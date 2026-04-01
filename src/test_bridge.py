"""
test_bridge.py — KiCadBridge 离线单元测试 (mock) + 在线集成测试

用法:
    # 离线测试（不需要 KiCad 也不需要 kipy）
    python test_bridge.py

    # 在线测试（需要 kicad conda 环境 + KiCad 打开 .kicad_pcb）
    conda activate kicad && python test_bridge.py --live
"""
import sys

_LIVE_MODE = "--live" in sys.argv

# ---------------------------------------------------------------------------
# Mock kipy 模块（仅离线模式）
# ---------------------------------------------------------------------------

_NM_PER_MM = 1_000_000


class MockVector2:
    def __init__(self, x=0, y=0):
        self.x = x
        self.y = y

    @classmethod
    def from_xy_mm(cls, x_mm, y_mm):
        return cls(int(x_mm * _NM_PER_MM), int(y_mm * _NM_PER_MM))


class MockAngle:
    def __init__(self, degrees=0.0):
        self.degrees = degrees

    @classmethod
    def from_degrees(cls, deg):
        return cls(deg)


class MockBoardLayer:
    BL_F_Cu = "F.Cu"
    BL_B_Cu = "B.Cu"
    BL_Edge_Cuts = "Edge.Cuts"


if not _LIVE_MODE:
    from unittest.mock import MagicMock

    def _mock_to_mm(nm):
        return nm / _NM_PER_MM

    def _mock_from_mm(mm):
        return int(mm * _NM_PER_MM)

    mock_kipy = MagicMock()
    mock_units = MagicMock()
    mock_units.to_mm = _mock_to_mm
    mock_units.from_mm = _mock_from_mm
    mock_kipy.util.units = mock_units

    mock_geometry = MagicMock()
    mock_geometry.Vector2 = MockVector2
    mock_geometry.Angle = MockAngle
    mock_kipy.geometry = mock_geometry
    mock_kipy.geometry.Vector2 = MockVector2
    mock_kipy.geometry.Angle = MockAngle

    mock_board_types = MagicMock()
    mock_board_types.BoardLayer = MockBoardLayer
    mock_board_types.BoardSegment = type("BoardSegment", (), {})
    mock_board_types.Net = MagicMock
    mock_kipy.board_types = mock_board_types
    mock_kipy.board_types.BoardLayer = MockBoardLayer
    mock_kipy.board_types.BoardSegment = mock_board_types.BoardSegment

    sys.modules['kipy'] = mock_kipy
    sys.modules['kipy.util'] = mock_kipy.util
    sys.modules['kipy.util.units'] = mock_units
    sys.modules['kipy.geometry'] = mock_geometry
    sys.modules['kipy.board_types'] = mock_board_types


# ---------------------------------------------------------------------------
# 在线集成测试（真实 kipy + KiCad）
# ---------------------------------------------------------------------------

