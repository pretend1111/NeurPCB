"""
geometry — 纯几何计算层

纯算法，不碰 KiCad API，不碰 LLM。
所有坐标/尺寸单位统一为 mm。
"""
from geometry.core import (
    calc_distance,
    calc_bbox,
    calc_overlap,
    calc_overlap_area,
    rects_overlap,
    resolve_overlap_minimum_displacement,
    point_in_rect,
    Rect,
)
from geometry.ratsnest import (
    calc_ratsnest_crossings,
    calc_ratsnest_total_length,
    segments_intersect,
)
from geometry.congestion import (
    calc_congestion_heatmap,
    calc_force_field_energy,
)
from geometry.channel import (
    calc_channel_capacity,
)
