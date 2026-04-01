"""
skill_voltage_divider — 电阻分压器布局

两颗电阻串联紧凑排列，中间抽头点靠近采样目标。
"""
from __future__ import annotations

import math
from skills.base import ComponentInput, Placement, SkillResult
from geometry.core import Rect, calc_bbox


def skill_voltage_divider(
    r_top: ComponentInput,
    r_bottom: ComponentInput,
    origin: tuple[float, float] = (0.0, 0.0),
    orientation_deg: float = 0.0,
    gap_mm: float = 0.3,
) -> SkillResult:
    """
    分压器布局：R_top — 抽头 — R_bottom 线性排列。

    origin: 抽头中心坐标（两电阻交接点）
    orientation_deg: 排列方向（0=水平，90=垂直）
    """
    ox, oy = origin
    rad = math.radians(orientation_deg)
    cos_a, sin_a = math.cos(rad), math.sin(rad)

    # R_top 在负方向（输入侧），R_bottom 在正方向（地侧）
    offset_top = r_top.width_mm / 2 + gap_mm / 2
    offset_bot = r_bottom.width_mm / 2 + gap_mm / 2

    placements = [
        Placement(
            r_top.ref,
            round(ox - offset_top * cos_a, 3),
            round(oy - offset_top * sin_a, 3),
            orientation_deg,
        ),
        Placement(
            r_bottom.ref,
            round(ox + offset_bot * cos_a, 3),
            round(oy + offset_bot * sin_a, 3),
            orientation_deg,
        ),
    ]

    bbox = calc_bbox([(p.x_mm, p.y_mm) for p in placements], margin=0.5)
    return SkillResult(placements=placements, bbox=bbox,
                       description=f"Voltage divider: {r_top.ref} / {r_bottom.ref}")
