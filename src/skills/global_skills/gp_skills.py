"""
skills/global/gp_skills.py — 全局排布 Skills

模块级别的排布算法，操作对象是模块矩形而非单个器件。
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from geometry.core import Rect, rects_overlap, resolve_overlap_minimum_displacement


@dataclass
class ModuleForGP:
    """全局排布的输入：模块矩形"""
    module_id: str
    w: float
    h: float
    weight_to: dict[str, float]   # module_id -> 连接权重
    anchored_pos: tuple[float, float] | None = None  # 如果锚定到固定位置


@dataclass
class GPPlacement:
    """全局排布的输出：模块中心坐标"""
    module_id: str
    cx: float
    cy: float


def skill_gp_force_directed(
    modules: list[ModuleForGP],
    board: Rect,
    attract_k: float = 0.005,
    repel_k: float = 50.0,
    max_iterations: int = 300,
    seed: int = 42,
) -> list[GPPlacement]:
    """
    力导向全局排布。

    模块间连接权重为弹簧力（吸引），模块矩形面积为斥力（排斥），
    锚定模块固定不动。
    """
    rng = random.Random(seed)
    n = len(modules)
    if n == 0:
        return []

    id_to_idx = {m.module_id: i for i, m in enumerate(modules)}

    # 初始位置：板框中心附近随机
    bcx, bcy = board.cx, board.cy
    spread = min(board.w, board.h) * 0.3
    cx = [bcx + rng.uniform(-spread, spread) for _ in range(n)]
    cy = [bcy + rng.uniform(-spread, spread) for _ in range(n)]

    # 锚定模块初始化到锚定位置
    fixed = [False] * n
    for i, m in enumerate(modules):
        if m.anchored_pos:
            cx[i], cy[i] = m.anchored_pos
            fixed[i] = True

    temperature = spread * 0.5

    for _ in range(max_iterations):
        fx = [0.0] * n
        fy = [0.0] * n

        # 斥力
        for i in range(n):
            for j in range(i + 1, n):
                dx = cx[j] - cx[i]
                dy = cy[j] - cy[i]
                dist = math.hypot(dx, dy)
                min_dist = (modules[i].w + modules[j].w) / 2 + 1.0
                if dist < 1e-4:
                    dx, dy, dist = rng.uniform(0.1, 1), rng.uniform(0.1, 1), 1.0
                if dist < min_dist * 3:
                    force = repel_k * min_dist / (dist * dist)
                    fx[i] -= force * dx / dist
                    fy[i] -= force * dy / dist
                    fx[j] += force * dx / dist
                    fy[j] += force * dy / dist

        # 吸引力
        for i, m in enumerate(modules):
            for other_id, weight in m.weight_to.items():
                j = id_to_idx.get(other_id)
                if j is None or j == i:
                    continue
                dx = cx[j] - cx[i]
                dy = cy[j] - cy[i]
                dist = math.hypot(dx, dy)
                if dist < 1e-4:
                    continue
                force = attract_k * weight * dist
                fx[i] += force * dx / dist
                fy[i] += force * dy / dist

        # 向板框中心的微弱引力（防止散开到板外）
        for i in range(n):
            dx = bcx - cx[i]
            dy = bcy - cy[i]
            fx[i] += dx * 0.001
            fy[i] += dy * 0.001

        # 应用力
        for i in range(n):
            if fixed[i]:
                continue
            mag = math.hypot(fx[i], fy[i])
            if mag > 1e-6:
                scale = min(temperature, mag) / mag
                cx[i] += fx[i] * scale
                cy[i] += fy[i] * scale

            # 板框约束
            hw, hh = modules[i].w / 2, modules[i].h / 2
            cx[i] = max(board.x + hw, min(cx[i], board.x2 - hw))
            cy[i] = max(board.y + hh, min(cy[i], board.y2 - hh))

        temperature *= 0.98

    return [GPPlacement(modules[i].module_id, round(cx[i], 2), round(cy[i], 2))
            for i in range(n)]


def skill_gp_resolve_overlap(
    modules: list[tuple[str, Rect]],
    board: Rect,
    gap: float = 1.0,
) -> list[GPPlacement]:
    """
    最小位移消解模块重叠。

    modules: [(module_id, Rect), ...]
    board: 板框
    gap: 模块间最小间隙

    返回调整后的模块中心坐标。
    """
    rects = [r for _, r in modules]
    ids = [mid for mid, _ in modules]

    resolved = resolve_overlap_minimum_displacement(rects, board=board, gap=gap)

    return [GPPlacement(ids[i], round(resolved[i].cx, 2), round(resolved[i].cy, 2))
            for i in range(len(ids))]
