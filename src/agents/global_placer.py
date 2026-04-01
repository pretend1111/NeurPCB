"""
agents/global_placer.py — Global Placer Agent

LLM 驱动的全局模块排布。操作对象是模块矩形，不是单个器件。
通过 tool-calling 选择力导向排布、手动移动、重叠消解等操作。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from agents.base_agent import BaseAgent
from agents.board_map import BoardMap, ModuleRect, InterModuleLink
from geometry.core import Rect
from skills.global_skills.gp_skills import (
    ModuleForGP, skill_gp_force_directed, skill_gp_resolve_overlap,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 工具处理器
# ---------------------------------------------------------------------------

def _gp_observe_map(bmap: BoardMap) -> dict:
    return {"map": bmap.to_text()}


def _gp_move_module(bmap: BoardMap, module_id: str, cx: float, cy: float) -> dict:
    if bmap.move_module(module_id, cx, cy):
        return {"status": "ok", "module_id": module_id, "cx": cx, "cy": cy}
    return {"error": f"Module {module_id} not found"}


def _gp_move_module_relative(bmap: BoardMap, module_id: str, dx: float, dy: float) -> dict:
    if bmap.move_module_relative(module_id, dx, dy):
        m = bmap.get_module(module_id)
        return {"status": "ok", "module_id": module_id, "cx": m.rect.cx, "cy": m.rect.cy}
    return {"error": f"Module {module_id} not found"}


def _gp_swap_modules(bmap: BoardMap, module_a: str, module_b: str) -> dict:
    if bmap.swap_modules(module_a, module_b):
        return {"status": "ok", "swapped": [module_a, module_b]}
    return {"error": "Module(s) not found"}


def _gp_check_overlap(bmap: BoardMap) -> dict:
    overlaps = bmap.check_overlaps()
    return {"overlaps": [{"a": a, "b": b, "area_mm2": ar} for a, b, ar in overlaps],
            "count": len(overlaps)}


def _gp_check_board_fit(bmap: BoardMap) -> dict:
    out = bmap.check_board_fit()
    return {"out_of_board": out, "count": len(out)}


def _gp_query_distance(bmap: BoardMap, module_a: str, module_b: str) -> dict:
    d = bmap.module_distance(module_a, module_b)
    return {"module_a": module_a, "module_b": module_b, "distance_mm": round(d, 2)}


def _gp_apply_force_directed(bmap: BoardMap) -> dict:
    """用力导向算法自动排布所有模块"""
    gp_modules = []
    for m in bmap.modules:
        weights = {}
        for link in bmap.links:
            if link.from_id == m.module_id:
                weights[link.to_id] = weights.get(link.to_id, 0) + link.weight
            elif link.to_id == m.module_id:
                weights[link.from_id] = weights.get(link.from_id, 0) + link.weight
        anchored = None
        if m.anchored_to:
            anchored = (m.rect.cx, m.rect.cy)
        gp_modules.append(ModuleForGP(m.module_id, m.rect.w, m.rect.h, weights, anchored))

    placements = skill_gp_force_directed(gp_modules, bmap.board)

    for p in placements:
        bmap.move_module(p.module_id, p.cx, p.cy)

    return {
        "status": "ok",
        "placed": len(placements),
        "routability": bmap.calc_routability_score(),
    }


def _gp_resolve_overlap(bmap: BoardMap) -> dict:
    """消解所有模块重叠"""
    modules_input = [(m.module_id, m.rect) for m in bmap.modules]
    placements = skill_gp_resolve_overlap(modules_input, bmap.board)

    for p in placements:
        bmap.move_module(p.module_id, p.cx, p.cy)

    overlaps_after = bmap.check_overlaps()
    return {"status": "ok", "remaining_overlaps": len(overlaps_after)}


def _gp_finish(bmap: BoardMap) -> dict:
    overlaps = bmap.check_overlaps()
    oob = bmap.check_board_fit()
    return {
        "status": "finished",
        "overlaps": len(overlaps),
        "out_of_board": len(oob),
        "utilization": bmap.calc_utilization(),
        "routability": bmap.calc_routability_score(),
    }


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

_GP_TOOLS = {
    "gp_observe_map": {
        "desc": "Get current board map snapshot (all module positions, connections, metrics)",
        "params": {"type": "object", "properties": {}, "required": []},
    },
    "gp_move_module": {
        "desc": "Move a module center to absolute coordinates (mm)",
        "params": {
            "type": "object",
            "properties": {
                "module_id": {"type": "string"},
                "cx": {"type": "number", "description": "center X in mm"},
                "cy": {"type": "number", "description": "center Y in mm"},
            },
            "required": ["module_id", "cx", "cy"],
        },
    },
    "gp_move_module_relative": {
        "desc": "Shift a module by dx, dy (mm)",
        "params": {
            "type": "object",
            "properties": {
                "module_id": {"type": "string"},
                "dx": {"type": "number"},
                "dy": {"type": "number"},
            },
            "required": ["module_id", "dx", "dy"],
        },
    },
    "gp_swap_modules": {
        "desc": "Swap positions of two modules",
        "params": {
            "type": "object",
            "properties": {
                "module_a": {"type": "string"},
                "module_b": {"type": "string"},
            },
            "required": ["module_a", "module_b"],
        },
    },
    "gp_check_overlap": {
        "desc": "Check if any module rectangles overlap",
        "params": {"type": "object", "properties": {}, "required": []},
    },
    "gp_check_board_fit": {
        "desc": "Check if all modules fit within board outline",
        "params": {"type": "object", "properties": {}, "required": []},
    },
    "gp_query_distance": {
        "desc": "Query the gap distance between two modules",
        "params": {
            "type": "object",
            "properties": {
                "module_a": {"type": "string"},
                "module_b": {"type": "string"},
            },
            "required": ["module_a", "module_b"],
        },
    },
    "gp_apply_force_directed": {
        "desc": "Auto-arrange all modules using force-directed algorithm based on connection weights",
        "params": {"type": "object", "properties": {}, "required": []},
    },
    "gp_resolve_overlap": {
        "desc": "Push overlapping modules apart with minimum displacement",
        "params": {"type": "object", "properties": {}, "required": []},
    },
    "gp_finish": {
        "desc": "Declare global placement complete. Call when no overlaps and all modules fit on board.",
        "params": {"type": "object", "properties": {}, "required": []},
    },
}


# ---------------------------------------------------------------------------
# Global Placer Agent
# ---------------------------------------------------------------------------

_GP_SYSTEM_PROMPT = """\
You are a Global Placer Agent. Your task is to arrange module rectangles on a PCB board.