def run_live_test():
    from bridge.kicad_bridge import KiCadBridge

    print("=" * 60)
    print("  KiCadBridge 在线集成测试")
    print("=" * 60)

    bridge = KiCadBridge()

    print("\n[1] 连接 KiCad...")
    bridge.connect()
    print(f"    OK: {bridge.board_name}")

    print("\n[2] 读取器件...")
    comps = bridge.get_footprints()
    print(f"    共 {len(comps)} 个器件")
    for c in comps[:5]:
        print(f"      {c.ref:<8} {c.value:<16} ({c.x_mm:.2f}, {c.y_mm:.2f}) "
              f"{c.angle_deg:.0f}deg locked={c.locked} pads={len(c.pads)}")
    if len(comps) > 5:
        print(f"      ... ({len(comps) - 5} more)")

    if comps:
        ref = comps[0].ref
        print(f"\n[3] 查询 {ref} 详情...")
        info = bridge.get_footprint_info(ref)
        print(f"    {info.ref} = {info.value}, pos=({info.x_mm}, {info.y_mm})")

        print(f"\n[4] 查询 {ref} 焊盘...")
        pads = bridge.get_pad_positions(ref)
        for p in pads[:5]:
            print(f"      pad {p.number}: net={p.net_name} ({p.x_mm:.2f}, {p.y_mm:.2f})")
        if len(pads) > 5:
            print(f"      ... ({len(pads)} total)")

    print("\n[5] 网表...")
    nets = bridge.get_nets()
    print(f"    共 {len(nets)} 个网络")
    for n in nets[:5]:
        print(f"      {n.name}: {len(n.nodes)} nodes")

    print("\n[6] 板框...")
    try:
        outline = bridge.get_board_outline()
        print(f"    {outline.width_mm} x {outline.height_mm} mm")
    except RuntimeError as e:
        print(f"    SKIP: {e}")

    print("\n[7] 叠层...")
    layers = bridge.get_stackup()
    copper = bridge.get_copper_layer_count()
    print(f"    {copper} copper layers, {len(layers)} total")
    for sl in layers[:6]:
        if sl.enabled:
            print(f"      {sl.name:<16} {sl.layer_type:<12} "
                  f"{sl.thickness_mm:.3f}mm  {sl.material}")

    print("\n[8] 锁定器件...")
    locked = bridge.get_locked_footprints()
    print(f"    {len(locked)} locked: {locked[:10]}")

    print("\n[9] Checkpoint 事务...")
    bridge.begin_commit()
    assert bridge.has_active_commit
    bridge.drop_commit()
    assert not bridge.has_active_commit
    print("    begin + drop OK")

    bridge.disconnect()
    print("\n" + "=" * 60)
    print("  ALL PASSED")
    print("=" * 60)


# ---------------------------------------------------------------------------
# 离线 Mock 测试
# ---------------------------------------------------------------------------

