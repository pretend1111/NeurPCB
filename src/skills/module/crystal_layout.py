"""
skill_crystal_layout — 晶振及负载电容布局

晶振紧贴 MCU 时钟引脚，两颗负载电容对称放置在晶振两侧，
周围留净空区。
"""
from __future__ import annotations

import math
from skills.base import ComponentInput, Placement, SkillResult
from geometry.core import Rect, calc_bbox


def skill_crystal_layout(
    crystal: ComponentInput,
    load_caps: list[ComponentInput],
    mcu_clock_pin_pos: tuple[float, float],
    approach_angle_deg: float = 0.0,
    crystal_distance_mm: float = 2.0,
    cap_offset_mm: float = 1.5,
    keepout_margin_mm: float = 1.0,
) -> SkillResult:
    """
    晶振布局。

    mcu_clock_pin_pos: MCU 时钟引脚的坐标
    approach_angle_deg: 晶振相对于时钟引脚的方向角（0=右，90=下）
    crystal_distance_mm: 晶振中心到时钟引脚的距离
    cap_offset_mm: 负载电容到晶振中心的偏移（沿垂直于接近方向）
    keepout_margin_mm: 净空区外扩
    """
    px, py = mcu_clock_pin_pos
    angle_rad = math.radians(approach_angle_deg)

    # 晶振位置：从时钟引脚沿 approach_angle 方向偏移
    xtal_x = px + crystal_distance_mm * math.cos(angle_rad)
    xtal_y = py + crystal_distance_mm * math.sin(angle_rad)

    placements = [
        Placement(crystal.ref, round(xtal_x, 3), round(xtal_y, 3), approach_angle_deg % 360),
    ]

    # 负载电容：对称放置在晶振两侧（垂直于接近方向）
    perp_rad = angle_rad + math.pi / 2
    for i, cap in enumerate(load_caps[:2]):
        sign = 1 if i == 0 else -1
        cx = xtal_x + sign * cap_offset_mm * math.cos(perp_rad)
        cy = xtal_y + sign * cap_offset_mm * math.sin(perp_rad)
        placements.append(Placement(cap.ref, round(cx, 3), round(cy, 3), approach_angle_deg % 360))

    # 多余的电容（极少见）：堆叠在第一颗后面
    for i, cap in enumerate(load_caps[2:], start=2):
        base = placements[1 + (i % 2)]
        offset = (i // 2) * (cap.width_mm + 0.5)
        cx = base.x_mm + offset * math.cos(angle_rad)
        cy = base.y_mm + offset * math.sin(angle_rad)
        placements.append(Placement(cap.ref, round(cx, 3), round(cy, 3), approach_angle_deg % 360))

    all_pts = [(p.x_mm, p.y_mm) for p in placements]
    bbox = calc_bbox(all_pts, margin=keepout_margin_mm)

    return SkillResult(
        placements=placements,
        bbox=bbox,
        description=f"Crystal layout: {crystal.ref} + {len(load_caps)} load caps",
    )
