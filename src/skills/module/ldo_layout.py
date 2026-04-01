"""
skill_ldo_layout — 线性稳压器标准布局

信号流方向线性排列：输入电容 → IC → 输出电容
反馈电阻紧贴输出电容（Kelvin 连接）。
"""
from __future__ import annotations

from skills.base import ComponentInput, Placement, SkillResult
from geometry.core import Rect, calc_bbox


def skill_ldo_layout(
    core_ic: ComponentInput,
    input_caps: list[ComponentInput],
    output_caps: list[ComponentInput],
    feedback_resistors: list[ComponentInput] | None = None,
    origin: tuple[float, float] = (0.0, 0.0),
    signal_flow: str = "left_to_right",
    spacing_mm: float = 1.0,
) -> SkillResult:
    """
    LDO 标准布局。

    signal_flow: "left_to_right" | "right_to_left" | "top_to_bottom" | "bottom_to_top"
    spacing_mm: 器件之间的间距
    """
    ox, oy = origin
    placements: list[Placement] = []

    horizontal = signal_flow in ("left_to_right", "right_to_left")
    reverse = signal_flow in ("right_to_left", "bottom_to_top")

    # 沿主轴方向排列的器件组：[input_caps, IC, output_caps, feedback]
    groups: list[list[tuple[ComponentInput, float]]] = []

    # 被动元件沿主轴方向的角度
    passive_angle = 0.0 if horizontal else 90.0

    # 输入电容组（竖直堆叠）
    for cap in input_caps:
        groups.append([(cap, passive_angle)])

    # IC
    groups.append([(core_ic, 0.0)])

    # 输出电容组
    for cap in output_caps:
        groups.append([(cap, passive_angle)])

    # 反馈电阻（放在输出电容旁边，沿副轴偏移）
    # 不加入主轴序列，单独处理

    # 计算沿主轴的总宽度，分配坐标
    cursor = 0.0  # 沿主轴的当前位置
    group_positions: list[float] = []

    for group in groups:
        comp, _ = group[0]
        size = comp.width_mm if horizontal else comp.height_mm
        group_positions.append(cursor + size / 2)
        cursor += size + spacing_mm

    if reverse:
        total_length = cursor - spacing_mm
        group_positions = [total_length - p for p in group_positions]

    # 生成 placements
    for i, group in enumerate(groups):
        comp, angle = group[0]
        pos_main = group_positions[i]
        if horizontal:
            placements.append(Placement(comp.ref, round(ox + pos_main, 3), round(oy, 3), angle))
        else:
            placements.append(Placement(comp.ref, round(ox, 3), round(oy + pos_main, 3), angle))

    # 反馈电阻：放在最后一个输出电容下方（副轴偏移）
    if feedback_resistors:
        last_out_idx = len(input_caps) + 1 + len(output_caps) - 1
        last_out_pos = group_positions[last_out_idx] if last_out_idx < len(group_positions) else group_positions[-1]
        fb_offset = core_ic.height_mm / 2 + spacing_mm + feedback_resistors[0].height_mm / 2

        for j, fb in enumerate(feedback_resistors):
            offset_main = j * (fb.width_mm + spacing_mm * 0.5)
            if horizontal:
                placements.append(Placement(
                    fb.ref,
                    round(ox + last_out_pos + offset_main, 3),
                    round(oy + fb_offset, 3),
                    passive_angle,
                ))
            else:
                placements.append(Placement(
                    fb.ref,
                    round(ox + fb_offset, 3),
                    round(oy + last_out_pos + offset_main, 3),
                    passive_angle,
                ))

    all_pts = [(p.x_mm, p.y_mm) for p in placements]
    bbox = calc_bbox(all_pts, margin=spacing_mm)

    return SkillResult(
        placements=placements,
        bbox=bbox,
        description=f"LDO layout: {signal_flow}, {len(input_caps)} in + {len(output_caps)} out caps",
    )
