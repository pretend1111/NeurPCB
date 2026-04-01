"""
agents/module_placer.py — Module Placer Agent

LLM 驱动的模块内布局。通过 tool-calling 选择 Skill 或原子操作，
观察结果后迭代优化，直到满足验收标准。

工具集：
- 观测工具：observe_module_layout, observe_violations
- Skill 工具：apply_skill_ldo, apply_skill_crystal, apply_skill_decap, apply_skill_force_directed, apply_skill_led, apply_skill_divider
- 原子操作：move_component, rotate_component, swap_components
- 终止：finish_placement
"""
from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field

from agents.base_agent import BaseAgent
from agents.analyzer import EnrichedModule
from skills.base import ComponentInput, PinPair, Placement, SkillResult
from geometry.core import Rect, calc_bbox, calc_overlap_area

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Module Placer 内部状态
# ---------------------------------------------------------------------------

@dataclass
class ModulePlacerState:
    """Module Placer 的可变状态"""
    module: EnrichedModule
    components: dict[str, ComponentInput]   # ref -> ComponentInput
    placements: dict[str, Placement]        # ref -> 当前放置
    connections: list[PinPair]              # 内部连接
    origin: tuple[float, float] = (0.0, 0.0)
    bbox_constraint: Rect | None = None     # 面积预算约束
    finished: bool = False


# ---------------------------------------------------------------------------
# 工具处理器（纯函数，操作 state）
# ---------------------------------------------------------------------------

def _observe_module_layout(state: ModulePlacerState) -> dict:
    """返回当前模块内所有器件的坐标、朝向"""
    layout = []
    for ref in state.module.components:
        p = state.placements.get(ref)
        c = state.components.get(ref)
        if p:
            layout.append({
                "ref": ref,
                "value": c.value if c else "",
                "x_mm": p.x_mm,
                "y_mm": p.y_mm,
                "angle_deg": p.angle_deg,
            })
        else:
            layout.append({"ref": ref, "value": c.value if c else "", "status": "unplaced"})

    bbox = _calc_current_bbox(state)
    return {
        "components": layout,
        "bbox": {"x": bbox.x, "y": bbox.y, "w": bbox.w, "h": bbox.h} if bbox else None,
        "placed_count": sum(1 for r in state.module.components if r in state.placements),
        "total_count": len(state.module.components),
    }


def _observe_ratsnest(state: ModulePlacerState) -> dict:
    """显示模块内所有电气连接（飞线），及已放置器件间的飞线长度"""
    nets = []
    for conn in state.connections:
        pa = state.placements.get(conn.ref_a)
        pb = state.placements.get(conn.ref_b)
        entry = {
            "net": f"{conn.ref_a}↔{conn.ref_b}",
            "weight": conn.weight,
        }
        if pa and pb:
            dist = math.hypot(pa.x_mm - pb.x_mm, pa.y_mm - pb.y_mm)
            entry["distance_mm"] = round(dist, 2)
            entry["status"] = "long" if dist > 5.0 else "ok"
        else:
            entry["status"] = "unplaced"
        nets.append(entry)

    # 按距离排序，最长的飞线排前面（最需要优化的）
    nets.sort(key=lambda n: -n.get("distance_mm", 999))

    total_length = sum(n.get("distance_mm", 0) for n in nets)
    long_count = sum(1 for n in nets if n.get("status") == "long")

    return {
        "connections": nets,
        "total_length_mm": round(total_length, 1),
        "long_connections": long_count,
        "total_connections": len(nets),
    }


def _observe_violations(state: ModulePlacerState) -> dict:
    """检查重叠和间距违规"""
    violations = []
    refs = [r for r in state.module.components if r in state.placements]
    for i in range(len(refs)):
        for j in range(i + 1, len(refs)):
            ri, rj = refs[i], refs[j]
            pi, pj = state.placements[ri], state.placements[rj]
            ci, cj = state.components.get(ri), state.components.get(rj)
            if not ci or not cj:
                continue
            # 简单矩形重叠检测
            rect_i = Rect.from_center(pi.x_mm, pi.y_mm, ci.width_mm, ci.height_mm)
            rect_j = Rect.from_center(pj.x_mm, pj.y_mm, cj.width_mm, cj.height_mm)
            overlap = calc_overlap_area(rect_i, rect_j)
            if overlap > 0:
                violations.append({
                    "type": "overlap",
                    "refs": [ri, rj],
                    "overlap_mm2": round(overlap, 3),
                })

            # 间距检查
            dist = math.hypot(pi.x_mm - pj.x_mm, pi.y_mm - pj.y_mm)
            min_dist = (ci.width_mm + cj.width_mm) / 2 * 0.6
            if dist < min_dist and overlap == 0:
                violations.append({
                    "type": "too_close",
                    "refs": [ri, rj],
                    "distance_mm": round(dist, 3),
                    "min_recommended_mm": round(min_dist, 3),
                })

    return {"violations": violations, "count": len(violations)}


