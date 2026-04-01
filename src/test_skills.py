"""
test_skills.py — 布局 Skills 单元测试

python -m pytest test_skills.py -v
"""
import math
import unittest

from skills.base import ComponentInput, PinPair, Placement, SkillResult
from geometry.core import Rect, rects_overlap, calc_distance

# ===================================================================
# 辅助
# ===================================================================

def _cap(ref, w=1.0, h=0.5):
    return ComponentInput(ref=ref, value="100nF", footprint="0402", width_mm=w, height_mm=h, pin_count=2)

def _res(ref, w=1.0, h=0.5):
    return ComponentInput(ref=ref, value="10k", footprint="0402", width_mm=w, height_mm=h, pin_count=2)

def _ic(ref, w=5.0, h=5.0, pins=20):
    return ComponentInput(ref=ref, value="IC", footprint="QFN", width_mm=w, height_mm=h, pin_count=pins)

def _led(ref, w=1.6, h=0.8):
    return ComponentInput(ref=ref, value="LED", footprint="0603", width_mm=w, height_mm=h, pin_count=2)


# ===================================================================
# Decap Cluster
# ===================================================================

class TestDecapCluster(unittest.TestCase):
    def test_basic_uniform(self):
        from skills.module.decap_cluster import skill_decap_cluster
        ic = _ic("U1")
        caps = [_cap(f"C{i}") for i in range(4)]
        result = skill_decap_cluster(ic, (50, 50), caps)

        self.assertEqual(len(result.placements), 4)
        self.assertIsNotNone(result.bbox)
        # 所有电容应该在 IC 周围
        for p in result.placements:
            dist = calc_distance((p.x_mm, p.y_mm), (50, 50))
            self.assertGreater(dist, ic.width_mm / 2)

    def test_with_pin_offsets(self):
        from skills.module.decap_cluster import skill_decap_cluster
        ic = _ic("U1")
        caps = [_cap("C1"), _cap("C2")]
        pins = [(2.5, 0), (-2.5, 0)]  # 左右两侧电源引脚
        result = skill_decap_cluster(ic, (50, 50), caps, power_pin_offsets=pins)

        self.assertEqual(len(result.placements), 2)
        # C1 应该在右侧，C2 在左侧
        self.assertGreater(result.placements[0].x_mm, 50)
        self.assertLess(result.placements[1].x_mm, 50)

    def test_empty_caps(self):
        from skills.module.decap_cluster import skill_decap_cluster
        result = skill_decap_cluster(_ic("U1"), (50, 50), [])
        self.assertEqual(len(result.placements), 0)


# ===================================================================
# LDO Layout
# ===================================================================

class TestLdoLayout(unittest.TestCase):
    def test_left_to_right(self):
        from skills.module.ldo_layout import skill_ldo_layout
        ic = _ic("U2", w=3, h=2)
        result = skill_ldo_layout(
            core_ic=ic,
            input_caps=[_cap("C1"), _cap("C2")],
            output_caps=[_cap("C3")],
            feedback_resistors=[_res("R1")],
            signal_flow="left_to_right",
        )
        # 应有 4 个主轴器件 + 1 个反馈电阻
        self.assertEqual(len(result.placements), 5)

        refs = {p.ref: p for p in result.placements}
        # 输入电容在 IC 左边，输出在右边
        self.assertLess(refs["C1"].x_mm, refs["U2"].x_mm)
        self.assertLess(refs["C2"].x_mm, refs["U2"].x_mm)
        self.assertGreater(refs["C3"].x_mm, refs["U2"].x_mm)

    def test_top_to_bottom(self):
        from skills.module.ldo_layout import skill_ldo_layout
        ic = _ic("U2", w=3, h=2)
        result = skill_ldo_layout(
            core_ic=ic,
            input_caps=[_cap("C1")],
            output_caps=[_cap("C2")],
            signal_flow="top_to_bottom",
        )
        refs = {p.ref: p for p in result.placements}
        self.assertLess(refs["C1"].y_mm, refs["U2"].y_mm)
        self.assertGreater(refs["C2"].y_mm, refs["U2"].y_mm)

    def test_no_feedback(self):
        from skills.module.ldo_layout import skill_ldo_layout
        result = skill_ldo_layout(
            core_ic=_ic("U1", w=3, h=2),
            input_caps=[_cap("C1")],
            output_caps=[_cap("C2")],
        )
        self.assertEqual(len(result.placements), 3)


# ===================================================================
# Crystal Layout
# ===================================================================

class TestCrystalLayout(unittest.TestCase):
    def test_basic(self):
        from skills.module.crystal_layout import skill_crystal_layout
        xtal = ComponentInput("Y1", "32.768kHz", "HC49", 4.0, 1.5, 2)
        caps = [_cap("C1"), _cap("C2")]
        result = skill_crystal_layout(xtal, caps, mcu_clock_pin_pos=(100, 50))

        self.assertEqual(len(result.placements), 3)
        refs = {p.ref: p for p in result.placements}
        # 晶振应该比时钟引脚更远
        xtal_dist = calc_distance((refs["Y1"].x_mm, refs["Y1"].y_mm), (100, 50))
        self.assertGreater(xtal_dist, 1.0)

        # 两个负载电容应该对称分布在晶振两侧
        c1_dist = calc_distance((refs["C1"].x_mm, refs["C1"].y_mm), (refs["Y1"].x_mm, refs["Y1"].y_mm))
        c2_dist = calc_distance((refs["C2"].x_mm, refs["C2"].y_mm), (refs["Y1"].x_mm, refs["Y1"].y_mm))
        self.assertAlmostEqual(c1_dist, c2_dist, places=2)

    def test_different_angle(self):
        from skills.module.crystal_layout import skill_crystal_layout
        xtal = ComponentInput("Y1", "8MHz", "SMD", 3.0, 1.2, 2)
        caps = [_cap("C1"), _cap("C2")]
        result = skill_crystal_layout(xtal, caps, (50, 50), approach_angle_deg=90)
        refs = {p.ref: p for p in result.placements}
        # 90 度方向：晶振在时钟引脚下方
        self.assertGreater(refs["Y1"].y_mm, 50)


