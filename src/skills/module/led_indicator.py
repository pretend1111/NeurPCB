"""
skill_led_indicator — LED + 限流电阻紧凑排列

LED 和电阻串联紧贴，LED 朝向统一。
"""
from __future__ import annotations

from skills.base import ComponentInput, Placement, SkillResult
from geometry.core import Rect, calc_bbox


def skill_led_indicator(
    led: ComponentInput,
    resistor: ComponentInput,
    origin: tuple[float, float] = (0.0, 0.0),
    orientation_deg: float = 0.0,
    gap_mm: float = 0.5,
) -> SkillResult:
    """
    LED + 限流电阻布局。

    orientation_deg: 0=电阻在左/LED在右, 90=电阻在上/LED在下
    """
    ox, oy = origin
    # 电阻和 LED 沿主轴串联排列
    import math
    rad = math.radians(orientation_deg)
    cos_a, sin_a = math.cos(rad), math.sin(rad)

    half_r = resistor.width_mm / 2
    half_l = led.width_mm / 2
    total_half = half_r + gap_mm / 2

    # 电阻在负方向，LED 在正方向
    rx = ox - total_half * cos_a
    ry = oy - total_half * sin_a
    lx = ox + (half_r + gap_mm + half_l) / 2 * cos_a
    ly = oy + (half_r + gap_mm + half_l) / 2 * sin_a

    placements = [
        Placement(resistor.ref, round(rx, 3), round(ry, 3), orientation_deg),
        Placement(led.ref, round(lx, 3), round(ly, 3), orientation_deg),
    ]

    bbox = calc_bbox([(p.x_mm, p.y_mm) for p in placements], margin=0.5)
    return SkillResult(placements=placements, bbox=bbox,
                       description=f"LED indicator: {resistor.ref} + {led.ref}")