def _move_component(state: ModulePlacerState, ref: str, x_mm: float, y_mm: float) -> dict:
    if ref not in state.components:
        return {"error": f"Component {ref} not in this module"}
    state.placements[ref] = Placement(ref, x_mm, y_mm,
                                       state.placements.get(ref, Placement(ref, 0, 0)).angle_deg)
    return {"status": "ok", "ref": ref, "x_mm": x_mm, "y_mm": y_mm}


def _rotate_component(state: ModulePlacerState, ref: str, angle_deg: float) -> dict:
    if ref not in state.components:
        return {"error": f"Component {ref} not in this module"}
    p = state.placements.get(ref)
    if p is None:
        return {"error": f"Component {ref} not yet placed"}
    state.placements[ref] = Placement(ref, p.x_mm, p.y_mm, angle_deg)
    return {"status": "ok", "ref": ref, "angle_deg": angle_deg}


def _swap_components(state: ModulePlacerState, ref_a: str, ref_b: str) -> dict:
    pa = state.placements.get(ref_a)
    pb = state.placements.get(ref_b)
    if not pa or not pb:
        return {"error": "Both components must be placed before swapping"}
    state.placements[ref_a] = Placement(ref_a, pb.x_mm, pb.y_mm, pa.angle_deg)
    state.placements[ref_b] = Placement(ref_b, pa.x_mm, pa.y_mm, pb.angle_deg)
    return {"status": "ok", "swapped": [ref_a, ref_b]}


def _apply_skill(state: ModulePlacerState, skill_name: str, params: dict) -> dict:
    """统一的 Skill 调用入口"""
    ox, oy = state.origin

    if skill_name == "ldo_layout":
        from skills.module.ldo_layout import skill_ldo_layout
        core = state.components.get(params.get("core_ic", ""))
        in_caps = [state.components[r] for r in params.get("input_caps", []) if r in state.components]
        out_caps = [state.components[r] for r in params.get("output_caps", []) if r in state.components]
        fb_res = [state.components[r] for r in params.get("feedback_resistors", []) if r in state.components]
        if not core:
            return {"error": "core_ic not found"}
        result = skill_ldo_layout(core, in_caps, out_caps, fb_res,
                                   origin=(ox, oy),
                                   signal_flow=params.get("signal_flow_direction", "left_to_right"))

    elif skill_name == "crystal_layout":
        from skills.module.crystal_layout import skill_crystal_layout
        xtal = state.components.get(params.get("crystal", ""))
        caps = [state.components[r] for r in params.get("load_caps", []) if r in state.components]
        if not xtal:
            return {"error": "crystal not found"}
        pin_pos = params.get("mcu_clock_pin_pos", [ox, oy])
        result = skill_crystal_layout(xtal, caps, tuple(pin_pos),
                                       approach_angle_deg=params.get("approach_angle_deg", 0))

    elif skill_name == "decap_cluster":
        from skills.module.decap_cluster import skill_decap_cluster
        core = state.components.get(params.get("core_ic", ""))
        caps = [state.components[r] for r in params.get("decaps", []) if r in state.components]
        if not core:
            return {"error": "core_ic not found"}
        result = skill_decap_cluster(core, (ox, oy), caps)

    elif skill_name == "force_directed":
        from skills.module.force_directed import skill_force_directed_place
        comps = [state.components[r] for r in state.module.components if r in state.components]
        result = skill_force_directed_place(
            comps, state.connections, origin=(ox, oy),
            bbox_constraint=state.bbox_constraint, seed=42)

    elif skill_name == "led_indicator":
        from skills.module.led_indicator import skill_led_indicator
        led = state.components.get(params.get("led", ""))
        res = state.components.get(params.get("resistor", ""))
        if not led or not res:
            return {"error": "led or resistor not found"}
        result = skill_led_indicator(led, res, origin=(ox, oy))

    elif skill_name == "voltage_divider":
        from skills.module.voltage_divider import skill_voltage_divider
        r_top = state.components.get(params.get("r_top", ""))
        r_bot = state.components.get(params.get("r_bottom", ""))
        if not r_top or not r_bot:
            return {"error": "r_top or r_bottom not found"}
        result = skill_voltage_divider(r_top, r_bot, origin=(ox, oy))

    elif skill_name == "compact_module":
        from skills.module.compact_module import skill_compact_module
        current = list(state.placements.values())
        if not current:
            return {"error": "No components placed yet, nothing to compact"}
        result = skill_compact_module(current, state.components, target_center=(ox, oy))

    else:
        return {"error": f"Unknown skill: {skill_name}"}

    # 应用 Skill 结果到 state
    for p in result.placements:
        if p.ref in state.components:
            state.placements[p.ref] = p

    return {
        "status": "ok",
        "skill": skill_name,
        "placed": [p.ref for p in result.placements],
        "bbox": {"x": result.bbox.x, "y": result.bbox.y, "w": result.bbox.w, "h": result.bbox.h},
        "description": result.description,
    }


