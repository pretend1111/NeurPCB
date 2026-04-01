"""
test_geometry.py — 几何计算层单元测试

python -m pytest test_geometry.py -v
"""
import math
import unittest

from geometry.core import (
    Rect, calc_distance, calc_bbox, calc_overlap, calc_overlap_area,
    rects_overlap, point_in_rect, resolve_overlap_minimum_displacement,
)
from geometry.ratsnest import (
    segments_intersect, calc_ratsnest_crossings, calc_ratsnest_total_length,
)
from geometry.congestion import (
    calc_congestion_heatmap, calc_force_field_energy, ModuleConnection,
)
from geometry.channel import calc_channel_capacity


# ===================================================================
# core.py
# ===================================================================

class TestRect(unittest.TestCase):
    def test_properties(self):
        r = Rect(10, 20, 30, 40)
        self.assertAlmostEqual(r.x2, 40)
        self.assertAlmostEqual(r.y2, 60)
        self.assertAlmostEqual(r.cx, 25)
        self.assertAlmostEqual(r.cy, 40)
        self.assertAlmostEqual(r.area, 1200)

    def test_from_center(self):
        r = Rect.from_center(50, 50, 20, 10)
        self.assertAlmostEqual(r.x, 40)
        self.assertAlmostEqual(r.y, 45)

    def test_from_corners(self):
        r = Rect.from_corners(30, 40, 10, 20)
        self.assertAlmostEqual(r.x, 10)
        self.assertAlmostEqual(r.y, 20)
        self.assertAlmostEqual(r.w, 20)
        self.assertAlmostEqual(r.h, 20)


class TestDistance(unittest.TestCase):
    def test_basic(self):
        self.assertAlmostEqual(calc_distance((0, 0), (3, 4)), 5.0)

    def test_same_point(self):
        self.assertAlmostEqual(calc_distance((5, 5), (5, 5)), 0.0)


class TestBbox(unittest.TestCase):
    def test_basic(self):
        bbox = calc_bbox([(0, 0), (10, 5), (3, 8)])
        self.assertAlmostEqual(bbox.x, 0)
        self.assertAlmostEqual(bbox.y, 0)
        self.assertAlmostEqual(bbox.w, 10)
        self.assertAlmostEqual(bbox.h, 8)

    def test_with_margin(self):
        bbox = calc_bbox([(5, 5), (15, 10)], margin=2.0)
        self.assertAlmostEqual(bbox.x, 3)
        self.assertAlmostEqual(bbox.y, 3)
        self.assertAlmostEqual(bbox.w, 14)
        self.assertAlmostEqual(bbox.h, 9)

    def test_empty(self):
        bbox = calc_bbox([])
        self.assertAlmostEqual(bbox.area, 0)

    def test_single_point(self):
        bbox = calc_bbox([(5, 5)])
        self.assertAlmostEqual(bbox.w, 0)
        self.assertAlmostEqual(bbox.h, 0)


class TestOverlap(unittest.TestCase):
    def test_overlapping(self):
        a = Rect(0, 0, 10, 10)
        b = Rect(5, 5, 10, 10)
        self.assertTrue(rects_overlap(a, b))
        ov = calc_overlap(a, b)
        self.assertIsNotNone(ov)
        self.assertAlmostEqual(ov.w, 5)
        self.assertAlmostEqual(ov.h, 5)
        self.assertAlmostEqual(calc_overlap_area(a, b), 25)

    def test_no_overlap(self):
        a = Rect(0, 0, 5, 5)
        b = Rect(10, 10, 5, 5)
        self.assertFalse(rects_overlap(a, b))
        self.assertIsNone(calc_overlap(a, b))
        self.assertAlmostEqual(calc_overlap_area(a, b), 0)

    def test_touching_edges(self):
        a = Rect(0, 0, 5, 5)
        b = Rect(5, 0, 5, 5)
        self.assertFalse(rects_overlap(a, b))

    def test_contained(self):
        a = Rect(0, 0, 20, 20)
        b = Rect(5, 5, 5, 5)
        self.assertTrue(rects_overlap(a, b))
        self.assertAlmostEqual(calc_overlap_area(a, b), 25)


class TestPointInRect(unittest.TestCase):
    def test_inside(self):
        self.assertTrue(point_in_rect(5, 5, Rect(0, 0, 10, 10)))

    def test_outside(self):
        self.assertFalse(point_in_rect(15, 5, Rect(0, 0, 10, 10)))

    def test_on_edge(self):
        self.assertTrue(point_in_rect(10, 5, Rect(0, 0, 10, 10)))


class TestResolveOverlap(unittest.TestCase):
    def test_no_overlap(self):
        rects = [Rect(0, 0, 5, 5), Rect(10, 10, 5, 5)]
        result = resolve_overlap_minimum_displacement(rects)
        # 不重叠，不应移动
        self.assertAlmostEqual(result[0].x, 0)
        self.assertAlmostEqual(result[1].x, 10)

    def test_overlapping_pair(self):
        rects = [Rect(0, 0, 10, 10), Rect(5, 0, 10, 10)]
        result = resolve_overlap_minimum_displacement(rects, gap=0)
        # 两个应该被推开到不重叠
        self.assertFalse(rects_overlap(result[0], result[1]))

    def test_board_constraint(self):
        board = Rect(0, 0, 20, 20)
        rects = [Rect(-5, 0, 10, 10)]
        result = resolve_overlap_minimum_displacement(rects, board=board)
        self.assertGreaterEqual(result[0].x, 0)


