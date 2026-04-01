"""
kicad_bridge.py — 统一的 KiCad IPC 桥接层

所有上层模块通过此类与 KiCad 交互，不直接 import kipy。
对外全部使用 mm 单位，内部自动转换 nm。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

try:
    from kipy import KiCad
    from kipy.board_types import BoardLayer, Pad as KiPad
    from kipy.geometry import Angle, Vector2
    from kipy.util.units import from_mm, to_mm
    HAS_KIPY = True
except ImportError:
    HAS_KIPY = False

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 数据容器（纯 Python，不依赖 kipy）
# ---------------------------------------------------------------------------

@dataclass
class ComponentInfo:
    """单个器件的完整信息"""
    ref: str
    value: str
    footprint: str
    x_mm: float
    y_mm: float
    angle_deg: float
    layer: str          # "F.Cu" / "B.Cu"
    locked: bool
    pads: list[PadInfo] = field(default_factory=list)


@dataclass
class PadInfo:
    """焊盘信息"""
    number: str
    net_name: str
    x_mm: float
    y_mm: float


@dataclass
class NetInfo:
    """网络信息"""
    name: str
    nodes: list[str]    # ["U1.1", "C1.2", ...]


@dataclass
class BoardOutline:
    """板框信息"""
    min_x_mm: float
    min_y_mm: float
    max_x_mm: float
    max_y_mm: float
    width_mm: float
    height_mm: float


@dataclass
class StackupLayer:
    """叠层单层信息"""
    name: str
    layer_type: str     # "copper" / "dielectric" / "mask" / "other"
    thickness_mm: float
    material: str
    enabled: bool


# ---------------------------------------------------------------------------
# KiCadBridge 主类
# ---------------------------------------------------------------------------

class KiCadBridge:
    """
    KiCad IPC 桥接层。

    设计原则:
    - 对外接口只使用 mm 单位和纯 Python 数据结构
    - 内部持有一个长连接，避免反复连接断开
    - 提供 checkpoint (commit) 事务管理
    - 所有写操作都支持原子批量提交

    kipy 实际 API 备忘 (v0.5/0.6, KiCad 9.x):
    - FootprintInstance 没有 .reference/.value/.pads 属性
    - 用 .reference_field.text.value 拿位号
    - 用 .value_field.text.value 拿元件值
    - 用 .definition.id 拿库链接
    - 用 board.get_pads() 拿全局焊盘，再用 ID 匹配 fp.definition.items 中的 Pad
    - KiCad() 没有 __enter__/__exit__/close，连接对象不需要显式关闭
    """

    def __init__(self):
        self._kicad = None
        self._board = None
        self._commit = None
        # footprint ref -> kipy footprint 对象的缓存，按需刷新
        self._fp_cache: dict = {}
        self._fp_cache_dirty: bool = True
        # pad id -> board pad 对象的缓存（用于网络信息查询）
        self._board_pad_cache: dict = {}
        self._board_pad_cache_dirty: bool = True

    # ===================================================================
    # 连接管理
    # ===================================================================

    def connect(self, timeout_ms: int = 5000) -> None:
        """连接到正在运行的 KiCad 实例"""
        if not HAS_KIPY:
            raise ImportError("kipy is not installed. Install with: pip install kicad-python")
        if self._kicad is not None:
            return
        self._kicad = KiCad(timeout_ms=timeout_ms)
        self._board = self._kicad.get_board()
        self._fp_cache_dirty = True
        self._board_pad_cache_dirty = True
        logger.info("Connected to KiCad: %s", self._board.name)

    def disconnect(self) -> None:
        """断开连接（置空引用，kipy 无显式 close）"""
        if self._kicad is not None:
            self._kicad = None
            self._board = None
            self._fp_cache.clear()
            self._board_pad_cache.clear()
            self._commit = None
            logger.info("Disconnected from KiCad")

    @property
    def is_connected(self) -> bool:
        return self._kicad is not None

    @property
    def board_name(self) -> str:
        self._ensure_connected()
        return self._board.name

    def _ensure_connected(self) -> None:
        if self._board is None:
            raise RuntimeError("Not connected to KiCad. Call connect() first.")

    # ===================================================================
    # 内部缓存
    # ===================================================================

    def _refresh_fp_cache(self) -> None:
        """从 KiCad 刷新 footprint 缓存。

        注意：KiCad IPC 的 get_footprints() 可能返回撤销栈中的旧副本，
        导致同一个 UUID/ref 出现多次。这里按 UUID 去重，只保留第一个出现
        的版本（KiCad 先返回当前状态，再返回历史副本）。
        """
        self._ensure_connected()
        fps = self._board.get_footprints()
        self._fp_cache = {}
        seen_ids: set = set()
        for fp in fps:
            fp_id = str(fp.id)
            if fp_id in seen_ids:
                continue
            seen_ids.add(fp_id)
            ref = self._fp_ref(fp)
            self._fp_cache[ref] = fp
        self._fp_cache_dirty = False

    def _refresh_board_pad_cache(self) -> None:
        """从 KiCad 刷新全局焊盘缓存（pad_id -> Pad 对象）"""
        self._ensure_connected()
        board_pads = self._board.get_pads()
        self._board_pad_cache = {}
        for bp in board_pads:
            pid = str(bp.id)
            self._board_pad_cache[pid] = bp
        self._board_pad_cache_dirty = False

    def _get_fp(self, ref: str):
        """获取单个 footprint 对象，必要时刷新缓存"""
        if self._fp_cache_dirty or ref not in self._fp_cache:
            self._refresh_fp_cache()
        fp = self._fp_cache.get(ref)
        if fp is None:
            raise KeyError(f"Footprint '{ref}' not found on board")
        return fp

    def invalidate_cache(self) -> None:
        """标记缓存为脏，下次读取时刷新"""
        self._fp_cache_dirty = True
        self._board_pad_cache_dirty = True

    # ===================================================================
    # kipy 属性访问辅助（兼容 mock 和真实 API）
    # ===================================================================

    @staticmethod
    def _fp_ref(fp) -> str:
        """读取 footprint 位号（兼容真实 kipy 和 mock）"""
        # 真实 kipy: fp.reference_field.text.value
        rf = getattr(fp, 'reference_field', None)
        if rf is not None:
            text = getattr(rf, 'text', None)
            if text is not None:
                val = getattr(text, 'value', None)
                if val is not None:
                    return val
        # mock 兼容: fp.reference
        return getattr(fp, 'reference', str(fp))

    @staticmethod
    def _fp_value(fp) -> str:
        """读取 footprint 元件值"""
        vf = getattr(fp, 'value_field', None)
        if vf is not None:
            text = getattr(vf, 'text', None)
            if text is not None:
                val = getattr(text, 'value', None)
                if val is not None:
                    return val
        return getattr(fp, 'value', '')

    @staticmethod
    def _fp_library(fp) -> str:
        """读取 footprint 库链接"""
        defn = getattr(fp, 'definition', None)
        if defn is not None:
            did = getattr(defn, 'id', None)
            if did is not None:
                return str(did)
        return str(getattr(fp, 'library_link', ''))

    # ===================================================================
    # 读取操作
    # ===================================================================

    def get_footprints(self) -> list[ComponentInfo]:
        """获取板上所有器件信息（含焊盘）"""
        self._refresh_fp_cache()
        if self._board_pad_cache_dirty:
            self._refresh_board_pad_cache()
        result = []
        for ref, fp in self._fp_cache.items():
            pads = self._extract_pads(fp)
            result.append(ComponentInfo(
                ref=ref,
                value=self._fp_value(fp),
                footprint=self._fp_library(fp),
                x_mm=round(to_mm(fp.position.x), 4),
                y_mm=round(to_mm(fp.position.y), 4),
                angle_deg=round(fp.orientation.degrees, 2),
                layer=self._layer_name(fp.layer),
                locked=fp.locked,
                pads=pads,
            ))
        return result

    def get_footprint_info(self, ref: str) -> ComponentInfo:
        """获取单个器件的详细信息"""
        fp = self._get_fp(ref)
        if self._board_pad_cache_dirty:
            self._refresh_board_pad_cache()
        pads = self._extract_pads(fp)
        return ComponentInfo(
            ref=ref,
            value=self._fp_value(fp),
            footprint=self._fp_library(fp),
            x_mm=round(to_mm(fp.position.x), 4),
            y_mm=round(to_mm(fp.position.y), 4),
            angle_deg=round(fp.orientation.degrees, 2),
            layer=self._layer_name(fp.layer),
            locked=fp.locked,
            pads=pads,
        )

    def get_pad_positions(self, ref: str) -> list[PadInfo]:
        """获取指定器件所有焊盘的全局坐标"""
        fp = self._get_fp(ref)
        if self._board_pad_cache_dirty:
            self._refresh_board_pad_cache()
        return self._extract_pads(fp)

    def get_nets(self) -> list[NetInfo]:
        """获取板上所有网络及其连接节点"""
        self._ensure_connected()
        self._refresh_fp_cache()
        if self._board_pad_cache_dirty:
            self._refresh_board_pad_cache()

        nets_dict: dict[str, list[str]] = {}
        for ref, fp in self._fp_cache.items():
            for pad_info in self._extract_pads(fp):
                if not pad_info.net_name:
                    continue
                nodes = nets_dict.setdefault(pad_info.net_name, [])
                node_id = f"{ref}.{pad_info.number}"
                if node_id not in nodes:
                    nodes.append(node_id)
        return [NetInfo(name=n, nodes=ns) for n, ns in nets_dict.items()]

    def get_board_outline(self) -> BoardOutline:
        """读取板框 (Edge.Cuts 层) 并返回边界框。"""
        self._ensure_connected()
        shapes = self._board.get_shapes()

        xs, ys = [], []
        edge_cuts = BoardLayer.BL_Edge_Cuts if HAS_KIPY else "Edge.Cuts"
        for shape in shapes:
            if shape.layer != edge_cuts:
                continue
            for attr in ('start', 'end', 'center', 'position'):
                pt = getattr(shape, attr, None)
                if pt is not None and hasattr(pt, 'x') and hasattr(pt, 'y'):
                    xs.append(to_mm(pt.x))
                    ys.append(to_mm(pt.y))

        if not xs:
            raise RuntimeError("No Edge.Cuts shapes found — board outline missing")

        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        return BoardOutline(
            min_x_mm=round(min_x, 4),
            min_y_mm=round(min_y, 4),
            max_x_mm=round(max_x, 4),
            max_y_mm=round(max_y, 4),
            width_mm=round(max_x - min_x, 4),
            height_mm=round(max_y - min_y, 4),
        )

    def get_stackup(self) -> list[StackupLayer]:
        """读取板层叠结构"""
        self._ensure_connected()
        stackup = self._board.get_stackup()
        result = []
        for layer in stackup.layers:
            result.append(StackupLayer(
                name=layer.user_name or str(layer.layer),
                layer_type=self._stackup_layer_type(layer),
                thickness_mm=round(to_mm(layer.thickness), 4) if layer.thickness else 0.0,
                material=layer.material_name or "",
                enabled=layer.enabled,
            ))
        return result

    def get_copper_layer_count(self) -> int:
        """获取铜层数量"""
        self._ensure_connected()
        return self._board.get_copper_layer_count()

    # ===================================================================
    # 写入操作 — 单个器件
    # ===================================================================

    def move_footprint(self, ref: str, x_mm: float, y_mm: float) -> None:
        """移动器件到绝对坐标 (mm)"""
        fp = self._get_fp(ref)
        fp.position = Vector2.from_xy_mm(x_mm, y_mm)
        result = self._board.update_items([fp])
        self._update_cache_from_result(ref, result)
        self._board_pad_cache_dirty = True
        logger.debug("Moved %s → (%.3f, %.3f)", ref, x_mm, y_mm)

    def move_footprint_relative(self, ref: str, dx_mm: float, dy_mm: float) -> None:
        """相对平移器件 (mm)"""
        fp = self._get_fp(ref)
        cur_x = to_mm(fp.position.x) + dx_mm
        cur_y = to_mm(fp.position.y) + dy_mm
        fp.position = Vector2.from_xy_mm(cur_x, cur_y)
        result = self._board.update_items([fp])
        self._update_cache_from_result(ref, result)
        self._board_pad_cache_dirty = True
        logger.debug("Moved %s by (%.3f, %.3f)", ref, dx_mm, dy_mm)

    def rotate_footprint(self, ref: str, angle_deg: float) -> None:
        """设置器件旋转角度（绝对值，度）"""
        fp = self._get_fp(ref)
        fp.orientation = Angle.from_degrees(angle_deg)
        result = self._board.update_items([fp])
        self._update_cache_from_result(ref, result)
        logger.debug("Rotated %s → %.1f°", ref, angle_deg)

    def set_footprint_locked(self, ref: str, locked: bool) -> None:
        """设置器件锁定状态"""
        fp = self._get_fp(ref)
        fp.locked = locked
        result = self._board.update_items([fp])
        self._update_cache_from_result(ref, result)
        logger.debug("Set %s locked=%s", ref, locked)

    def _update_cache_from_result(self, ref: str, result) -> None:
        """用 update_items 的返回值更新缓存，避免后续读到撤销栈旧数据"""
        if result and len(result) > 0:
            self._fp_cache[ref] = result[0]

    # ===================================================================
    # 写入操作 — 批量
    # ===================================================================

    def batch_move_footprints(
        self, positions: dict[str, tuple[float, float]]
    ) -> int:
        """
        批量移动器件到绝对坐标。

        positions: {"U1": (x_mm, y_mm), "C1": (x_mm, y_mm), ...}
        返回实际移动的器件数量。
        """
        self._ensure_connected()
        if self._fp_cache_dirty:
            self._refresh_fp_cache()

        updated = []
        for ref, (x, y) in positions.items():
            fp = self._fp_cache.get(ref)
            if fp is None:
                logger.warning("batch_move: footprint '%s' not found, skipping", ref)
                continue
            fp.position = Vector2.from_xy_mm(x, y)
            updated.append(fp)

        if updated:
            self._board.update_items(updated)
            self._board_pad_cache_dirty = True
        logger.info("Batch moved %d / %d footprints", len(updated), len(positions))
        return len(updated)

    def batch_update_footprints(
        self,
        updates: list[dict],
    ) -> int:
        """
        批量更新器件属性。

        updates: [{"ref": "U1", "x_mm": 10, "y_mm": 20, "angle_deg": 90}, ...]
        只有提供的字段会被修改。
        返回实际更新的器件数量。
        """
        self._ensure_connected()
        if self._fp_cache_dirty:
            self._refresh_fp_cache()

        modified = []
        for upd in updates:
            ref = upd.get("ref")
            if not ref:
                continue
            fp = self._fp_cache.get(ref)
            if fp is None:
                logger.warning("batch_update: footprint '%s' not found, skipping", ref)
                continue
            changed = False
            if "x_mm" in upd and "y_mm" in upd:
                fp.position = Vector2.from_xy_mm(upd["x_mm"], upd["y_mm"])
                changed = True
            if "angle_deg" in upd:
                fp.orientation = Angle.from_degrees(upd["angle_deg"])
                changed = True
            if "locked" in upd:
                fp.locked = upd["locked"]
                changed = True
            if changed:
                modified.append(fp)

        if modified:
            self._board.update_items(modified)
            self._board_pad_cache_dirty = True
        logger.info("Batch updated %d / %d footprints", len(modified), len(updates))
        return len(modified)

    # ===================================================================
    # Checkpoint / 事务管理
    # ===================================================================

    def begin_commit(self) -> None:
        """开始一个事务。后续的写操作不会立即刷新到 KiCad UI，直到 push_commit。"""
        self._ensure_connected()
        if self._commit is not None:
            raise RuntimeError("A commit is already in progress. push or drop it first.")
        self._commit = self._board.begin_commit()
        logger.debug("Commit started")

    def push_commit(self, message: str = "NeurPCB auto-layout") -> None:
        """提交事务，写入 KiCad 撤销历史"""
        if self._commit is None:
            raise RuntimeError("No commit in progress")
        self._board.push_commit(self._commit, message=message)
        self._commit = None
        self._fp_cache_dirty = True
        self._board_pad_cache_dirty = True
        logger.info("Commit pushed: %s", message)

    def drop_commit(self) -> None:
        """回滚事务，丢弃所有未提交的改动"""
        if self._commit is None:
            return
        self._board.drop_commit(self._commit)
        self._commit = None
        self._fp_cache_dirty = True
        self._board_pad_cache_dirty = True
        logger.info("Commit dropped (rollback)")

    @property
    def has_active_commit(self) -> bool:
        return self._commit is not None

    def save(self) -> None:
        """保存板文件"""
        self._ensure_connected()
        self._board.save()
        logger.info("Board saved")

    # ===================================================================
    # 封装尺寸
    # ===================================================================

    def get_real_footprint_sizes(self) -> dict[str, tuple[float, float, int]]:
        """
        从真实焊盘坐标计算每个器件的封装尺寸。

        返回 {ref: (width_mm, height_mm, pin_count)}
        尺寸 = pad 坐标范围 + margin（考虑 pad 本身占位）
        """
        self._ensure_connected()
        self._refresh_fp_cache()
        if self._board_pad_cache_dirty:
            self._refresh_board_pad_cache()

        result = {}
        PAD_MARGIN = 0.8  # pad 本身尺寸 + courtyard 余量

        for ref, fp in self._fp_cache.items():
            pads = self._extract_pads(fp)
            if not pads:
                result[ref] = (1.5, 0.8, 0)
                continue

            fp_x = to_mm(fp.position.x)
            fp_y = to_mm(fp.position.y)

            # 计算 pad 相对于 fp 中心的范围
            rel_xs = [p.x_mm - fp_x for p in pads]
            rel_ys = [p.y_mm - fp_y for p in pads]

            if rel_xs and rel_ys:
                w = max(rel_xs) - min(rel_xs) + PAD_MARGIN
                h = max(rel_ys) - min(rel_ys) + PAD_MARGIN
                w = max(w, 1.0)
                h = max(h, 0.5)
            else:
                w, h = 1.5, 0.8

            result[ref] = (round(w, 2), round(h, 2), len(pads))

        return result

    # ===================================================================
    # 高级查询
    # ===================================================================

    def get_clearance_mm(self, ref_a: str, ref_b: str) -> float:
        """计算两个器件中心之间的距离 (mm)"""
        fp_a = self._get_fp(ref_a)
        fp_b = self._get_fp(ref_b)
        dx = to_mm(fp_a.position.x) - to_mm(fp_b.position.x)
        dy = to_mm(fp_a.position.y) - to_mm(fp_b.position.y)
        return round((dx**2 + dy**2) ** 0.5, 4)

    def get_locked_footprints(self) -> list[str]:
        """获取所有已锁定器件的 ref 列表"""
        self._refresh_fp_cache()
        return [ref for ref, fp in self._fp_cache.items() if fp.locked]

    def hit_test(self, x_mm: float, y_mm: float) -> list[str]:
        """对一个坐标点进行碰撞检测，返回覆盖该点的元素信息"""
        self._ensure_connected()
        results = self._board.hit_test(Vector2.from_xy_mm(x_mm, y_mm))
        return [str(r.item) for r in results]

    # ===================================================================
    # 内部辅助
    # ===================================================================

    def _extract_pads(self, fp) -> list[PadInfo]:
        """
        提取 footprint 的焊盘信息。

        真实 kipy: fp 没有 .pads 属性。需要:
        1. 从 fp.definition.items 中筛选 Pad 对象，拿到 pad ID
        2. 用 ID 从 board.get_pads() 缓存中查到带网络信息的 board pad
        3. 合并 pad number + net name + 全局坐标

        Mock 环境: fp.pads 直接可用。
        """
        # Mock 兼容路径
        mock_pads = getattr(fp, 'pads', None)
        if mock_pads is not None and not callable(mock_pads):
            # 检测是否是真实 list（mock 的 fp 会有 .pads = [...]）
            try:
                iter(mock_pads)
                # 进一步确认：如果元素有 .net 属性，就是 mock pad
                pads_list = list(mock_pads)
                if pads_list and hasattr(pads_list[0], 'net'):
                    result = []
                    for pad in pads_list:
                        net_name = pad.net.name if pad.net else ""
                        result.append(PadInfo(
                            number=pad.number,
                            net_name=net_name,
                            x_mm=round(to_mm(pad.position.x), 4),
                            y_mm=round(to_mm(pad.position.y), 4),
                        ))
                    return result
            except TypeError:
                pass

        # 真实 kipy 路径：fp.definition.items -> Pad 对象
        defn = getattr(fp, 'definition', None)
        if defn is None:
            return []

        items = getattr(defn, 'items', None)
        if items is None:
            return []

        result = []
        for item in items:
            # 只取 Pad 对象
            if not (HAS_KIPY and isinstance(item, KiPad)):
                # fallback: duck typing
                if not (hasattr(item, 'number') and hasattr(item, 'position') and hasattr(item, 'net')):
                    continue

            pad_id = str(item.id)
            # 从 board pad 缓存中获取带网络信息的版本
            board_pad = self._board_pad_cache.get(pad_id)
            if board_pad is not None:
                net_name = board_pad.net.name if board_pad.net else ""
                result.append(PadInfo(
                    number=board_pad.number,
                    net_name=net_name,
                    x_mm=round(to_mm(board_pad.position.x), 4),
                    y_mm=round(to_mm(board_pad.position.y), 4),
                ))
            else:
                # fallback: 用 definition pad（没有网络信息）
                net_name = item.net.name if hasattr(item, 'net') and item.net else ""
                result.append(PadInfo(
                    number=item.number if hasattr(item, 'number') else "",
                    net_name=net_name,
                    x_mm=round(to_mm(item.position.x), 4),
                    y_mm=round(to_mm(item.position.y), 4),
                ))
        return result

    @staticmethod
    def _layer_name(layer) -> str:
        if HAS_KIPY:
            if layer == BoardLayer.BL_F_Cu:
                return "F.Cu"
            if layer == BoardLayer.BL_B_Cu:
                return "B.Cu"
        name = str(layer)
        if name in ("F.Cu", "B.Cu"):
            return name
        return name

    @staticmethod
    def _stackup_layer_type(layer) -> str:
        name = str(layer.layer).lower()
        if "cu" in name:
            return "copper"
        if "mask" in name:
            return "mask"
        if "paste" in name:
            return "paste"
        if "silk" in name:
            return "silkscreen"
        return "dielectric"

    # ===================================================================
    # Context Manager
    # ===================================================================

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._commit is not None:
            if exc_type is not None:
                self.drop_commit()
            else:
                logger.warning("Exiting with uncommitted changes — dropping commit")
                self.drop_commit()
        self.disconnect()
        return False
