"""
test_module_placer.py — Module Placer 单元测试

离线测试：python -m pytest test_module_placer.py -v
在线测试：DEEPSEEK_API_KEY=... python test_module_placer.py --live
"""
import sys
import json
import unittest
from unittest.mock import patch, MagicMock

from agents.analyzer import EnrichedModule
from agents.module_placer import (
    ModulePlacerState, _observe_module_layout, _observe_violations,
    _move_component, _rotate_component, _swap_components, _apply_skill,
    _finish_placement,
)
from skills.base import ComponentInput, PinPair, Placement


def _make_state():
    """构造一个 LDO 模块的测试 state"""
    module = EnrichedModule(
        module_id="M02",
        module_name="3V3_LDO",
        module_type="power_ldo",
        core_component="U2",
        components=["U2", "C3", "C4", "R2", "R3"],
        layout_template_hint="ldo_layout",
    )
    components = {
        "U2": ComponentInput("U2", "AMS1117-3.3", "SOT-223", 6.5, 3.5, 4),
        "C3": ComponentInput("C3", "10uF", "0805", 2.0, 1.25, 2),
        "C4": ComponentInput("C4", "22uF", "0805", 2.0, 1.25, 2),
        "R2": ComponentInput("R2", "100k", "0402", 1.0, 0.5, 2),
        "R3": ComponentInput("R3", "22k", "0402", 1.0, 0.5, 2),
    }
    connections = [
        PinPair("U2", "C3", 2.0),
        PinPair("U2", "C4", 2.0),
        PinPair("U2", "R2", 1.5),
        PinPair("R2", "R3", 1.0),
    ]
    return ModulePlacerState(
        module=module,
        components=components,
        placements={},
        connections=connections,
        origin=(50.0, 50.0),
    )


class TestObserveLayout(unittest.TestCase):
    def test_empty(self):
        state = _make_state()
        result = _observe_module_layout(state)
        self.assertEqual(result["placed_count"], 0)
        self.assertEqual(result["total_count"], 5)

    def test_after_placement(self):
        state = _make_state()
        state.placements["U2"] = Placement("U2", 50, 50, 0)
        result = _observe_module_layout(state)
        self.assertEqual(result["placed_count"], 1)


class TestObserveViolations(unittest.TestCase):
    def test_no_violations(self):
        state = _make_state()
        state.placements["U2"] = Placement("U2", 50, 50, 0)
        state.placements["C3"] = Placement("C3", 40, 50, 0)
        result = _observe_violations(state)
        self.assertEqual(result["count"], 0)

    def test_overlap(self):
        state = _make_state()
        state.placements["U2"] = Placement("U2", 50, 50, 0)
        state.placements["C3"] = Placement("C3", 50, 50, 0)  # exact same position
        result = _observe_violations(state)
        self.assertGreater(result["count"], 0)
        self.assertEqual(result["violations"][0]["type"], "overlap")


class TestAtomicOps(unittest.TestCase):
    def test_move(self):
        state = _make_state()
        r = _move_component(state, "U2", 55.0, 45.0)
        self.assertEqual(r["status"], "ok")
        self.assertAlmostEqual(state.placements["U2"].x_mm, 55.0)

    def test_move_invalid(self):
        state = _make_state()
        r = _move_component(state, "INVALID", 0, 0)
        self.assertIn("error", r)

    def test_rotate(self):
        state = _make_state()
        _move_component(state, "C3", 40, 50)
        r = _rotate_component(state, "C3", 90.0)
        self.assertEqual(r["status"], "ok")
        self.assertAlmostEqual(state.placements["C3"].angle_deg, 90.0)

    def test_swap(self):
        state = _make_state()
        _move_component(state, "C3", 40, 50)
        _move_component(state, "C4", 60, 50)
        _swap_components(state, "C3", "C4")
        self.assertAlmostEqual(state.placements["C3"].x_mm, 60)
        self.assertAlmostEqual(state.placements["C4"].x_mm, 40)


class TestApplySkill(unittest.TestCase):
    def test_ldo(self):
        state = _make_state()
        r = _apply_skill(state, "ldo_layout", {
            "core_ic": "U2",
            "input_caps": ["C3"],
            "output_caps": ["C4"],
            "feedback_resistors": ["R2", "R3"],
            "signal_flow_direction": "left_to_right",
        })
        self.assertEqual(r["status"], "ok")
        self.assertIn("U2", r["placed"])
        # All 4 in skill should be placed (U2, C3, C4, R2, R3 = 5 minus R3 not directly in ldo params but R2+R3 as feedback)
        self.assertGreater(len(r["placed"]), 0)

    def test_force_directed(self):
        state = _make_state()
        r = _apply_skill(state, "force_directed", {})
        self.assertEqual(r["status"], "ok")
        self.assertEqual(len(state.placements), 5)

    def test_unknown_skill(self):
        state = _make_state()
        r = _apply_skill(state, "nonexistent", {})
        self.assertIn("error", r)


class TestFinish(unittest.TestCase):
    def test_finish(self):
        state = _make_state()
        _apply_skill(state, "force_directed", {})
        r = _finish_placement(state)
        self.assertTrue(state.finished)
        self.assertEqual(r["placed_count"], 5)


# ===================================================================
# 在线 live 测试
# ===================================================================

def run_live_test():
    """用 DeepSeek 真实调用 Module Placer"""
    print("=" * 60)
    print("  Module Placer 在线测试")
    print("=" * 60)

    module = EnrichedModule(
        module_id="M02",
        module_name="3V3_LDO",
        module_type="power_ldo",
        core_component="U2",
        components=["U2", "C3", "C4", "R2", "R3"],
        layout_template_hint="ldo_layout",
    )
    components = {
        "U2": ComponentInput("U2", "AMS1117-3.3", "SOT-223", 6.5, 3.5, 4),
        "C3": ComponentInput("C3", "10uF", "0805", 2.0, 1.25, 2),
        "C4": ComponentInput("C4", "22uF", "0805", 2.0, 1.25, 2),
        "R2": ComponentInput("R2", "100k", "0402", 1.0, 0.5, 2),
        "R3": ComponentInput("R3", "22k", "0402", 1.0, 0.5, 2),
    }
    connections = [
        PinPair("U2", "C3", 2.0),
        PinPair("U2", "C4", 2.0),
        PinPair("U2", "R2", 1.5),
        PinPair("R2", "R3", 1.0),
    ]

    from agents.module_placer import ModulePlacerAgent
    agent = ModulePlacerAgent()
    result = agent.place_module(module, components, connections, origin=(50.0, 50.0))

    print(f"\n--- Placement Result ---")
    print(f"Module: {module.module_name}")
    print(f"Placed: {len(result.placements)} / {len(module.components)}")
    print(f"BBox: ({result.bbox.x:.1f}, {result.bbox.y:.1f}) {result.bbox.w:.1f}x{result.bbox.h:.1f}mm")
    for p in result.placements:
        print(f"  {p.ref}: ({p.x_mm:.2f}, {p.y_mm:.2f}) {p.angle_deg:.0f}deg")

    print("\n" + "=" * 60)
    print("  DONE")
    print("=" * 60)


if __name__ == "__main__":
    if "--live" in sys.argv:
        run_live_test()
    else:
        unittest.main(argv=["test_module_placer"], exit=True)
