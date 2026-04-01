"""
test_agents.py — Agent 层单元测试

离线测试（mock LLM）：
    python -m pytest test_agents.py -v

在线测试（需要 DEEPSEEK_API_KEY + 真实 KiCad）：
    python test_agents.py --live
"""
import sys
import json
import unittest
from unittest.mock import patch, MagicMock

# ===================================================================
# 网表图 + Louvain 聚类（纯算法，不需要 mock）
# ===================================================================

class TestNetlistGraph(unittest.TestCase):
    """测试网表图构建"""

    def _sample_nets(self):
        """模拟一个简单的 ESP32 最小系统网表"""
        return [
            {"name": "GND", "nodes": ["U1.GND", "C1.2", "C2.2", "C3.2", "C4.2"]},
            {"name": "+3V3", "nodes": ["U1.VDD", "C1.1", "C2.1", "U2.OUT"]},
            {"name": "VIN", "nodes": ["U2.IN", "C3.1"]},
            {"name": "VOUT_3V3", "nodes": ["U2.OUT", "C4.1"]},
            {"name": "SPI_CLK", "nodes": ["U1.CLK", "U3.CLK"]},
            {"name": "SPI_MOSI", "nodes": ["U1.MOSI", "U3.DI"]},
            {"name": "SPI_CS", "nodes": ["U1.CS", "U3.CS"]},
            {"name": "XTAL_IN", "nodes": ["U1.XI", "Y1.1"]},
            {"name": "XTAL_OUT", "nodes": ["U1.XO", "Y1.2", "C5.1", "C6.1"]},
            {"name": "LED", "nodes": ["R1.1", "D1.1"]},
            {"name": "LED_CTRL", "nodes": ["U1.IO2", "R1.2"]},
            {"name": "FB", "nodes": ["U2.ADJ", "R2.1"]},
            {"name": "FB_DIV", "nodes": ["R2.2", "R3.1"]},
        ]

    def test_build_graph(self):
        from agents.netlist_graph import build_netlist_graph
        G = build_netlist_graph(self._sample_nets())
        # GND 应被忽略
        self.assertGreater(G.number_of_nodes(), 0)
        self.assertGreater(G.number_of_edges(), 0)
        # U1 应该连接到很多器件
        self.assertIn("U1", G.nodes)

    def test_gnd_ignored(self):
        from agents.netlist_graph import build_netlist_graph
        nets = [{"name": "GND", "nodes": ["U1.1", "C1.2"]}]
        G = build_netlist_graph(nets)
        self.assertEqual(G.number_of_edges(), 0)

    def test_edge_weight(self):
        from agents.netlist_graph import build_netlist_graph
        # U1 和 U3 通过 3 个 SPI 网络连接
        G = build_netlist_graph(self._sample_nets())
        if G.has_edge("U1", "U3"):
            self.assertEqual(G["U1"]["U3"]["weight"], 3)

    def test_cluster_louvain(self):
        from agents.netlist_graph import build_netlist_graph, cluster_louvain
        G = build_netlist_graph(self._sample_nets())
        clusters = cluster_louvain(G)
        self.assertGreater(len(clusters), 0)
        # 所有图节点都应被分配
        all_assigned = set()
        for c in clusters:
            all_assigned.update(c.components)
        for node in G.nodes:
            self.assertIn(node, all_assigned)

    def test_empty_nets(self):
        from agents.netlist_graph import build_netlist_graph, cluster_louvain
        G = build_netlist_graph([])
        self.assertEqual(G.number_of_nodes(), 0)
        clusters = cluster_louvain(G)
        self.assertEqual(len(clusters), 0)


# ===================================================================
# BaseAgent（mock LLM）
# ===================================================================

class TestBaseAgent(unittest.TestCase):
    @patch("agents.llm_client.query_llm_json")
    def test_run_json(self, mock_query):
        from agents.base_agent import BaseAgent
        mock_query.return_value = {"result": "ok"}
        agent = BaseAgent("test", "You are a test agent.")
        result = agent.run_json("hello")
        self.assertEqual(result["result"], "ok")
        mock_query.assert_called_once()


# ===================================================================
# Analyzer Agent（mock LLM）
# ===================================================================

