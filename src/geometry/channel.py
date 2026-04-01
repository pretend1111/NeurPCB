"""
geometry/channel.py — 通道容量计算

计算两个模块之间的间隙能容纳多少条走线。
"""
from __future__ import annotations

import math


def calc_channel_capacity(
    gap_width_mm: float,
    layer_count: int = 1,
    min_spacing_mm: float = 0.15,
    min_width_mm: float = 0.15,
    via_diameter_mm: float = 0.0,
) -> int:
    """
    通道可容纳走线数。

    gap_width_mm: 通道宽度（两个模块矩形之间的间隙）
    layer_count: 可用布线层数
    min_spacing_mm: 最小线间距（net class 规则）
    min_width_mm: 最小线宽
    via_diameter_mm: 如果需要换层，过孔直径（0 表示不考虑过孔占位）

    返回: 能通过该通道的最大走线数
    """
    if gap_width_mm <= 0 or layer_count <= 0:
        return 0

    # 每条线占用的宽度 = 线宽 + 一侧间距
    pitch = min_width_mm + min_spacing_mm

    # 单层能容纳的线数（两侧各留半个间距作为边距）
    usable_width = gap_width_mm - min_spacing_mm
    if usable_width <= 0:
        return 0

    traces_per_layer = max(0, int(math.floor(usable_width / pitch)))

    # 多层时，考虑过孔占位（过孔需要在通道入口/出口处占用面积）
    total = traces_per_layer * layer_count

    if via_diameter_mm > 0 and layer_count > 1:
        # 过孔阵列在通道两端各占一排
        # 简化：每个过孔占 (via_diameter + spacing) 的宽度
        via_pitch = via_diameter_mm + min_spacing_mm
        vias_per_row = max(0, int(math.floor(usable_width / via_pitch)))
        # 额外层的走线需要过孔，能穿过的过孔数限制了额外层的走线数
        extra_layers = layer_count - 1
        total = traces_per_layer + min(traces_per_layer * extra_layers, vias_per_row * extra_layers)

    return total