You operate on MODULE RECTANGLES, not individual components. Each module is a black box with a fixed size.

Strategy:
1. Call gp_observe_map to see the current state.
2. Call gp_apply_force_directed to auto-arrange based on connection weights.
3. Call gp_check_overlap to verify no overlaps. If overlaps exist, call gp_resolve_overlap.
4. Call gp_check_board_fit to verify all modules fit within the board.
5. Use gp_move_module or gp_move_module_relative to fine-tune positions.
6. Prioritize: modules with high connection weight should be close together.
7. Anchored modules must not be moved.
8. When satisfied, call gp_finish.

Rules:
- No module overlaps allowed.
- All modules must fit within the board outline.
- High-weight connections should have short distances.
- Leave routing corridors (≥1mm gaps) between modules.
"""


class GlobalPlacerAgent(BaseAgent):

    def __init__(self, model: str = "deepseek-chat"):
        super().__init__(
            name="GlobalPlacer",
            system_prompt=_GP_SYSTEM_PROMPT,
            model=model,
        )

    def place_global(
        self,
        board_map: BoardMap,
        max_rounds: int = 15,
    ) -> BoardMap:
        """
        执行全局排布。

        board_map: 初始地图（模块已有估算尺寸，位置待确定）
        返回: 排布后的 board_map（原地修改）
        """
        self._tools = []
        self._register_tools(board_map)

        user_prompt = (
            f"Please arrange {len(board_map.modules)} modules on a "
            f"{board_map.board.w:.0f}×{board_map.board.h:.0f}mm board.\n"
            f"Start by observing the current map."
        )

        self.run_tools(user_prompt, max_rounds=max_rounds)
        return board_map

    def _register_tools(self, bmap: BoardMap) -> None:
        from agents.llm_client import ToolDef

        handlers = {
            "gp_observe_map": lambda _b=bmap: _gp_observe_map(_b),
            "gp_move_module": lambda module_id, cx, cy, _b=bmap: _gp_move_module(_b, module_id, cx, cy),
            "gp_move_module_relative": lambda module_id, dx, dy, _b=bmap: _gp_move_module_relative(_b, module_id, dx, dy),
            "gp_swap_modules": lambda module_a, module_b, _b=bmap: _gp_swap_modules(_b, module_a, module_b),
            "gp_check_overlap": lambda _b=bmap: _gp_check_overlap(_b),
            "gp_check_board_fit": lambda _b=bmap: _gp_check_board_fit(_b),
            "gp_query_distance": lambda module_a, module_b, _b=bmap: _gp_query_distance(_b, module_a, module_b),
            "gp_apply_force_directed": lambda _b=bmap: _gp_apply_force_directed(_b),
            "gp_resolve_overlap": lambda _b=bmap: _gp_resolve_overlap(_b),
            "gp_finish": lambda _b=bmap: _gp_finish(_b),
        }

        for name, schema in _GP_TOOLS.items():
            self.register_tool(name, schema["desc"], schema["params"], handlers[name])
