"""
agents/board_map.py — 地图系统

将 PCB 布局状态压缩为 ~400 token 的文本表示，供 Architect / Global Placer 使用。
地图 = 板框 + 模块矩形 + 固定锚点 + 模块间连接权重 + 指标。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from geometry.core import Rect, rects_overlap, calc_overlap_area
from geometry.congestion import calc_force_field_energy, ModuleConnection as GeoModuleConn


@dataclass
class ModuleRect:
    """地图上的模块矩形"""
    module_id: str
    name: str
    rect: Rect              # 位置 + 尺寸
    component_count: int
    anchored_to: str = ""   # 锚定到的固定器件 ref（如 "J1"）
    status: str = "placed"  # placed / unplaced


@dataclass
class Anchor:
    """固定锚点（用户锁定的器件）"""
    ref: str
    x_mm: float
    y_mm: float
    description: str = ""


@dataclass
class InterModuleLink:
    """模块间连接"""
    from_id: str
    to_id: str
    weight: int
    net_names: list[str] = field(default_factory=list)
    constraint: str = ""    # adjacent_tight / moderate / flexible


@dataclass
class BoardMap:
    """
    板面地图 — Architect / Global Placer 的世界视图。

    所有信息压缩在 ~400 token 内。
    """
    board: Rect                         # 板框
    copper_layers: int = 2
    modules: list[ModuleRect] = field(default_factory=list)
    anchors: list[Anchor] = field(default_factory=list)
    links: list[InterModuleLink] = field(default_factory=list)

    # --- 模块查询 ---

    def get_module(self, module_id: str) -> ModuleRect | None:
        for m in self.modules:
            if m.module_id == module_id:
                return m
        return None

    # --- 模块操作 ---

    def move_module(self, module_id: str, cx: float, cy: float) -> bool:
        """移动模块中心到 (cx, cy)"""
        m = self.get_module(module_id)
        if not m:
            return False
        m.rect = Rect.from_center(cx, cy, m.rect.w, m.rect.h)
        return True

    def move_module_relative(self, module_id: str, dx: float, dy: float) -> bool:
        m = self.get_module(module_id)
        if not m:
            return False
        m.rect = Rect(m.rect.x + dx, m.rect.y + dy, m.rect.w, m.rect.h)
        return True

    def swap_modules(self, id_a: str, id_b: str) -> bool:
        a, b = self.get_module(id_a), self.get_module(id_b)
        if not a or not b:
            return False
        ac, bc = (a.rect.cx, a.rect.cy), (b.rect.cx, b.rect.cy)
        a.rect = Rect.from_center(bc[0], bc[1], a.rect.w, a.rect.h)
        b.rect = Rect.from_center(ac[0], ac[1], b.rect.w, b.rect.h)
        return True

    # --- 检测 ---

    def check_overlaps(self) -> list[tuple[str, str, float]]:
        """返回所有重叠的模块对 [(id_a, id_b, overlap_mm2), ...]"""
        overlaps = []
        for i in range(len(self.modules)):
            for j in range(i + 1, len(self.modules)):
                a, b = self.modules[i], self.modules[j]
                area = calc_overlap_area(a.rect, b.rect)
                if area > 0:
                    overlaps.append((a.module_id, b.module_id, round(area, 2)))
        return overlaps

    def check_board_fit(self) -> list[str]:
        """返回超出板框的模块 ID 列表"""
        out = []
        for m in self.modules:
            if m.rect.x < self.board.x or m.rect.y < self.board.y or \
               m.rect.x2 > self.board.x2 or m.rect.y2 > self.board.y2:
                out.append(m.module_id)
        return out

    def calc_utilization(self) -> float:
        """板面利用率"""
        if self.board.area < 1e-6:
            return 0.0
        used = sum(m.rect.area for m in self.modules)
        return round(used / self.board.area * 100, 1)

    def calc_routability_score(self) -> float:
        """基于磁力场模型的简易可布线性评分 (0~1)"""
        conns = []
        for link in self.links:
            a = self.get_module(link.from_id)
            b = self.get_module(link.to_id)
            if a and b:
                conns.append(GeoModuleConn(
                    from_xy=(a.rect.cx, a.rect.cy),
                    to_xy=(b.rect.cx, b.rect.cy),
                    weight=link.weight,
                ))
        return calc_force_field_energy(conns)

    def module_distance(self, id_a: str, id_b: str) -> float:
        """两个模块矩形之间的最短距离（中心间距 - 两个半径）"""
        a, b = self.get_module(id_a), self.get_module(id_b)
        if not a or not b:
            return float('inf')
        dx = abs(a.rect.cx - b.rect.cx) - (a.rect.w + b.rect.w) / 2
        dy = abs(a.rect.cy - b.rect.cy) - (a.rect.h + b.rect.h) / 2
        return max(0, max(dx, dy))

    # --- 文本表示 ---

    def to_text(self) -> str:
        """生成 ~400 token 的文本地图快照"""
        lines = []
        lines.append(f"Board: {self.board.w:.1f}×{self.board.h:.1f}mm, {self.copper_layers}-layer, "
                      f"origin=({self.board.x:.1f},{self.board.y:.1f}), "
                      f"end=({self.board.x2:.1f},{self.board.y2:.1f})")
        lines.append(f"  Valid X range: {self.board.x:.1f} ~ {self.board.x2:.1f}")
        lines.append(f"  Valid Y range: {self.board.y:.1f} ~ {self.board.y2:.1f}")

        if self.anchors:
            anchor_str = ", ".join(f"{a.ref}({a.description}) at ({a.x_mm:.0f},{a.y_mm:.0f})"
                                   for a in self.anchors)
            lines.append(f"Fixed anchors: {anchor_str}")

        lines.append(f"\nModules ({len(self.modules)} total):")
        for m in self.modules:
            anchor_tag = f"  [anchored: {m.anchored_to}]" if m.anchored_to else ""
            lines.append(
                f"  {m.module_id} \"{m.name}\" "
                f"center=({m.rect.cx:.1f},{m.rect.cy:.1f}) "
                f"size={m.rect.w:.0f}×{m.rect.h:.0f}mm "
                f"components={m.component_count}{anchor_tag}"
            )

        if self.links:
            sorted_links = sorted(self.links, key=lambda l: -l.weight)
            lines.append(f"\nInter-module connections (top {min(10, len(sorted_links))}):")
            for link in sorted_links[:10]:
                lines.append(f"  {link.from_id}↔{link.to_id}: weight={link.weight} [{link.constraint}]")

        overlaps = self.check_overlaps()
        out_of_board = self.check_board_fit()
        util = self.calc_utilization()
        routability = self.calc_routability_score()

        lines.append(f"\nMetrics:")
        lines.append(f"  Board utilization: {util}%")
        lines.append(f"  Module overlaps: {len(overlaps)}")
        if overlaps:
            for a, b, area in overlaps[:3]:
                lines.append(f"    {a} ↔ {b}: {area}mm²")
        lines.append(f"  Out of board: {out_of_board if out_of_board else 'none'}")
        lines.append(f"  Routability estimate: {routability:.2f}")

        return "\n".join(lines)
