"""
test_pipeline.py — Phase 6+7 测试

Router + Critic + Architect 端到端

离线: python -m pytest test_pipeline.py -v
在线: DEEPSEEK_API_KEY=... python test_pipeline.py --live
"""
import sys
import unittest
from unittest.mock import patch

from geometry.core import Rect
from agents.board_map import BoardMap, ModuleRect, InterModuleLink, Anchor
from routing.router import evaluate_ratsnest_mode_a, RouterReport
from routing.critic import fast_check, deep_review, CriticReport, Issue


def _make_test_map() -> BoardMap:
    board = Rect(0, 0, 50, 50)
    bmap = BoardMap(board=board, copper_layers=2)
    bmap.modules = [
        ModuleRect("M01", "MCU", Rect.from_center(15, 15, 12, 10), 10),
        ModuleRect("M02", "Power", Rect.from_center(35, 15, 8, 8), 5),
        ModuleRect("M03", "Flash", Rect.from_center(15, 35, 6, 6), 3),
    ]
    bmap.links = [
        InterModuleLink("M01", "M02", 5, ["VCC", "3V3"], "moderate"),
        InterModuleLink("M01", "M03", 8, ["SPI_CLK", "SPI_MOSI", "SPI_CS"], "adjacent_tight"),
    ]
    return bmap


# ===================================================================
# Router
# ===================================================================

class TestRouter(unittest.TestCase):
    def test_mode_a_basic(self):
        bmap = _make_test_map()
        report = evaluate_ratsnest_mode_a(bmap)
        self.assertIsInstance(report, RouterReport)
        self.assertEqual(report.mode, "A")
        self.assertGreater(report.ratsnest_count, 0)
        self.assertGreaterEqual(report.routability_score, 0)
        self.assertLessEqual(report.routability_score, 1)

    def test_force_field_score(self):
        bmap = _make_test_map()
        report = evaluate_ratsnest_mode_a(bmap)
        self.assertGreater(report.force_field_score, 0)

    def test_summary(self):
        bmap = _make_test_map()
        report = evaluate_ratsnest_mode_a(bmap)
        self.assertIn("Router Mode A", report.summary)
        self.assertIn("Routability score", report.summary)

    def test_empty_map(self):
        bmap = BoardMap(board=Rect(0, 0, 50, 50))
        report = evaluate_ratsnest_mode_a(bmap)
        self.assertEqual(report.ratsnest_count, 0)


# ===================================================================
# Critic
# ===================================================================

class TestCriticFastCheck(unittest.TestCase):
    def test_no_issues(self):
        bmap = _make_test_map()
        report = fast_check(bmap)
        # No overlaps, all fit on board
        self.assertEqual(report.critical, 0)

    def test_overlap_detected(self):
        bmap = _make_test_map()
        # Force overlap
        bmap.modules[1].rect = Rect.from_center(15, 15, 8, 8)
        report = fast_check(bmap)
        self.assertGreater(report.critical, 0)
        self.assertFalse(report.passed)
        self.assertTrue(any("overlap" in i.category for i in report.issues))

    def test_out_of_board(self):
        bmap = _make_test_map()
        bmap.modules[0].rect = Rect.from_center(-5, 25, 12, 10)
        report = fast_check(bmap)
        self.assertGreater(report.critical, 0)
        self.assertTrue(any("board_overflow" in i.category for i in report.issues))


class TestCriticDeepReview(unittest.TestCase):
    def test_includes_fast_check(self):
        bmap = _make_test_map()
        report = deep_review(bmap)
        # Deep review includes fast check
        self.assertIsInstance(report, CriticReport)

    def test_summary(self):
        bmap = _make_test_map()
        report = deep_review(bmap)
        text = report.summary()
        self.assertIn("Critic Report", text)


# ===================================================================
# Architect (mock LLM)
# ===================================================================

