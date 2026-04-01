"""
geometry/congestion.py — 拥塞热力图 + 磁力场势能

将板面划分为网格，计算每个网格的飞线穿越密度。
磁力场模型将模块间连接建模为带权重的弹簧力。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from geometry.core import Rect
from geometry.ratsnest import segments_intersect


@dataclass
class HeatmapCell:
    """热力图单元格"""
    x: float
    y: float
    w: float
    h: float
    density: float = 0.0    # 穿越飞线数


@dataclass
class HeatmapResult:
    """热力图结果"""
    cells: list[list[HeatmapCell]]      # [row][col]
    grid_size_mm: float
    max_density: float
    avg_density: float
    hotspots: list[HeatmapCell] = field(default_factory=list)  # density > 2x avg


def calc_congestion_heatmap(
    region: Rect,
    ratsnest: list[tuple[tuple[float, float], tuple[float, float]]],
    grid_size_mm: float = 5.0,
    hotspot_threshold: float = 2.0,
) -> HeatmapResult:
    """
    区域拥塞热力图。

    将 region 划分为 grid_size_mm 的网格，统计每个网格被多少条飞线穿越。

    region: 分析区域（通常是板框）
    ratsnest: 飞线列表 [((x1,y1), (x2,y2)), ...]
    grid_size_mm: 网格尺寸
    hotspot_threshold: 热点阈值（density > avg * threshold 的格子视为热点）
    """
    cols = max(1, int(math.ceil(region.w / grid_size_mm)))
    rows = max(1, int(math.ceil(region.h / grid_size_mm)))
    cell_w = region.w / cols
    cell_h = region.h / rows

    # 初始化网格
    cells: list[list[HeatmapCell]] = []
    for r in range(rows):
        row = []
        for c in range(cols):
            row.append(HeatmapCell(
                x=region.x + c * cell_w,
                y=region.y + r * cell_h,
                w=cell_w,
                h=cell_h,
            ))
        cells.append(row)

    # 统计每个格子被穿越的飞线数
    for (x1, y1), (x2, y2) in ratsnest:
        # 粗略判断：飞线 bbox 与格子有交集，则认为穿越
        rn_min_x, rn_max_x = min(x1, x2), max(x1, x2)
        rn_min_y, rn_max_y = min(y1, y2), max(y1, y2)

        # 只遍历飞线 bbox 覆盖的格子
        c_start = max(0, int((rn_min_x - region.x) / cell_w))
        c_end = min(cols, int((rn_max_x - region.x) / cell_w) + 1)
        r_start = max(0, int((rn_min_y - region.y) / cell_h))
        r_end = min(rows, int((rn_max_y - region.y) / cell_h) + 1)

        for r in range(r_start, r_end):
            for c in range(c_start, c_end):
                cell = cells[r][c]
                # 精确检测：飞线是否与格子矩形的对角线相交（简化近似）
                # 对于热力图级别的分析，bbox 级检测已经够用
                cells[r][c].density += 1

    # 统计
    all_densities = [cells[r][c].density for r in range(rows) for c in range(cols)]
    max_d = max(all_densities) if all_densities else 0
    avg_d = sum(all_densities) / len(all_densities) if all_densities else 0

    hotspots = []
    if avg_d > 0:
        for r in range(rows):
            for c in range(cols):
                if cells[r][c].density > avg_d * hotspot_threshold:
                    hotspots.append(cells[r][c])

    return HeatmapResult(
        cells=cells,
        grid_size_mm=grid_size_mm,
        max_density=max_d,
        avg_density=avg_d,
        hotspots=hotspots,
    )


# ---------------------------------------------------------------------------
# 磁力场势能
# ---------------------------------------------------------------------------

@dataclass
class ModuleConnection:
    """模块间连接"""
    from_xy: tuple[float, float]    # 模块 A 中心坐标
    to_xy: tuple[float, float]      # 模块 B 中心坐标
    weight: float                   # 连接权重（由信号类型决定）


def calc_force_field_energy(
    connections: list[ModuleConnection],
    quadratic: bool = True,
) -> float:
    """
    磁力场总势能。

    将每条模块间连接建模为弹簧，势能 = weight * f(distance)。
    quadratic=True 时 f(d)=d², 否则 f(d)=d。

    返回: 归一化的 0~1 评分（1=最优，0=最差）
    """
    if not connections:
        return 1.0

    total_energy = 0.0
    max_possible = 0.0

    for conn in connections:
        d = math.hypot(
            conn.to_xy[0] - conn.from_xy[0],
            conn.to_xy[1] - conn.from_xy[1],
        )
        if quadratic:
            total_energy += conn.weight * d * d
        else:
            total_energy += conn.weight * d
        # 假设最大合理距离为 200mm (大板)
        max_d = 200.0
        if quadratic:
            max_possible += conn.weight * max_d * max_d
        else:
            max_possible += conn.weight * max_d

    if max_possible < 1e-9:
        return 1.0

    # 归一化：energy 越小越好，转换为 0~1 评分
    score = 1.0 - (total_energy / max_possible)
    return max(0.0, min(1.0, score))
