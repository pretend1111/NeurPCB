"""
bridge — KiCad IPC 桥接层

所有上层模块统一通过 KiCadBridge 与 KiCad 交互。
"""
from bridge.kicad_bridge import (
    KiCadBridge,
    BoardOutline,
    ComponentInfo,
    NetInfo,
    PadInfo,
    StackupLayer,
)

__all__ = [
    "KiCadBridge",
    "BoardOutline",
    "ComponentInfo",
    "NetInfo",
    "PadInfo",
    "StackupLayer",
]
