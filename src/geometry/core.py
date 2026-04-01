"""
geometry/core.py — 基础几何计算

距离、外接矩形、矩形重叠检测、最小位移消解重叠。
所有坐标单位: mm
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class Rect:
    """轴对齐矩形 (AABB)，用左下角 + 宽高表示"""
    x: float        # 左边界
    y: float        # 上边界 (KiCad Y 轴向下)
    w: float        # 宽
    h: float        # 高

    @property
    def x2(self) -> float:
        return self.x + self.w

    @property
    def y2(self) -> float:
        return self.y + self.h

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    @property
    def area(self) -> float:
        return self.w * self.h

    @classmethod
    def from_center(cls, cx: float, cy: float, w: float, h: float) -> Rect:
        return cls(cx - w / 2, cy - h / 2, w, h)

    @classmethod
    def from_corners(cls, x1: float, y1: float, x2: float, y2: float) -> Rect:
        return cls(min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1))


# ---------------------------------------------------------------------------
# 基础几何
# ---------------------------------------------------------------------------

def calc_distance(p1: tuple[float, float], p2: tuple[float, float]) -> float:
    """两点欧氏距离 (mm)"""
    return math.hypot(p2[0] - p1[0], p2[1] - p1[1])


def calc_bbox(points: list[tuple[float, float]], margin: float = 0.0) -> Rect:
    """
    一组坐标点的外接矩形。

    points: [(x, y), ...]
    margin: 四周外扩量 (mm)
    """
    if not points:
        return Rect(0, 0, 0, 0)
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return Rect(
        min(xs) - margin,
        min(ys) - margin,
        max(xs) - min(xs) + 2 * margin,
        max(ys) - min(ys) + 2 * margin,
    )


def point_in_rect(px: float, py: float, r: Rect) -> bool:
    """点是否在矩形内"""
    return r.x <= px <= r.x2 and r.y <= py <= r.y2


# ---------------------------------------------------------------------------
# 矩形重叠
# ---------------------------------------------------------------------------

def rects_overlap(a: Rect, b: Rect) -> bool:
    """两个矩形是否重叠（边缘相切不算重叠）"""
    return a.x < b.x2 and a.x2 > b.x and a.y < b.y2 and a.y2 > b.y


def calc_overlap(a: Rect, b: Rect) -> Rect | None:
    """
    两个矩形的重叠区域。不重叠返回 None。
    """
    ox = max(a.x, b.x)
    oy = max(a.y, b.y)
    ox2 = min(a.x2, b.x2)
    oy2 = min(a.y2, b.y2)
    if ox2 <= ox or oy2 <= oy:
        return None
    return Rect(ox, oy, ox2 - ox, oy2 - oy)


def calc_overlap_area(a: Rect, b: Rect) -> float:
    """两个矩形的重叠面积 (mm²)。不重叠返回 0。"""
    overlap = calc_overlap(a, b)
    return overlap.area if overlap else 0.0


# ---------------------------------------------------------------------------
# 最小位移消解重叠
# ---------------------------------------------------------------------------

def resolve_overlap_minimum_displacement(
    rects: list[Rect],
    board: Rect | None = None,
    gap: float = 0.5,
    max_iterations: int = 100,
) -> list[Rect]:
    """
    最小位移消解重叠。

    对输入的矩形列表迭代推开，直到所有矩形互不重叠。
    使用简单的基于重叠中心的排斥策略。

    rects: 矩形列表（会被复制，不修改原始数据）
    board: 板框限制，超出板框的矩形会被推回
    gap: 矩形间最小间隙 (mm)
    max_iterations: 最大迭代次数
    返回: 调整后的矩形列表
    """
    # 深拷贝
    result = [Rect(r.x, r.y, r.w, r.h) for r in rects]
    n = len(result)

    for _ in range(max_iterations):
        moved = False
        for i in range(n):
            for j in range(i + 1, n):
                a, b = result[i], result[j]
                # 加上 gap 检测
                a_expanded = Rect(a.x - gap / 2, a.y - gap / 2,
                                  a.w + gap, a.h + gap)
                if not rects_overlap(a_expanded, b):
                    continue
                # 计算推开方向和距离
                dx = b.cx - a.cx
                dy = b.cy - a.cy
                dist = math.hypot(dx, dy)
                if dist < 1e-6:
                    dx, dy, dist = 1.0, 0.0, 1.0

                # 计算需要推开的最小距离（沿连心线方向）
                # 选择水平或垂直方向中较小的那个推开量
                overlap_x = (a.w + b.w) / 2 + gap - abs(dx)
                overlap_y = (a.h + b.h) / 2 + gap - abs(dy)

                if overlap_x > 0 and overlap_y > 0:
                    if overlap_x < overlap_y:
                        push = overlap_x / 2
                        sign = 1.0 if dx >= 0 else -1.0
                        result[i] = Rect(a.x - push * sign, a.y, a.w, a.h)
                        result[j] = Rect(b.x + push * sign, b.y, b.w, b.h)
                    else:
                        push = overlap_y / 2
                        sign = 1.0 if dy >= 0 else -1.0
                        result[i] = Rect(a.x, a.y - push * sign, a.w, a.h)
                        result[j] = Rect(a.x, b.y + push * sign, b.w, b.h)
                    moved = True

        # 板框约束
        if board is not None:
            for i in range(n):
                r = result[i]
                nx = max(board.x, min(r.x, board.x2 - r.w))
                ny = max(board.y, min(r.y, board.y2 - r.h))
                if nx != r.x or ny != r.y:
                    result[i] = Rect(nx, ny, r.w, r.h)
                    moved = True

        if not moved:
            break

    return result
