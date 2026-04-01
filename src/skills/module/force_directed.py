"""
skill_force_directed_place — 力导向通用布局

以连接关系为弹簧力（吸引），以间距约束为斥力（排斥），
迭代求解器件位置。适用于没有现成模板的通用场景。
"""
from __future__ import annotations

import math
import random
from skills.base import ComponentInput, PinPair, Placement, SkillResult
from geometry.core import Rect, calc_bbox


def skill_force_directed_place(
    components: list[ComponentInput],
    connections: list[PinPair],
    bbox_constraint: Rect | None = None,
    origin: tuple[float, float] = (0.0, 0.0),
    attract_k: float = 0.01,
    repel_k: float = 2.0,
    min_gap_mm: float = 0.5,
    max_iterations: int = 200,
    cooling_rate: float = 0.97,
    seed: int | None = None,
) -> SkillResult:
    """
    力导向布局。

    components: 需要布局的器件列表
    connections: 器件间连接关系（弹簧力）
    bbox_constraint: 限制区域（为 None 时不限制）
    origin: 布局中心点
    attract_k: 弹簧力系数（越大吸引力越强）
    repel_k: 斥力系数（越大排斥力越强）
    min_gap_mm: 最小间隙
    max_iterations: 最大迭代次数
    cooling_rate: 模拟退火降温率
    seed: 随机种子（可复现）
    """
    if not components:
        return SkillResult([], Rect(0, 0, 0, 0), "Empty")

    rng = random.Random(seed)
    n = len(components)
    ref_to_idx = {c.ref: i for i, c in enumerate(components)}

    # 初始位置：在 origin 周围随机散布
    spread = max(3.0, math.sqrt(n) * 3.0)
    ox, oy = origin
    pos_x = [ox + rng.uniform(-spread, spread) for _ in range(n)]
    pos_y = [oy + rng.uniform(-spread, spread) for _ in range(n)]

    # 器件半径（用于斥力计算）
    radii = [max(c.width_mm, c.height_mm) / 2 + min_gap_mm for c in components]

    temperature = spread * 0.5

    for iteration in range(max_iterations):
        # 计算每个器件受到的合力
        fx = [0.0] * n
        fy = [0.0] * n

        # 斥力：所有器件对之间
        for i in range(n):
            for j in range(i + 1, n):
                dx = pos_x[j] - pos_x[i]
                dy = pos_y[j] - pos_y[i]
                dist = math.hypot(dx, dy)
                min_dist = radii[i] + radii[j]

                if dist < 1e-4:
                    dx, dy, dist = rng.uniform(0.1, 1), rng.uniform(0.1, 1), 1.0

                if dist < min_dist * 3:  # 只在近距离计算斥力
                    force = repel_k * min_dist * min_dist / (dist * dist)
                    fx[i] -= force * dx / dist
                    fy[i] -= force * dy / dist
                    fx[j] += force * dx / dist
                    fy[j] += force * dy / dist

        # 吸引力：有连接的器件对之间
        for conn in connections:
            i = ref_to_idx.get(conn.ref_a)
            j = ref_to_idx.get(conn.ref_b)
            if i is None or j is None:
                continue
            dx = pos_x[j] - pos_x[i]
            dy = pos_y[j] - pos_y[i]
            dist = math.hypot(dx, dy)
            if dist < 1e-4:
                continue

            force = attract_k * conn.weight * dist
            fx[i] += force * dx / dist
            fy[i] += force * dy / dist
            fx[j] -= force * dx / dist
            fy[j] -= force * dy / dist

        # 应用力（限制位移不超过 temperature）
        for i in range(n):
            f_mag = math.hypot(fx[i], fy[i])
            if f_mag > 1e-6:
                scale = min(temperature, f_mag) / f_mag
                pos_x[i] += fx[i] * scale
                pos_y[i] += fy[i] * scale

        # bbox 约束
        if bbox_constraint is not None:
            for i in range(n):
                r = radii[i]
                pos_x[i] = max(bbox_constraint.x + r, min(pos_x[i], bbox_constraint.x2 - r))
                pos_y[i] = max(bbox_constraint.y + r, min(pos_y[i], bbox_constraint.y2 - r))

        temperature *= cooling_rate

    # 生成结果
    placements = []
    for i, comp in enumerate(components):
        placements.append(Placement(
            comp.ref,
            round(pos_x[i], 3),
            round(pos_y[i], 3),
            0.0,
        ))

    all_pts = [(p.x_mm, p.y_mm) for p in placements]
    bbox = calc_bbox(all_pts, margin=min_gap_mm)

    return SkillResult(
        placements=placements,
        bbox=bbox,
        description=f"Force-directed: {n} components, {len(connections)} connections",
    )
