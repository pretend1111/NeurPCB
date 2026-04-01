"""
skills/base.py — Skill 公共数据结构

所有 Skill 的输出统一为 SkillResult：
- 每个器件的目标坐标和角度
- 模块外接矩形
- 接口焊盘所在边
"""
from __future__ import annotations

from dataclasses import dataclass, field
from geometry.core import Rect


@dataclass
class Placement:
    """单个器件的放置结果"""
    ref: str
    x_mm: float
    y_mm: float
    angle_deg: float = 0.0


@dataclass
class SkillResult:
    """Skill 执行结果"""
    placements: list[Placement]
    bbox: Rect                              # 模块外接矩形
    description: str = ""                   # 人类可读的布局描述


@dataclass
class ComponentInput:
    """传入 Skill 的器件信息（从 bridge 读取后转换）"""
    ref: str
    value: str
    footprint: str      # 封装名
    width_mm: float     # 封装宽度（courtyard）
    height_mm: float    # 封装高度
    pin_count: int = 2


@dataclass
class PinPair:
    """两个需要连接的引脚对（用于力导向算法）"""
    ref_a: str
    ref_b: str
    weight: float = 1.0
