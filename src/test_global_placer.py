"""
test_global_placer.py — Global Placer + 地图系统测试

离线: python -m pytest test_global_placer.py -v
在线: DEEPSEEK_API_KEY=... python test_global_placer.py --live
"""
import sys
import unittest

from geometry.core import Rect
from agents.board_map import BoardMap, ModuleRect, Anchor, InterModuleLink
from skills.global_skills.gp_skills import ModuleForGP, skill_gp_force_directed, skill_gp_resolve_overlap


def _make_esp32_map() -> BoardMap:
    """构造一个模拟 ESP32 板的地图"""
    board = Rect(0, 0, 23, 64)  # ~ESP32-C3 板尺寸
    bmap = BoardMap(board=board, copper_layers=2)

    bmap.modules = [
        ModuleRect("M01", "MCU_Core", Rect.from_center(11, 20, 15, 12), 14),
        ModuleRect("M02", "USB_Interface", Rect.from_center(11, 55, 10, 8), 8, anchored_to="J1"),
        ModuleRect("M03", "I2C_Sensors", Rect.from_center(11, 35, 10, 8), 13),
        ModuleRect("M04", "Power_Mgmt", Rect.from_center(11, 45, 12, 10), 17),
        ModuleRect("M05", "Board_Ctrl", Rect.from_center(11, 10, 8, 6), 1),
    ]
    bmap.anchors = [Anchor("J1", 11, 58, "USB-C")]
    bmap.links = [
        InterModuleLink("M01", "M05", 12, constraint="adjacent_tight"),
        InterModuleLink("M01", "M03", 4, constraint="adjacent_tight"),
        InterModuleLink("M01", "M02", 4, constraint="adjacent_tight"),
        InterModuleLink("M04", "M01", 1, constraint="moderate"),
        InterModuleLink("M04", "M03", 1, constraint="moderate"),
        InterModuleLink("M02", "M04", 1, constraint="moderate"),
    ]
    return bmap


# ===================================================================
# BoardMap
# ===================================================================

class TestBoardMap(unittest.TestCase):
    def test_to_text(self):
        bmap = _make_esp32_map()
        text = bmap.to_text()
        self.assertIn("Board:", text)
        self.assertIn("MCU_Core", text)
        self.assertIn("Routability", text)
        # Should be < 600 tokens (~1500 chars)
        self.assertLess(len(text), 2000)

    def test_move_module(self):
        bmap = _make_esp32_map()
        self.assertTrue(bmap.move_module("M01", 15, 25))
        m = bmap.get_module("M01")
        self.assertAlmostEqual(m.rect.cx, 15)
        self.assertAlmostEqual(m.rect.cy, 25)

    def test_move_module_not_found(self):
        bmap = _make_esp32_map()
        self.assertFalse(bmap.move_module("INVALID", 0, 0))

    def test_swap(self):
        bmap = _make_esp32_map()
        m1_before = bmap.get_module("M01").rect.cx
        m03_before = bmap.get_module("M03").rect.cx
        bmap.swap_modules("M01", "M03")
        self.assertAlmostEqual(bmap.get_module("M01").rect.cx, m03_before)
        self.assertAlmostEqual(bmap.get_module("M03").rect.cx, m1_before)

    def test_check_overlaps(self):
        bmap = _make_esp32_map()
        # Initial setup may have overlaps since modules are placed naively
        overlaps = bmap.check_overlaps()
        # Just verify it returns a list
        self.assertIsInstance(overlaps, list)

    def test_check_board_fit(self):
        bmap = _make_esp32_map()
        oob = bmap.check_board_fit()
        self.assertIsInstance(oob, list)

    def test_utilization(self):
        bmap = _make_esp32_map()
        util = bmap.calc_utilization()
        self.assertGreater(util, 0)

    def test_routability(self):
        bmap = _make_esp32_map()
        score = bmap.calc_routability_score()
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 1)

    def test_module_distance(self):
        bmap = _make_esp32_map()
        d = bmap.module_distance("M01", "M02")
        self.assertGreaterEqual(d, 0)


