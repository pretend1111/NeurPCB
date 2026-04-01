"""
skill_compact_module — 模块紧凑化

保持器件间的相对位置关系，收紧间距到最小合法值。
将整个模块缩放到尽可能小的 bbox。
"""
from __future__ import annotations

import math
from skills.base import ComponentInput, Placement, SkillResult
from geometry.core import Rect, calc_bbox


def skill_compact_module(
    placements: list[Placement],
    components: dict[str, ComponentInput],
    target_center: tuple[float, float] | None = None,
    min_gap_mm: float = 0.3,
    scale_factor: float | None = None,
) -> SkillResult:
    """
    紧凑化模块布局。

    placements: 当前放置列表
    components: ref -> ComponentInput（用于获取器件尺寸）
    target_center: 紧凑化后的目标中心坐标，None 则保持原中心
    min_gap_mm: 器件间最小间隙
    scale_factor: 手动指定缩放因子（None 则自动计算最大可行缩放）
    """
    if len(placements) <= 1:
        bbox = calc_bbox([(p.x_mm, p.y_mm) for p in placements], margin=1.0) if placements else Rect(0, 0, 0, 0)
        return SkillResult(placements=list(placements), bbox=bbox, description="Too few to compact")

    # 当前中心
    cx = sum(p.x_mm for p in placements) / len(placements)
    cy = sum(p.y_mm for p in placements) / len(placements)
    tx, ty = target_center if target_center else (cx, cy)

    if scale_factor is None:
        # 自动计算：从 1.0 开始逐步缩小，直到出现重叠
        best_scale = 1.0
        for s in [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]:
            test_placements = _apply_scale(placements, cx, cy, s, tx, ty)
            if not _has_overlap(test_placements, components, min_gap_mm):
                best_scale = s
                break
        scale_factor = best_scale

    result_placements = _apply_scale(placements, cx, cy, scale_factor, tx, ty)

    all_pts = [(p.x_mm, p.y_mm) for p in result_placements]
    margin = min_gap_mm + 0.5
    bbox = calc_bbox(all_pts, margin=margin)

    return SkillResult(
        placements=result_placements,
        bbox=bbox,
        description=f"Compacted {len(placements)} components, scale={scale_factor:.2f}",
    )


def _apply_scale(
    placements: list[Placement],
    cx: float, cy: float,
    scale: float,
    tx: float, ty: float,
) -> list[Placement]:
    """以 (cx,cy) 为中心缩放，然后平移到 (tx,ty)"""
    result = []
    for p in placements:
        nx = (p.x_mm - cx) * scale + tx
        ny = (p.y_mm - cy) * scale + ty
        result.append(Placement(p.ref, round(nx, 3), round(ny, 3), p.angle_deg))
    return result


def _has_overlap(
    placements: list[Placement],
    components: dict[str, ComponentInput],
    min_gap: float,
) -> bool:
    """检查是否有任何器件对重叠"""
    for i in range(len(placements)):
        for j in range(i + 1, len(placements)):
            pi, pj = placements[i], placements[j]
            ci = components.get(pi.ref)
            cj = components.get(pj.ref)
            if not ci or not cj:
                continue
            # 简单矩形碰撞
            dx = abs(pi.x_mm - pj.x_mm)
            dy = abs(pi.y_mm - pj.y_mm)
            min_dx = (ci.width_mm + cj.width_mm) / 2 + min_gap
            min_dy = (ci.height_mm + cj.height_mm) / 2 + min_gap
            if dx < min_dx and dy < min_dy:
                return True
    return False
