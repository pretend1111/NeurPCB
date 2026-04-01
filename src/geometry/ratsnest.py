"""
geometry/ratsnest.py — 飞线（Ratsnest）分析

飞线交叉数（扫除线算法）、总长度统计。
"""
from __future__ import annotations

import math


def calc_ratsnest_total_length(
    ratsnest: list[tuple[tuple[float, float], tuple[float, float]]],
) -> float:
    """
    飞线总长度 (mm)。

    ratsnest: [((x1,y1), (x2,y2)), ...]
    """
    total = 0.0
    for (x1, y1), (x2, y2) in ratsnest:
        total += math.hypot(x2 - x1, y2 - y1)
    return total


def segments_intersect(
    p1: tuple[float, float], p2: tuple[float, float],
    p3: tuple[float, float], p4: tuple[float, float],
) -> bool:
    """
    判断线段 p1-p2 和 p3-p4 是否相交（不含端点重合）。
    使用叉积法。
    """
    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    d1 = cross(p3, p4, p1)
    d2 = cross(p3, p4, p2)
    d3 = cross(p1, p2, p3)
    d4 = cross(p1, p2, p4)

    if ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and \
       ((d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0)):
        return True

    # 共线情况下的重叠检测（简化：不处理共线重叠，PCB 飞线极少共线）
    return False


def calc_ratsnest_crossings(
    ratsnest: list[tuple[tuple[float, float], tuple[float, float]]],
) -> int:
    """
    飞线交叉数。

    暴力 O(n²) 逐对检测，对于 PCB 飞线数量 (<500) 足够快。
    后续如需优化可改为扫除线算法。

    ratsnest: [((x1,y1), (x2,y2)), ...]
    返回: 交叉对数
    """
    n = len(ratsnest)
    crossings = 0
    for i in range(n):
        a1, a2 = ratsnest[i]
        for j in range(i + 1, n):
            b1, b2 = ratsnest[j]
            if segments_intersect(a1, a2, b1, b2):
                crossings += 1
    return crossings
