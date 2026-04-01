"""
skills — 确定性布局算法

纯几何计算，不走 LLM，不碰 KiCad API。
输入器件信息 + 约束，输出放置坐标。
"""
from skills.base import Placement, SkillResult
