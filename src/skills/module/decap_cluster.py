"""
skill_decap_cluster — 去耦电容扇形排列

将去耦电容围绕核心 IC 的电源引脚排列。
每颗电容对准最近的电源引脚，最小化 3D 环路面积。
"""
from __future__ import annotations

import math
from skills.base import ComponentInput, Placement, SkillResult
from geometry.core import Rect, calc_bbox


def skill_decap_cluster(
    core_ic: ComponentInput,
    core_ic_pos: tuple[float, float],
    decaps: list[ComponentInput],
    power_pin_offsets: list[tuple[float, float]] | None = None,
    clearance_mm: float = 0.8,
    ring_gap_mm: float = 1.5,
) -> SkillResult:
    """
    去耦电容围绕 IC 排列。

    core_ic: 核心 IC 信息
    core_ic_pos: IC 中心坐标 (x, y) mm
    decaps: 去耦电容列表
    power_pin_offsets: IC 电源引脚相对于 IC 中心的偏移 [(dx,dy), ...]
                       如果不提供，则均匀环绕
    clearance_mm: 电容之间的最小间距
    ring_gap_mm: 电容到 IC 边缘的距离
    """
    cx, cy = core_ic_pos
    n = len(decaps)

    if n == 0:
        bbox = Rect.from_center(cx, cy, core_ic.width_mm, core_ic.height_mm)
        return SkillResult(placements=[], bbox=bbox, description="No decaps")

    # IC 外边缘半径（取长边/2）
    ic_radius = max(core_ic.width_mm, core_ic.height_mm) / 2 + ring_gap_mm

    placements = []

    if power_pin_offsets and len(power_pin_offsets) >= n:
        # 模式 A：每颗电容对准一个电源引脚
        for i, cap in enumerate(decaps):
            px, py = power_pin_offsets[i]
            # 从 IC 中心到引脚方向上，放在 IC 边缘外
            angle = math.atan2(py, px)
            dist = ic_radius + cap.height_mm / 2
            x = cx + dist * math.cos(angle)
            y = cy + dist * math.sin(angle)
            # 电容朝向：沿径向
            orient = math.degrees(angle) + 90
            placements.append(Placement(cap.ref, round(x, 3), round(y, 3), round(orient % 360, 1)))
    else:
        # 模式 B：均匀环绕
        for i, cap in enumerate(decaps):
            angle = 2 * math.pi * i / n - math.pi / 2  # 从顶部开始
            dist = ic_radius + cap.height_mm / 2
            x = cx + dist * math.cos(angle)
            y = cy + dist * math.sin(angle)
            orient = math.degrees(angle) + 90
            placements.append(Placement(cap.ref, round(x, 3), round(y, 3), round(orient % 360, 1)))

    all_pts = [(p.x_mm, p.y_mm) for p in placements] + [core_ic_pos]
    margin = max(c.width_mm for c in decaps) / 2 + clearance_mm
    bbox = calc_bbox(all_pts, margin=margin)

    return SkillResult(
        placements=placements,
        bbox=bbox,
        description=f"Decap cluster: {n} caps around {core_ic.ref}",
    )