# ===================================================================
# GP Skills
# ===================================================================

class TestGPSkills(unittest.TestCase):
    def test_force_directed(self):
        board = Rect(0, 0, 50, 50)
        modules = [
            ModuleForGP("M1", 10, 8, {"M2": 5}),
            ModuleForGP("M2", 8, 6, {"M1": 5, "M3": 2}),
            ModuleForGP("M3", 6, 6, {"M2": 2}),
        ]
        result = skill_gp_force_directed(modules, board)
        self.assertEqual(len(result), 3)
        # All within board
        for p in result:
            self.assertGreaterEqual(p.cx, board.x)
            self.assertLessEqual(p.cx, board.x2)

    def test_force_directed_with_anchor(self):
        board = Rect(0, 0, 50, 50)
        modules = [
            ModuleForGP("M1", 10, 8, {}, anchored_pos=(5, 25)),
            ModuleForGP("M2", 8, 6, {"M1": 5}),
        ]
        result = skill_gp_force_directed(modules, board)
        # Anchored module should stay at its position
        m1 = next(p for p in result if p.module_id == "M1")
        self.assertAlmostEqual(m1.cx, 5, places=0)
        self.assertAlmostEqual(m1.cy, 25, places=0)

    def test_resolve_overlap(self):
        board = Rect(0, 0, 50, 50)
        modules = [
            ("M1", Rect.from_center(25, 25, 10, 10)),
            ("M2", Rect.from_center(27, 25, 10, 10)),  # overlapping with M1
        ]
        result = skill_gp_resolve_overlap(modules, board)
        self.assertEqual(len(result), 2)
        # After resolution, they shouldn't overlap
        from geometry.core import calc_overlap_area
        r1 = Rect.from_center(result[0].cx, result[0].cy, 10, 10)
        r2 = Rect.from_center(result[1].cx, result[1].cy, 10, 10)
        self.assertAlmostEqual(calc_overlap_area(r1, r2), 0, places=0)


# ===================================================================
# Global Placer 工具处理器
# ===================================================================

class TestGPToolHandlers(unittest.TestCase):
    def test_observe_map(self):
        from agents.global_placer import _gp_observe_map
        bmap = _make_esp32_map()
        result = _gp_observe_map(bmap)
        self.assertIn("map", result)
        self.assertIn("MCU_Core", result["map"])

    def test_move_and_check(self):
        from agents.global_placer import _gp_move_module, _gp_check_overlap
        bmap = _make_esp32_map()
        r = _gp_move_module(bmap, "M01", 11, 15)
        self.assertEqual(r["status"], "ok")
        overlap_r = _gp_check_overlap(bmap)
        self.assertIn("count", overlap_r)

    def test_force_directed_handler(self):
        from agents.global_placer import _gp_apply_force_directed
        bmap = _make_esp32_map()
        r = _gp_apply_force_directed(bmap)
        self.assertEqual(r["status"], "ok")
        self.assertIn("routability", r)

    def test_finish(self):
        from agents.global_placer import _gp_finish
        bmap = _make_esp32_map()
        r = _gp_finish(bmap)
        self.assertEqual(r["status"], "finished")
        self.assertIn("routability", r)


# ===================================================================
# 在线测试
# ===================================================================

def run_live_test():
    print("=" * 60)
    print("  Global Placer 在线测试")
    print("=" * 60)

    bmap = _make_esp32_map()
    print(f"\n--- Initial Map ---")
    print(bmap.to_text())

    from agents.global_placer import GlobalPlacerAgent
    agent = GlobalPlacerAgent()
    result_map = agent.place_global(bmap)

    print(f"\n--- After Global Placement ---")
    print(result_map.to_text())

    print("\n" + "=" * 60)
    print("  DONE")
    print("=" * 60)


if __name__ == "__main__":
    if "--live" in sys.argv:
        run_live_test()
    else:
        unittest.main(argv=["test_global_placer"], exit=True)