class TestAnalyzerAgent(unittest.TestCase):
    def _sample_data(self):
        components = [
            {"ref": "U1", "value": "ESP32"},
            {"ref": "C1", "value": "100nF"},
            {"ref": "C2", "value": "10uF"},
            {"ref": "U2", "value": "AMS1117-3.3"},
            {"ref": "C3", "value": "10uF"},
            {"ref": "C4", "value": "22uF"},
            {"ref": "U3", "value": "W25Q32"},
            {"ref": "Y1", "value": "32.768kHz"},
            {"ref": "C5", "value": "22pF"},
            {"ref": "C6", "value": "22pF"},
            {"ref": "R1", "value": "1k"},
            {"ref": "D1", "value": "LED"},
            {"ref": "R2", "value": "100k"},
            {"ref": "R3", "value": "22k"},
        ]
        nets = [
            {"name": "GND", "nodes": ["U1.GND", "C1.2", "C2.2", "C3.2", "C4.2"]},
            {"name": "+3V3", "nodes": ["U1.VDD", "C1.1", "C2.1", "U2.OUT"]},
            {"name": "VIN", "nodes": ["U2.IN", "C3.1"]},
            {"name": "VOUT_3V3", "nodes": ["U2.OUT", "C4.1"]},
            {"name": "SPI_CLK", "nodes": ["U1.CLK", "U3.CLK"]},
            {"name": "SPI_MOSI", "nodes": ["U1.MOSI", "U3.DI"]},
            {"name": "SPI_CS", "nodes": ["U1.CS", "U3.CS"]},
            {"name": "XTAL_IN", "nodes": ["U1.XI", "Y1.1"]},
            {"name": "XTAL_OUT", "nodes": ["U1.XO", "Y1.2", "C5.1", "C6.1"]},
            {"name": "LED", "nodes": ["R1.1", "D1.1"]},
            {"name": "LED_CTRL", "nodes": ["U1.IO2", "R1.2"]},
            {"name": "FB", "nodes": ["U2.ADJ", "R2.1"]},
            {"name": "FB_DIV", "nodes": ["R2.2", "R3.1"]},
        ]
        return components, nets

    @patch("agents.base_agent.query_llm_json")
    def test_analyzer_flow(self, mock_query):
        """测试 Analyzer 完整流程（mock LLM 输出）"""
        mock_query.return_value = {
            "board_type": "digital",
            "modules": [
                {
                    "module_id": "M01",
                    "module_name": "MCU_Core",
                    "module_type": "mcu",
                    "core_component": "U1",
                    "components": ["U1", "C1", "C2", "Y1", "C5", "C6"],
                    "layout_template_hint": "",
                    "notes": "MCU with decoupling and crystal",
                },
                {
                    "module_id": "M02",
                    "module_name": "3V3_LDO",
                    "module_type": "power_ldo",
                    "core_component": "U2",
                    "components": ["U2", "C3", "C4", "R2", "R3"],
                    "layout_template_hint": "ldo_standard",
                    "notes": "3.3V LDO with feedback divider",
                },
                {
                    "module_id": "M03",
                    "module_name": "SPI_Flash",
                    "module_type": "memory",
                    "core_component": "U3",
                    "components": ["U3"],
                    "layout_template_hint": "",
                    "notes": "",
                },
                {
                    "module_id": "M04",
                    "module_name": "LED_Status",
                    "module_type": "indicator",
                    "core_component": "D1",
                    "components": ["D1", "R1"],
                    "layout_template_hint": "led_indicator",
                    "notes": "",
                },
            ],
            "component_roles": [
                {"ref": "U1", "role": "core_ic", "priority": "critical"},
                {"ref": "C1", "role": "decoupling_cap", "priority": "critical"},
                {"ref": "C2", "role": "bulk_cap", "priority": "normal"},
                {"ref": "U2", "role": "core_ic", "priority": "critical"},
                {"ref": "C3", "role": "input_cap", "priority": "normal"},
                {"ref": "C4", "role": "output_cap", "priority": "normal"},
                {"ref": "U3", "role": "core_ic", "priority": "normal"},
                {"ref": "Y1", "role": "crystal", "priority": "critical"},
                {"ref": "C5", "role": "load_cap", "priority": "critical"},
                {"ref": "C6", "role": "load_cap", "priority": "critical"},
                {"ref": "R1", "role": "current_limit_resistor", "priority": "normal"},
                {"ref": "D1", "role": "led_indicator", "priority": "low"},
                {"ref": "R2", "role": "feedback_resistor", "priority": "critical"},
                {"ref": "R3", "role": "feedback_resistor", "priority": "critical"},
            ],
            "connections": [
                {
                    "from_module": "M01",
                    "to_module": "M03",
                    "net_names": ["SPI_CLK", "SPI_MOSI", "SPI_CS"],
                    "total_weight": 3,
                    "placement_constraint": "adjacent_tight",
                },
                {
                    "from_module": "M02",
                    "to_module": "M01",
                    "net_names": ["+3V3"],
                    "total_weight": 1,
                    "placement_constraint": "moderate",
                },
            ],
        }

        from agents.analyzer import AnalyzerAgent

        components, nets = self._sample_data()
        agent = AnalyzerAgent()
        result = agent.analyze(components, nets)

        # 验证结构
        self.assertEqual(result.board_type, "digital")
        self.assertEqual(len(result.modules), 4)
        self.assertEqual(result.total_components, 14)
        self.assertEqual(result.total_modules, 4)

        # 验证模块
        m01 = next(m for m in result.modules if m.module_id == "M01")
        self.assertEqual(m01.module_name, "MCU_Core")
        self.assertEqual(m01.core_component, "U1")
        self.assertIn("U1", m01.components)

        # 验证器件角色
        u1_comp = next(c for c in result.components if c.ref == "U1")
        self.assertEqual(u1_comp.role, "core_ic")
        self.assertEqual(u1_comp.module_id, "M01")

        # 验证连接
        self.assertEqual(len(result.connections), 2)
        spi_conn = next(c for c in result.connections if c.from_module == "M01")
        self.assertIn("SPI_CLK", spi_conn.net_names)


