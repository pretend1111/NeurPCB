"""
routing/router.py — Router 布线验证器

模式 A: 飞线分析（秒级）— 总长度、交叉数、拥塞热力图、通道需求/容量比
磁力场评估: 基于信号类型的加权势能模型，热点检测 + 修改建议
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from geometry.core import Rect, calc_distance
from geometry.ratsnest import calc_ratsnest_crossings, calc_ratsnest_total_length
from geometry.congestion import calc_congestion_heatmap, HeatmapResult
from geometry.channel import calc_channel_capacity
from agents.board_map import BoardMap


# ---------------------------------------------------------------------------
# 磁力权重表（架构文档 7.3）
# ---------------------------------------------------------------------------

SIGNAL_WEIGHTS = {
    "high_speed_differential": 3.0,
    "clock": 2.5,
    "high_speed_bus": 2.0,
    "analog_sensitive": 2.0,
    "spi": 1.0,
    "i2c": 1.0,
    "uart": 1.0,
    "power_rail": 0.5,
    "gpio": 0.5,
    "ground": 0.0,
    "default": 1.0,
}


@dataclass
class Hotspot:
    """拥塞热点"""
    region_x: float
    region_y: float
    region_w: float
    region_h: float
    density: float
    avg_density: float
    involved_modules: list[str] = field(default_factory=list)
    suggestion: str = ""


@dataclass
class RouterReport:
    """Router 评估报告"""
    mode: str = "A"
    # 飞线统计
    total_ratsnest_length_mm: float = 0.0
    ratsnest_crossings: int = 0
    ratsnest_count: int = 0
    # 磁力场
    force_field_score: float = 0.0      # 0~1, 越高越好
    total_energy: float = 0.0
    # 热点
    hotspots: list[Hotspot] = field(default_factory=list)
    # 通道分析
    channel_bottlenecks: list[dict] = field(default_factory=list)
    # 综合
    routability_score: float = 0.0      # 0~1
    summary: str = ""


# ---------------------------------------------------------------------------
# Router 核心
# ---------------------------------------------------------------------------

def evaluate_ratsnest_mode_a(
    board_map: BoardMap,
    signal_types: dict[str, str] | None = None,
    grid_size_mm: float = 5.0,
) -> RouterReport:
    """
    模式 A: 飞线分析（最快）。

    board_map: 当前地图
    signal_types: {net_name: signal_type} 映射（可选，影响磁力权重）
    """
    report = RouterReport(mode="A")
    if signal_types is None:
        signal_types = {}

    # 1. 构建模块间飞线
    ratsnest = []
    weighted_energies = []

    for link in board_map.links:
        ma = board_map.get_module(link.from_id)
        mb = board_map.get_module(link.to_id)
        if not ma or not mb:
            continue
        p1 = (ma.rect.cx, ma.rect.cy)
        p2 = (mb.rect.cx, mb.rect.cy)
        dist = calc_distance(p1, p2)

        # 每条 link 可能代表多条网络
        for net in link.net_names:
            ratsnest.append((p1, p2))
            sig_type = signal_types.get(net, "default")
            weight = SIGNAL_WEIGHTS.get(sig_type, SIGNAL_WEIGHTS["default"])
            weighted_energies.append(weight * dist * dist)

        # 如果没有 net_names，用权重估算条数
        if not link.net_names:
            for _ in range(max(1, link.weight)):
                ratsnest.append((p1, p2))
                weighted_energies.append(1.0 * dist * dist)

    report.ratsnest_count = len(ratsnest)
    report.total_ratsnest_length_mm = round(calc_ratsnest_total_length(ratsnest), 2)
    report.ratsnest_crossings = calc_ratsnest_crossings(ratsnest)

    # 2. 磁力场评分
    max_energy = sum(SIGNAL_WEIGHTS.get("default", 1.0) * 200 * 200 for _ in weighted_energies) if weighted_energies else 1
    total_e = sum(weighted_energies)
    report.total_energy = round(total_e, 2)
    report.force_field_score = round(max(0, 1.0 - total_e / max(max_energy, 1e-9)), 4)

    # 3. 拥塞热力图 + 热点
    if ratsnest:
        heatmap = calc_congestion_heatmap(board_map.board, ratsnest, grid_size_mm)
        for hs in heatmap.hotspots:
            # 找出涉及的模块
            involved = []
            for m in board_map.modules:
                if (hs.x <= m.rect.cx <= hs.x + hs.w and
                    hs.y <= m.rect.cy <= hs.y + hs.h):
                    involved.append(m.module_id)
            report.hotspots.append(Hotspot(
                region_x=round(hs.x, 1),
                region_y=round(hs.y, 1),
                region_w=round(hs.w, 1),
                region_h=round(hs.h, 1),
                density=round(hs.density, 1),
                avg_density=round(heatmap.avg_density, 1),
                involved_modules=involved,
            ))

    # 4. 通道瓶颈分析
    for i in range(len(board_map.modules)):
        for j in range(i + 1, len(board_map.modules)):
            mi, mj = board_map.modules[i], board_map.modules[j]
            gap = board_map.module_distance(mi.module_id, mj.module_id)
            # 需要多少条线？
            needed = 0
            for link in board_map.links:
                if (link.from_id in (mi.module_id, mj.module_id) and
                    link.to_id in (mi.module_id, mj.module_id)):
                    needed += link.weight
            if needed > 0 and gap < 20:
                capacity = calc_channel_capacity(gap, board_map.copper_layers)
                if capacity < needed:
                    report.channel_bottlenecks.append({
                        "modules": [mi.module_id, mj.module_id],
                        "gap_mm": round(gap, 1),
                        "needed": needed,
                        "capacity": capacity,
                    })

    # 5. 综合评分
    overlap_penalty = 0.2 * len(board_map.check_overlaps())
    oob_penalty = 0.1 * len(board_map.check_board_fit())
    bottleneck_penalty = 0.05 * len(report.channel_bottlenecks)
    hotspot_penalty = 0.03 * len(report.hotspots)

    report.routability_score = round(max(0, min(1,
        report.force_field_score - overlap_penalty - oob_penalty - bottleneck_penalty - hotspot_penalty
    )), 4)

    # 6. 文本摘要
    lines = [
        f"Router Mode A Report:",
        f"  Ratsnest: {report.ratsnest_count} nets, total {report.total_ratsnest_length_mm}mm, {report.ratsnest_crossings} crossings",
        f"  Force-field score: {report.force_field_score}",
        f"  Hotspots: {len(report.hotspots)}",
        f"  Channel bottlenecks: {len(report.channel_bottlenecks)}",
    ]
    for bn in report.channel_bottlenecks:
        lines.append(f"    {bn['modules'][0]}↔{bn['modules'][1]}: gap={bn['gap_mm']}mm, need={bn['needed']}, capacity={bn['capacity']}")
    lines.append(f"  Routability score: {report.routability_score}")
    report.summary = "\n".join(lines)

    return report
