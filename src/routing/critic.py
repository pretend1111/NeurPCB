"""
routing/critic.py — Critic 质量评审员

Fast Check: 纯规则引擎，毫秒级，每次操作后自动运行
Deep Review: LLM 驱动，按领域知识库逐项检查（由 Architect 触发）
"""
from __future__ import annotations

import math
import logging
from dataclasses import dataclass, field

from geometry.core import Rect, calc_distance, rects_overlap, calc_overlap_area
from agents.board_map import BoardMap

logger = logging.getLogger(__name__)


@dataclass
class Issue:
    """单个问题"""
    id: str
    severity: str           # critical / major / minor
    category: str           # overlap / board_edge / spacing / decoupling / orientation / ...
    description: str
    affected_module: str = ""
    affected_components: list[str] = field(default_factory=list)
    suggestion: str = ""
    fix_agent: str = ""     # module_placer_M01 / global_placer / ...


@dataclass
class CriticReport:
    """Critic 评审报告"""
    total_issues: int = 0
    critical: int = 0
    major: int = 0
    minor: int = 0
    issues: list[Issue] = field(default_factory=list)
    passed: bool = True

    def add(self, issue: Issue):
        self.issues.append(issue)
        self.total_issues += 1
        if issue.severity == "critical":
            self.critical += 1
            self.passed = False
        elif issue.severity == "major":
            self.major += 1
        else:
            self.minor += 1

    def summary(self) -> str:
        lines = [
            f"Critic Report: {self.total_issues} issues "
            f"({self.critical} critical, {self.major} major, {self.minor} minor)",
            f"  Status: {'PASS' if self.passed else 'FAIL'}",
        ]
        for iss in self.issues:
            lines.append(f"  [{iss.severity.upper()}] {iss.category}: {iss.description}")
            if iss.suggestion:
                lines.append(f"    → {iss.suggestion}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Fast Check（纯规则引擎）
# ---------------------------------------------------------------------------

def fast_check(
    board_map: BoardMap,
    component_positions: dict[str, tuple[float, float]] | None = None,
    component_sizes: dict[str, tuple[float, float]] | None = None,
    min_board_edge_mm: float = 0.5,
    min_component_spacing_mm: float = 0.2,
) -> CriticReport:
    """
    Fast Check：毫秒级规则检查。

    board_map: 当前地图（模块级检查）
    component_positions: {ref: (x, y)} 器件级坐标（可选，用于更精细的检查）
    component_sizes: {ref: (w, h)} 器件封装尺寸（可选）
    """
    report = CriticReport()
    issue_counter = 0

    def _add(severity, category, desc, module="", comps=None, suggestion="", fix=""):
        nonlocal issue_counter
        issue_counter += 1
        report.add(Issue(
            id=f"FC-{issue_counter:03d}",
            severity=severity, category=category, description=desc,
            affected_module=module,
            affected_components=comps or [],
            suggestion=suggestion, fix_agent=fix,
        ))

    # --- 模块级检查 ---

    # 1. 模块重叠
    for i in range(len(board_map.modules)):
        for j in range(i + 1, len(board_map.modules)):
            mi, mj = board_map.modules[i], board_map.modules[j]
            area = calc_overlap_area(mi.rect, mj.rect)
            if area > 0:
                _add("critical", "module_overlap",
                     f"Modules {mi.module_id} and {mj.module_id} overlap by {area:.1f}mm²",
                     suggestion=f"Move {mi.module_id} or {mj.module_id} apart",
                     fix="global_placer")

    # 2. 模块超出板框
    for m in board_map.modules:
        if m.rect.x < board_map.board.x or m.rect.y < board_map.board.y or \
           m.rect.x2 > board_map.board.x2 or m.rect.y2 > board_map.board.y2:
            _add("critical", "board_overflow",
                 f"Module {m.module_id} exceeds board boundary",
                 module=m.module_id,
                 suggestion=f"Move {m.module_id} inside board or reduce module size",
                 fix="global_placer")

    # 3. 模块间距过小
    for i in range(len(board_map.modules)):
        for j in range(i + 1, len(board_map.modules)):
            mi, mj = board_map.modules[i], board_map.modules[j]
            gap = board_map.module_distance(mi.module_id, mj.module_id)
            if 0 < gap < 0.5:
                _add("major", "module_spacing",
                     f"Modules {mi.module_id} and {mj.module_id} gap is only {gap:.1f}mm (< 0.5mm)",
                     suggestion="Increase gap for routing corridor",
                     fix="global_placer")

    # --- 器件级检查（如果提供了坐标）---

    if component_positions and component_sizes:
        refs = list(component_positions.keys())

        # 4. 器件重叠
        for i in range(len(refs)):
            for j in range(i + 1, len(refs)):
                ri, rj = refs[i], refs[j]
                pi, pj = component_positions[ri], component_positions[rj]
                si, sj = component_sizes.get(ri, (1, 1)), component_sizes.get(rj, (1, 1))
                rect_i = Rect.from_center(pi[0], pi[1], si[0], si[1])
                rect_j = Rect.from_center(pj[0], pj[1], sj[0], sj[1])
                area = calc_overlap_area(rect_i, rect_j)
                if area > 0:
                    _add("critical", "component_overlap",
                         f"Components {ri} and {rj} overlap by {area:.2f}mm²",
                         comps=[ri, rj],
                         suggestion=f"Move {ri} or {rj} apart")

        # 5. 器件板边距离
        for ref, (x, y) in component_positions.items():
            sz = component_sizes.get(ref, (1, 1))
            comp_rect = Rect.from_center(x, y, sz[0], sz[1])
            edge_dist = min(
                comp_rect.x - board_map.board.x,
                comp_rect.y - board_map.board.y,
                board_map.board.x2 - comp_rect.x2,
                board_map.board.y2 - comp_rect.y2,
            )
            if edge_dist < min_board_edge_mm:
                _add("major", "board_edge_distance",
                     f"Component {ref} is {edge_dist:.2f}mm from board edge (< {min_board_edge_mm}mm)",
                     comps=[ref],
                     suggestion=f"Move {ref} at least {min_board_edge_mm}mm from board edge")

    return report


# ---------------------------------------------------------------------------
# Deep Review（LLM 驱动）
# ---------------------------------------------------------------------------

def deep_review(
    board_map: BoardMap,
    board_type: str = "digital",
    enriched_modules: list[dict] | None = None,
) -> CriticReport:
    """
    Deep Review：LLM 驱动的质量审查。

    当前实现为规则增强版（不实际调用 LLM），检查更多领域知识项。
    后续可升级为真正的 LLM 驱动。
    """
    report = fast_check(board_map)
    issue_counter = report.total_issues

    def _add(severity, category, desc, module="", comps=None, suggestion=""):
        nonlocal issue_counter
        issue_counter += 1
        report.add(Issue(
            id=f"DR-{issue_counter:03d}",
            severity=severity, category=category, description=desc,
            affected_module=module,
            affected_components=comps or [],
            suggestion=suggestion,
        ))

    # 高连接权重模块距离检查
    for link in board_map.links:
        if link.weight >= 5:
            dist = board_map.module_distance(link.from_id, link.to_id)
            if dist > 15:
                _add("major", "high_weight_distance",
                     f"High-weight connection {link.from_id}↔{link.to_id} "
                     f"(weight={link.weight}) has gap {dist:.1f}mm (> 15mm)",
                     suggestion=f"Move {link.from_id} and {link.to_id} closer together")

    # 板面利用率检查
    util = board_map.calc_utilization()
    if util > 90:
        _add("major", "utilization",
             f"Board utilization is {util}% (> 90%), very tight layout",
             suggestion="Consider increasing board size or reducing module count")
    elif util < 20:
        _add("minor", "utilization",
             f"Board utilization is only {util}%, layout may be too sparse",
             suggestion="Consider compacting modules closer together")

    return report