def _finish_placement(state: ModulePlacerState) -> dict:
    state.finished = True
    bbox = _calc_current_bbox(state)
    return {
        "status": "finished",
        "placed_count": len(state.placements),
        "total_count": len(state.module.components),
        "bbox": {"x": bbox.x, "y": bbox.y, "w": bbox.w, "h": bbox.h} if bbox else None,
    }


def _calc_current_bbox(state: ModulePlacerState) -> Rect | None:
    pts = [(p.x_mm, p.y_mm) for p in state.placements.values()]
    if not pts:
        return None
    return calc_bbox(pts, margin=1.0)


# ---------------------------------------------------------------------------
# Tool 定义（JSON Schema）
# ---------------------------------------------------------------------------

_TOOLS_SCHEMA = {
    "observe_module_layout": {
        "desc": "View current placement state of all components in this module",
        "params": {"type": "object", "properties": {}, "required": []},
    },
    "observe_ratsnest": {
        "desc": "Show all electrical connections (ratsnest/flylines) between components. Shows which components need to be close and current distances. Long connections (>5mm) should be shortened by moving components closer.",
        "params": {"type": "object", "properties": {}, "required": []},
    },
    "observe_violations": {
        "desc": "Check for overlaps and spacing violations in current placement",
        "params": {"type": "object", "properties": {}, "required": []},
    },
    "move_component": {
        "desc": "Move a component to absolute coordinates (mm)",
        "params": {
            "type": "object",
            "properties": {
                "ref": {"type": "string", "description": "Component reference (e.g. U1)"},
                "x_mm": {"type": "number"},
                "y_mm": {"type": "number"},
            },
            "required": ["ref", "x_mm", "y_mm"],
        },
    },
    "rotate_component": {
        "desc": "Set component rotation angle (degrees: 0/90/180/270)",
        "params": {
            "type": "object",
            "properties": {
                "ref": {"type": "string"},
                "angle_deg": {"type": "number"},
            },
            "required": ["ref", "angle_deg"],
        },
    },
    "swap_components": {
        "desc": "Swap positions of two components",
        "params": {
            "type": "object",
            "properties": {
                "ref_a": {"type": "string"},
                "ref_b": {"type": "string"},
            },
            "required": ["ref_a", "ref_b"],
        },
    },
    "apply_skill": {
        "desc": "Apply a layout skill. Available skills: ldo_layout, crystal_layout, decap_cluster, force_directed, led_indicator, voltage_divider. Params depend on skill.",
        "params": {
            "type": "object",
            "properties": {
                "skill_name": {"type": "string", "enum": ["ldo_layout", "crystal_layout", "decap_cluster", "force_directed", "led_indicator", "voltage_divider", "compact_module"]},
                "params": {"type": "object", "description": "Skill-specific parameters"},
            },
            "required": ["skill_name", "params"],
        },
    },
    "finish_placement": {
        "desc": "Declare placement complete. Call this when all components are placed and no violations remain.",
        "params": {"type": "object", "properties": {}, "required": []},
    },
}


# ---------------------------------------------------------------------------
# Module Placer Agent
# ---------------------------------------------------------------------------

_MODULE_PLACER_SYSTEM_PROMPT = """\
You are a Module Placer Agent. Your task is to place electronic components within a STRICT area budget.

CRITICAL CONSTRAINTS:
1. ALL components must fit within the area budget.
2. Electrically connected components MUST be placed close together (check with observe_ratsnest).

Strategy:
1. Call apply_skill with "force_directed" — it uses connection weights to pull connected parts together.
2. Call observe_ratsnest to check connection distances. Any connection > 5mm is too long.
3. Call observe_violations to check for overlaps.
4. Move components to shorten long connections (move connected parts closer to each other).
5. If still too spread out, call apply_skill with "compact_module".
6. When done: all placed, no overlaps, no connections > 5mm → call finish_placement.

Rules:
- Place ALL components.
- Connected components should be < 3mm apart (critical for signal integrity).
- Core IC at center, decoupling caps ADJACENT to their IC (< 2mm).
- Stay within area budget.
- Minimum 0.3mm spacing.
"""