# ===================================================================
# ratsnest.py
# ===================================================================

class TestSegmentsIntersect(unittest.TestCase):
    def test_crossing(self):
        self.assertTrue(segments_intersect((0, 0), (10, 10), (0, 10), (10, 0)))

    def test_parallel(self):
        self.assertFalse(segments_intersect((0, 0), (10, 0), (0, 1), (10, 1)))

    def test_not_reaching(self):
        self.assertFalse(segments_intersect((0, 0), (5, 5), (6, 0), (10, 10)))


class TestRatsnest(unittest.TestCase):
    def test_total_length(self):
        rats = [((0, 0), (3, 4)), ((0, 0), (0, 10))]
        self.assertAlmostEqual(calc_ratsnest_total_length(rats), 15.0)

    def test_no_crossings(self):
        rats = [((0, 0), (10, 0)), ((0, 5), (10, 5))]
        self.assertEqual(calc_ratsnest_crossings(rats), 0)

    def test_one_crossing(self):
        rats = [((0, 0), (10, 10)), ((0, 10), (10, 0))]
        self.assertEqual(calc_ratsnest_crossings(rats), 1)

    def test_multiple_crossings(self):
        rats = [
            ((0, 0), (10, 10)),
            ((0, 10), (10, 0)),
            ((5, 0), (5, 10)),
        ]
        # 垂直线 (5,0)-(5,10) 与两条对角线都相交
        self.assertEqual(calc_ratsnest_crossings(rats), 3)

    def test_empty(self):
        self.assertEqual(calc_ratsnest_crossings([]), 0)


# ===================================================================
# congestion.py
# ===================================================================

class TestHeatmap(unittest.TestCase):
    def test_basic(self):
        region = Rect(0, 0, 20, 20)
        rats = [((0, 0), (20, 20)), ((0, 20), (20, 0))]
        result = calc_congestion_heatmap(region, rats, grid_size_mm=10)
        self.assertEqual(len(result.cells), 2)      # 2 rows
        self.assertEqual(len(result.cells[0]), 2)    # 2 cols
        self.assertGreater(result.max_density, 0)

    def test_empty_ratsnest(self):
        region = Rect(0, 0, 20, 20)
        result = calc_congestion_heatmap(region, [], grid_size_mm=10)
        self.assertAlmostEqual(result.max_density, 0)
        self.assertEqual(len(result.hotspots), 0)

    def test_hotspot_detection(self):
        region = Rect(0, 0, 20, 20)
        # 所有飞线集中在左上角
        rats = [((0, 0), (5, 5)) for _ in range(10)]
        result = calc_congestion_heatmap(region, rats, grid_size_mm=10)
        self.assertGreater(len(result.hotspots), 0)


class TestForceField(unittest.TestCase):
    def test_perfect_layout(self):
        # 距离为 0 -> 势能为 0 -> 评分为 1
        conns = [ModuleConnection((50, 50), (50, 50), weight=1.0)]
        self.assertAlmostEqual(calc_force_field_energy(conns), 1.0)

    def test_bad_layout(self):
        # 距离很远 -> 势能很高 -> 评分接近 0
        conns = [ModuleConnection((0, 0), (200, 200), weight=3.0)]
        score = calc_force_field_energy(conns)
        self.assertLess(score, 0.5)

    def test_empty(self):
        self.assertAlmostEqual(calc_force_field_energy([]), 1.0)

    def test_closer_is_better(self):
        # 同权重，近距离 -> 更高评分
        conns_close = [ModuleConnection((0, 0), (10, 0), weight=2.0)]
        conns_far = [ModuleConnection((0, 0), (80, 0), weight=2.0)]
        self.assertGreater(
            calc_force_field_energy(conns_close),
            calc_force_field_energy(conns_far),
        )

    def test_linear_mode(self):
        conns = [ModuleConnection((0, 0), (100, 0), weight=1.0)]
        score = calc_force_field_energy(conns, quadratic=False)
        self.assertGreater(score, 0)
        self.assertLess(score, 1.0)


# ===================================================================
# channel.py
# ===================================================================

class TestChannelCapacity(unittest.TestCase):
    def test_basic(self):
        # 5mm gap, 0.15mm trace + 0.15mm space = 0.3mm pitch
        # usable = 5 - 0.15 = 4.85mm, floor(4.85/0.3) = 16
        cap = calc_channel_capacity(5.0, layer_count=1)
        self.assertEqual(cap, 16)

    def test_multi_layer(self):
        cap1 = calc_channel_capacity(5.0, layer_count=1)
        cap2 = calc_channel_capacity(5.0, layer_count=2)
        self.assertGreater(cap2, cap1)

    def test_too_narrow(self):
        cap = calc_channel_capacity(0.1, layer_count=1)
        self.assertEqual(cap, 0)

    def test_zero_gap(self):
        self.assertEqual(calc_channel_capacity(0, layer_count=1), 0)

    def test_custom_rules(self):
        # 宽走线 + 大间距
        cap = calc_channel_capacity(
            5.0, layer_count=1,
            min_spacing_mm=0.3, min_width_mm=0.3,
        )
        # usable = 5 - 0.3 = 4.7mm, pitch = 0.6mm, floor(4.7/0.6) = 7
        self.assertEqual(cap, 7)


if __name__ == "__main__":
    unittest.main()