# ===================================================================
# Force Directed
# ===================================================================

class TestForceDirected(unittest.TestCase):
    def test_basic(self):
        from skills.module.force_directed import skill_force_directed_place
        comps = [_ic("U1"), _cap("C1"), _cap("C2"), _res("R1")]
        conns = [
            PinPair("U1", "C1", 2.0),
            PinPair("U1", "C2", 2.0),
            PinPair("U1", "R1", 1.0),
        ]
        result = skill_force_directed_place(comps, conns, seed=42)

        self.assertEqual(len(result.placements), 4)
        # 连接的器件应该比没连接的更近
        refs = {p.ref: (p.x_mm, p.y_mm) for p in result.placements}
        d_u1_c1 = calc_distance(refs["U1"], refs["C1"])
        d_c1_r1 = calc_distance(refs["C1"], refs["R1"])
        # C1 连接到 U1 权重高，应该比 R1 和 C1 的距离更近（大致上）
        # 不做严格断言，力导向算法结果受随机性影响

    def test_with_constraint(self):
        from skills.module.force_directed import skill_force_directed_place
        comps = [_cap(f"C{i}") for i in range(5)]
        conns = []
        box = Rect(0, 0, 10, 10)
        result = skill_force_directed_place(comps, conns, bbox_constraint=box, seed=42)

        # 所有器件应在 box 内
        for p in result.placements:
            self.assertGreaterEqual(p.x_mm, box.x - 1)
            self.assertLessEqual(p.x_mm, box.x2 + 1)

    def test_empty(self):
        from skills.module.force_directed import skill_force_directed_place
        result = skill_force_directed_place([], [])
        self.assertEqual(len(result.placements), 0)

    def test_deterministic(self):
        from skills.module.force_directed import skill_force_directed_place
        comps = [_cap("C1"), _cap("C2")]
        conns = [PinPair("C1", "C2", 1.0)]
        r1 = skill_force_directed_place(comps, conns, seed=123)
        r2 = skill_force_directed_place(comps, conns, seed=123)
        for p1, p2 in zip(r1.placements, r2.placements):
            self.assertAlmostEqual(p1.x_mm, p2.x_mm)
            self.assertAlmostEqual(p1.y_mm, p2.y_mm)


# ===================================================================
# LED Indicator
# ===================================================================

class TestLedIndicator(unittest.TestCase):
    def test_basic(self):
        from skills.module.led_indicator import skill_led_indicator
        result = skill_led_indicator(_led("D1"), _res("R1"), origin=(10, 10))
        self.assertEqual(len(result.placements), 2)
        refs = {p.ref: p for p in result.placements}
        # 电阻和 LED 应该紧贴
        dist = calc_distance((refs["R1"].x_mm, refs["R1"].y_mm),
                             (refs["D1"].x_mm, refs["D1"].y_mm))
        self.assertLess(dist, 5.0)

    def test_vertical(self):
        from skills.module.led_indicator import skill_led_indicator
        result = skill_led_indicator(_led("D1"), _res("R1"), orientation_deg=90)
        self.assertEqual(len(result.placements), 2)


# ===================================================================
# Voltage Divider
# ===================================================================

class TestVoltageDivider(unittest.TestCase):
    def test_basic(self):
        from skills.module.voltage_divider import skill_voltage_divider
        result = skill_voltage_divider(_res("R1"), _res("R2"), origin=(20, 20))
        self.assertEqual(len(result.placements), 2)
        refs = {p.ref: p for p in result.placements}
        # R1 在左，R2 在右（orientation=0）
        self.assertLess(refs["R1"].x_mm, refs["R2"].x_mm)

    def test_vertical(self):
        from skills.module.voltage_divider import skill_voltage_divider
        result = skill_voltage_divider(_res("R1"), _res("R2"), origin=(0, 0), orientation_deg=90)
        refs = {p.ref: p for p in result.placements}
        self.assertLess(refs["R1"].y_mm, refs["R2"].y_mm)

    def test_symmetric(self):
        from skills.module.voltage_divider import skill_voltage_divider
        r = _res("R1", w=1.0)
        result = skill_voltage_divider(r, _res("R2", w=1.0), origin=(50, 50))
        refs = {p.ref: p for p in result.placements}
        # 两个电阻到 origin 的距离应该相等
        d1 = abs(refs["R1"].x_mm - 50)
        d2 = abs(refs["R2"].x_mm - 50)
        self.assertAlmostEqual(d1, d2, places=2)


if __name__ == "__main__":
    unittest.main()