class ModulePlacerAgent(BaseAgent):
    """
    Module Placer：LLM 驱动的模块内布局。

    使用步骤：
        placer = ModulePlacerAgent()
        result = placer.place_module(module, components, connections, origin)
    """

    def __init__(self, model: str = "deepseek-chat"):
        super().__init__(
            name="ModulePlacer",
            system_prompt=_MODULE_PLACER_SYSTEM_PROMPT,
            model=model,
        )

    def place_module(
        self,
        module: EnrichedModule,
        components: dict[str, ComponentInput],
        connections: list[PinPair] | None = None,
        origin: tuple[float, float] = (0.0, 0.0),
        bbox_constraint: Rect | None = None,
        max_rounds: int = 15,
    ) -> SkillResult:
        """
        为一个模块执行布局。

        bbox_constraint: 最大允许区域（绝对坐标），force_directed 会受此约束
        返回 SkillResult（所有器件的放置坐标 + bbox）。
        """
        state = ModulePlacerState(
            module=module,
            components=components,
            placements={},
            connections=connections or [],
            origin=origin,
            bbox_constraint=bbox_constraint,
        )

        # 注册工具（闭包绑定 state）
        self._tools = []
        self._register_tools(state)

        # 构建 user prompt
        comp_desc = []
        for ref in module.components:
            c = components.get(ref)
            if c:
                comp_desc.append(f"  {ref}: {c.value} ({c.footprint}, {c.width_mm}x{c.height_mm}mm)")

        bbox_info = ""
        if bbox_constraint:
            bbox_info = (f"AREA BUDGET: {bbox_constraint.w:.1f} x {bbox_constraint.h:.1f} mm "
                         f"(center at {bbox_constraint.cx:.1f}, {bbox_constraint.cy:.1f}). "
                         f"ALL components must fit within this area!\n")

        # 构建连接关系描述
        conn_desc = []
        conns = connections or []
        for c in conns:
            conn_desc.append(f"  {c.ref_a} ↔ {c.ref_b} (weight={c.weight})")

        conn_text = ""
        if conn_desc:
            conn_text = (f"\nElectrical connections ({len(conns)} nets) — "
                         f"connected components MUST be placed close together:\n"
                         + "\n".join(conn_desc[:20]) + "\n")

        user_prompt = (
            f"Module: {module.module_name} ({module.module_id})\n"
            f"Type: {module.module_type}\n"
            f"Core component: {module.core_component}\n"
            f"Layout template hint: {module.layout_template_hint or 'none'}\n"
            f"Origin: ({origin[0]:.1f}, {origin[1]:.1f})\n"
            f"{bbox_info}"
            f"Components ({len(module.components)}):\n" + "\n".join(comp_desc) + "\n"
            f"{conn_text}\n"
            f"Place all components. Use observe_ratsnest to check connection lengths after placement."
        )

        # 运行 tool-calling 循环
        result = self.run_tools(user_prompt, max_rounds=max_rounds)

        # 如果 LLM 没调用 finish，但有放置结果，也可以用
        if not state.finished:
            logger.warning("[ModulePlacer] LLM did not call finish_placement, using current state")

        # 转换为 SkillResult
        placements = list(state.placements.values())
        bbox = _calc_current_bbox(state) or Rect(0, 0, 0, 0)

        return SkillResult(
            placements=placements,
            bbox=bbox,
            description=f"Module {module.module_name}: {len(placements)}/{len(module.components)} placed",
        )

    def _register_tools(self, state: ModulePlacerState) -> None:
        """注册所有工具，闭包绑定 state"""
        from agents.llm_client import ToolDef

        for name, schema in _TOOLS_SCHEMA.items():
            if name == "observe_module_layout":
                handler = lambda _state=state: _observe_module_layout(_state)
            elif name == "observe_ratsnest":
                handler = lambda _state=state: _observe_ratsnest(_state)
            elif name == "observe_violations":
                handler = lambda _state=state: _observe_violations(_state)
            elif name == "move_component":
                handler = lambda ref, x_mm, y_mm, _state=state: _move_component(_state, ref, x_mm, y_mm)
            elif name == "rotate_component":
                handler = lambda ref, angle_deg, _state=state: _rotate_component(_state, ref, angle_deg)
            elif name == "swap_components":
                handler = lambda ref_a, ref_b, _state=state: _swap_components(_state, ref_a, ref_b)
            elif name == "apply_skill":
                handler = lambda skill_name, params, _state=state: _apply_skill(_state, skill_name, params)
            elif name == "finish_placement":
                handler = lambda _state=state: _finish_placement(_state)
            else:
                continue

            self.register_tool(name, schema["desc"], schema["params"], handler)