if not _LIVE_MODE:
    import unittest
    from unittest.mock import MagicMock
    from bridge.kicad_bridge import KiCadBridge, BoardOutline

    # -- Mock 工厂 --

    def _make_mock_pad(number, net_name, x_mm, y_mm):
        pad = MagicMock()
        pad.number = number
        pad.net = MagicMock()
        pad.net.name = net_name
        pad.position = MockVector2(int(x_mm * _NM_PER_MM), int(y_mm * _NM_PER_MM))
        return pad

    class _MockField:
        """模拟 kipy Field 结构: field.text.value"""
        def __init__(self, val):
            self.text = MagicMock()
            self.text.value = val

    class _MockDefinition:
        """模拟 kipy Footprint definition"""
        def __init__(self, lib_id):
            self.id = lib_id
            self.items = []  # 空列表，mock 环境用 fp.pads 走快速路径

    def _make_mock_fp(ref, value, x_mm, y_mm, angle_deg=0.0, locked=False, pads=None):
        fp = MagicMock()
        # 模拟真实 kipy 的属性结构
        fp.reference_field = _MockField(ref)
        fp.value_field = _MockField(value)
        fp.definition = _MockDefinition(f"Library:{value}")
        fp.position = MockVector2(int(x_mm * _NM_PER_MM), int(y_mm * _NM_PER_MM))
        fp.orientation = MockAngle(angle_deg)
        fp.layer = MockBoardLayer.BL_F_Cu
        fp.locked = locked
        fp.pads = pads or []
        return fp

    class MockEdgeSegment:
        def __init__(self, x1, y1, x2, y2):
            self.layer = MockBoardLayer.BL_Edge_Cuts
            self.start = MockVector2(int(x1 * _NM_PER_MM), int(y1 * _NM_PER_MM))
            self.end = MockVector2(int(x2 * _NM_PER_MM), int(y2 * _NM_PER_MM))

    def _make_bridge(footprints=None, shapes=None):
        bridge = KiCadBridge()
        board = MagicMock()
        board.name = "test_board.kicad_pcb"
        board.get_footprints.return_value = footprints or []
        board.get_shapes.return_value = shapes or []
        board.get_copper_layer_count.return_value = 4
        board.begin_commit.return_value = MagicMock()
        stackup = MagicMock()
        stackup.layers = []
        board.get_stackup.return_value = stackup
        bridge._kicad = MagicMock()
        bridge._board = board
        bridge._fp_cache_dirty = True
        return bridge

    # -- 测试用例 --

    class TestConnection(unittest.TestCase):
        def test_not_connected_raises(self):
            bridge = KiCadBridge()
            with self.assertRaises(RuntimeError):
                bridge.get_footprints()

        def test_is_connected(self):
            bridge = KiCadBridge()
            self.assertFalse(bridge.is_connected)
            bridge._kicad = MagicMock()
            self.assertTrue(bridge.is_connected)

        def test_board_name(self):
            bridge = _make_bridge()
            self.assertEqual(bridge.board_name, "test_board.kicad_pcb")

    class TestReadFootprints(unittest.TestCase):
        def test_get_footprints_basic(self):
            pad1 = _make_mock_pad("1", "VCC", 10.0, 20.0)
            fp1 = _make_mock_fp("U1", "ESP32", 50.0, 40.0, pads=[pad1])
            fp2 = _make_mock_fp("C1", "100nF", 55.0, 40.0, angle_deg=90.0)
            bridge = _make_bridge([fp1, fp2])
            comps = bridge.get_footprints()
            self.assertEqual(len(comps), 2)
            u1 = next(c for c in comps if c.ref == "U1")
            self.assertAlmostEqual(u1.x_mm, 50.0, places=2)
            self.assertAlmostEqual(u1.y_mm, 40.0, places=2)
            self.assertEqual(len(u1.pads), 1)
            self.assertEqual(u1.pads[0].net_name, "VCC")

        def test_get_footprint_info(self):
            fp = _make_mock_fp("R1", "10k", 30.0, 25.0, angle_deg=180.0, locked=True)
            bridge = _make_bridge([fp])
            info = bridge.get_footprint_info("R1")
            self.assertEqual(info.ref, "R1")
            self.assertAlmostEqual(info.angle_deg, 180.0)
            self.assertTrue(info.locked)

        def test_get_footprint_info_not_found(self):
            bridge = _make_bridge([])
            with self.assertRaises(KeyError):
                bridge.get_footprint_info("NONEXIST")

    class TestReadPads(unittest.TestCase):
        def test_get_pad_positions(self):
            p1 = _make_mock_pad("1", "NET_A", 10.0, 20.0)
            p2 = _make_mock_pad("2", "NET_B", 12.0, 20.0)
            fp = _make_mock_fp("U1", "IC", 10.0, 20.0, pads=[p1, p2])
            bridge = _make_bridge([fp])
            pads = bridge.get_pad_positions("U1")
            self.assertEqual(len(pads), 2)
            self.assertEqual(pads[0].net_name, "NET_A")
            self.assertAlmostEqual(pads[0].x_mm, 10.0, places=2)

    class TestReadNets(unittest.TestCase):
        def test_get_nets(self):
            p1 = _make_mock_pad("1", "VCC", 10.0, 20.0)
            p2 = _make_mock_pad("1", "VCC", 55.0, 40.0)
            p3 = _make_mock_pad("2", "GND", 55.5, 40.0)
            fp1 = _make_mock_fp("U1", "IC", 10.0, 20.0, pads=[p1])
            fp2 = _make_mock_fp("C1", "100nF", 55.0, 40.0, pads=[p2, p3])
            bridge = _make_bridge([fp1, fp2])
            nets = bridge.get_nets()
            vcc = next(n for n in nets if n.name == "VCC")
            self.assertIn("U1.1", vcc.nodes)
            self.assertIn("C1.1", vcc.nodes)
            gnd = next(n for n in nets if n.name == "GND")
            self.assertIn("C1.2", gnd.nodes)

    class TestBoardOutline(unittest.TestCase):
        def test_get_board_outline(self):
            shapes = [
                MockEdgeSegment(0, 0, 100, 0),
                MockEdgeSegment(100, 0, 100, 80),
                MockEdgeSegment(100, 80, 0, 80),
                MockEdgeSegment(0, 80, 0, 0),
            ]
            bridge = _make_bridge(shapes=shapes)
            outline = bridge.get_board_outline()
            self.assertAlmostEqual(outline.width_mm, 100.0, places=1)
            self.assertAlmostEqual(outline.height_mm, 80.0, places=1)

        def test_missing_outline_raises(self):
            bridge = _make_bridge(shapes=[])
            with self.assertRaises(RuntimeError):
                bridge.get_board_outline()

    class TestWriteOperations(unittest.TestCase):
        def test_move_footprint(self):
            fp = _make_mock_fp("U1", "IC", 10.0, 20.0)
            bridge = _make_bridge([fp])
            bridge.move_footprint("U1", 50.0, 40.0)
            bridge._board.update_items.assert_called()

        def test_rotate_footprint(self):
            fp = _make_mock_fp("U1", "IC", 10.0, 20.0)
            bridge = _make_bridge([fp])
            bridge.rotate_footprint("U1", 90.0)
            bridge._board.update_items.assert_called()

        def test_batch_move(self):
            fp1 = _make_mock_fp("U1", "IC", 10.0, 20.0)
            fp2 = _make_mock_fp("C1", "100nF", 15.0, 20.0)
            bridge = _make_bridge([fp1, fp2])
            count = bridge.batch_move_footprints({
                "U1": (50.0, 40.0),
                "C1": (55.0, 40.0),
                "MISSING": (0, 0),
            })
            self.assertEqual(count, 2)

        def test_batch_update(self):
            fp1 = _make_mock_fp("U1", "IC", 10.0, 20.0)
            bridge = _make_bridge([fp1])
            count = bridge.batch_update_footprints([
                {"ref": "U1", "x_mm": 50.0, "y_mm": 40.0, "angle_deg": 90.0},
            ])
            self.assertEqual(count, 1)

        def test_set_locked(self):
            fp = _make_mock_fp("U1", "IC", 10.0, 20.0)
            bridge = _make_bridge([fp])
            bridge.set_footprint_locked("U1", True)
            bridge._board.update_items.assert_called()

    class TestCheckpoint(unittest.TestCase):
        def test_commit_lifecycle(self):
            bridge = _make_bridge([])
            bridge.begin_commit()
            self.assertTrue(bridge.has_active_commit)
            bridge.push_commit("test")
            self.assertFalse(bridge.has_active_commit)

        def test_commit_drop(self):
            bridge = _make_bridge([])
            bridge.begin_commit()
            bridge.drop_commit()
            self.assertFalse(bridge.has_active_commit)

        def test_double_begin_raises(self):
            bridge = _make_bridge([])
            bridge.begin_commit()
            with self.assertRaises(RuntimeError):
                bridge.begin_commit()

        def test_push_without_begin_raises(self):
            bridge = _make_bridge([])
            with self.assertRaises(RuntimeError):
                bridge.push_commit("oops")

        def test_drop_without_begin_is_noop(self):
            bridge = _make_bridge([])
            bridge.drop_commit()

    class TestAdvancedQueries(unittest.TestCase):
        def test_clearance(self):
            fp1 = _make_mock_fp("U1", "IC", 0.0, 0.0)
            fp2 = _make_mock_fp("C1", "100nF", 3.0, 4.0)
            bridge = _make_bridge([fp1, fp2])
            dist = bridge.get_clearance_mm("U1", "C1")
            self.assertAlmostEqual(dist, 5.0, places=2)

        def test_locked_footprints(self):
            fp1 = _make_mock_fp("U1", "IC", 0.0, 0.0, locked=True)
            fp2 = _make_mock_fp("C1", "100nF", 5.0, 5.0, locked=False)
            bridge = _make_bridge([fp1, fp2])
            locked = bridge.get_locked_footprints()
            self.assertIn("U1", locked)
            self.assertNotIn("C1", locked)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if _LIVE_MODE:
        run_live_test()
    else:
        unittest.main(argv=["test_bridge"], exit=True)