class TestArchitectOffline(unittest.TestCase):
    @patch("agents.analyzer.AnalyzerAgent.run_json")
    @patch("agents.module_placer.ModulePlacerAgent.run_tools")
    @patch("agents.global_placer.GlobalPlacerAgent.run_tools")
    def test_pipeline_structure(self, mock_gp_tools, mock_mp_tools, mock_analyzer_json):
        """验证 pipeline 结构正确（mock 所有 LLM 调用）"""
        from agents.architect import Architect
        from agents.llm_client import ToolCallResult

        # Mock Analyzer
        mock_analyzer_json.return_value = {
            "board_type": "digital",
            "modules": [
                {"module_id": "M01", "module_name": "MCU", "module_type": "mcu",
                 "core_component": "U1", "components": ["U1", "C1"],
                 "layout_template_hint": "", "notes": ""},
                {"module_id": "M02", "module_name": "Power", "module_type": "power",
                 "core_component": "U2", "components": ["U2", "C2"],
                 "layout_template_hint": "ldo_layout", "notes": ""},
            ],
            "component_roles": [
                {"ref": "U1", "role": "core_ic", "priority": "critical"},
                {"ref": "C1", "role": "decoupling_cap", "priority": "normal"},
                {"ref": "U2", "role": "core_ic", "priority": "critical"},
                {"ref": "C2", "role": "output_cap", "priority": "normal"},
            ],
            "connections": [
                {"from_module": "M01", "to_module": "M02",
                 "net_names": ["VCC"], "total_weight": 2,
                 "placement_constraint": "moderate"},
            ],
        }

        # Mock Module Placer (returns without actually calling LLM)
        mock_mp_tools.return_value = ToolCallResult(final_message="done")

        # Mock Global Placer
        mock_gp_tools.return_value = ToolCallResult(final_message="done")

        components = [
            {"ref": "U1", "value": "ESP32"},
            {"ref": "C1", "value": "100nF"},
            {"ref": "U2", "value": "AMS1117"},
            {"ref": "C2", "value": "10uF"},
        ]
        nets = [
            {"name": "VCC", "nodes": ["U1.1", "C1.1", "U2.3"]},
            {"name": "GND", "nodes": ["U1.2", "C1.2", "U2.1", "C2.2"]},
            {"name": "3V3", "nodes": ["U2.3", "C2.1"]},
        ]

        architect = Architect()
        result = architect.run_pipeline(components, nets, Rect(0, 0, 30, 30))

        self.assertIsNotNone(result.enriched_netlist)
        self.assertEqual(result.enriched_netlist.total_modules, 2)
        self.assertIsNotNone(result.board_map)
        self.assertIsNotNone(result.router_report)
        self.assertIsNotNone(result.critic_report)
        self.assertIn("NeurPCB", result.summary)


# ===================================================================
# Live 端到端测试
# ===================================================================

def run_live_test():
    """用真实 KiCad + DeepSeek 跑完整 pipeline"""
    import logging
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    print("=" * 60)
    print("  NeurPCB 端到端 Pipeline 测试")
    print("=" * 60)

    # 从 KiCad 读取
    from bridge.kicad_bridge import KiCadBridge
    bridge = KiCadBridge()
    bridge.connect()
    print(f"Board: {bridge.board_name}")

    comps_raw = bridge.get_footprints()
    nets_raw = bridge.get_nets()

    try:
        outline = bridge.get_board_outline()
        board_rect = Rect(outline.min_x_mm, outline.min_y_mm,
                          outline.width_mm, outline.height_mm)
    except RuntimeError:
        board_rect = Rect(0, 0, 50, 80)

    copper = bridge.get_copper_layer_count()
    locked_refs = bridge.get_locked_footprints()
    bridge.disconnect()

    # 过滤非电气器件
    components = []
    for c in comps_raw:
        if c.ref.startswith("kibuzzard") or c.value in ("LOGO", "G***") or c.ref == "REF**":
            continue
        components.append({"ref": c.ref, "value": c.value, "footprint": c.footprint})

    nets = [{"name": n.name, "nodes": n.nodes} for n in nets_raw]

    locked = [{"ref": r, "x_mm": 0, "y_mm": 0} for r in locked_refs]

    print(f"Components: {len(components)}, Nets: {len(nets)}, Board: {board_rect.w:.0f}x{board_rect.h:.0f}mm")

    # 运行 pipeline
    from agents.architect import Architect
    architect = Architect()
    result = architect.run_pipeline(
        components, nets, board_rect,
        copper_layers=copper,
        locked_components=locked,
    )

    print("\n" + result.summary)
    print("\n" + "=" * 60)
    print("  DONE")
    print("=" * 60)


if __name__ == "__main__":
    if "--live" in sys.argv:
        run_live_test()
    else:
        unittest.main(argv=["test_pipeline"], exit=True)