# ===================================================================
# 在线集成测试
# ===================================================================

def run_live_test():
    """用真实 KiCad + DeepSeek 跑一遍 Analyzer"""
    print("=" * 60)
    print("  Agent 在线集成测试 (Analyzer)")
    print("=" * 60)

    # 从 KiCad 读取数据
    from bridge.kicad_bridge import KiCadBridge
    bridge = KiCadBridge()
    bridge.connect()
    print(f"\nBoard: {bridge.board_name}")

    comps_raw = bridge.get_footprints()
    nets_raw = bridge.get_nets()
    bridge.disconnect()

    # 过滤掉 kibuzzard / logo 等非电气器件
    components = []
    for c in comps_raw:
        if c.ref.startswith("kibuzzard") or c.value in ("LOGO", "G***"):
            continue
        if c.ref == "REF**":
            continue
        components.append({"ref": c.ref, "value": c.value})

    nets = [{"name": n.name, "nodes": n.nodes} for n in nets_raw]

    print(f"Components: {len(components)}")
    print(f"Nets: {len(nets)}")

    # Step 1: 图聚类
    from agents.netlist_graph import build_netlist_graph, cluster_louvain
    G = build_netlist_graph(nets)
    clusters = cluster_louvain(G)
    print(f"\nLouvain clusters: {len(clusters)}")
    for c in clusters:
        print(f"  {c.module_id}: {len(c.components)} comps — {c.components[:6]}")

    # Step 2: LLM 增强
    print("\nCalling DeepSeek for Analyzer enrichment...")
    from agents.analyzer import AnalyzerAgent
    agent = AnalyzerAgent()
    result = agent.analyze(components, nets)

    print(f"\n--- Enriched Netlist ---")
    print(f"Board type: {result.board_type}")
    print(f"Modules: {result.total_modules}")
    for m in result.modules:
        print(f"  {m.module_id} {m.module_name} ({m.module_type})")
        print(f"    core: {m.core_component}, hint: {m.layout_template_hint}")
        print(f"    components: {m.components}")

    print(f"\nConnections: {len(result.connections)}")
    for conn in result.connections:
        print(f"  {conn.from_module} → {conn.to_module}: "
              f"weight={conn.total_weight} [{conn.placement_constraint}]")

    print("\n" + "=" * 60)
    print("  DONE")
    print("=" * 60)


if __name__ == "__main__":
    if "--live" in sys.argv:
        run_live_test()
    else:
        unittest.main(argv=["test_agents"], exit=True)
