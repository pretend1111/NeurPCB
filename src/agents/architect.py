"""
agents/architect.py — Architect 总调度官

编排完整的 PCB 自动布局流程：
  Phase 0: Analyzer → 增强网表
  Phase 1: Module Placer × N → 模块内布局（并行）
  Phase 2: Global Placer → 全局排布
  Phase 3: Router 验证 + Critic 评审 → 迭代精调
  Phase 4: 最终验证 → 输出
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from agents.analyzer import AnalyzerAgent, EnrichedNetlist, EnrichedModule
from agents.module_placer import ModulePlacerAgent
from agents.global_placer import GlobalPlacerAgent
from agents.board_map import BoardMap, ModuleRect, Anchor, InterModuleLink
from routing.router import evaluate_ratsnest_mode_a, RouterReport
from routing.critic import fast_check, deep_review, CriticReport
from skills.base import ComponentInput, PinPair, SkillResult
from geometry.core import Rect

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """端到端 pipeline 结果"""
    enriched_netlist: EnrichedNetlist | None = None
    module_placements: dict[str, SkillResult] = field(default_factory=dict)
    board_map: BoardMap | None = None
    router_report: RouterReport | None = None
    critic_report: CriticReport | None = None
    success: bool = False
    summary: str = ""


class Architect:
    """
    Architect 总调度官。

    编排全流程，不直接操作器件，而是协调各 Agent 工作。

    用法：
        architect = Architect()
        result = architect.run_pipeline(components, nets, board_rect)
    """

    def __init__(self, model: str = "deepseek-chat"):
        self.model = model

    def run_pipeline(
        self,
        components: list[dict],
        nets: list[dict],
        board_rect: Rect,
        copper_layers: int = 2,
        locked_components: list[dict] | None = None,
        max_iterations: int = 3,
    ) -> PipelineResult:
        """
        运行完整的自动布局 pipeline。

        components: [{"ref": "U1", "value": "ESP32", ...}]
        nets: [{"name": "VCC", "nodes": ["U1.1", "C1.1"]}]
        board_rect: 板框矩形
        copper_layers: 铜层数
        locked_components: 用户锁定的器件 [{"ref": "J1", "x_mm": 10, "y_mm": 50}]
        """
        result = PipelineResult()
        locked = locked_components or []

        # ===== Phase 0: Analyzer =====
        logger.info("=" * 50)
        logger.info("Phase 0: Analyzer")
        logger.info("=" * 50)

        analyzer = AnalyzerAgent(model=self.model)
        enriched = analyzer.analyze(components, nets)
        result.enriched_netlist = enriched

        logger.info("Analyzer output: %d modules, %d components, board_type=%s",
                     enriched.total_modules, enriched.total_components, enriched.board_type)

        # ===== Phase 1: Module Placer (逐模块) =====
        logger.info("=" * 50)
        logger.info("Phase 1: Module Placement (%d modules)", len(enriched.modules))
        logger.info("=" * 50)

        # 构建 ComponentInput 映射
        comp_input_map = self._build_component_inputs(components)

        # 构建模块内连接
        module_connections = self._build_module_connections(enriched, nets)

        placer = ModulePlacerAgent(model=self.model)
        module_bboxes: dict[str, Rect] = {}

        for i, module in enumerate(enriched.modules):
            logger.info("  Placing module %s (%s) [%d/%d]",
                        module.module_id, module.module_name, i + 1, len(enriched.modules))

            module_comps = {ref: comp_input_map[ref]
                           for ref in module.components if ref in comp_input_map}
            conns = module_connections.get(module.module_id, [])

            # 模块原点：暂时放在板框中心（Global Placer 后续会调整）
            origin = (board_rect.cx, board_rect.cy)

            skill_result = placer.place_module(module, module_comps, conns, origin)
            result.module_placements[module.module_id] = skill_result
            module_bboxes[module.module_id] = skill_result.bbox

            logger.info("    → %d/%d placed, bbox %.0fx%.0fmm",
                        len(skill_result.placements), len(module.components),
                        skill_result.bbox.w, skill_result.bbox.h)

        # ===== Phase 2: Global Placer =====
        logger.info("=" * 50)
        logger.info("Phase 2: Global Placement")
        logger.info("=" * 50)

        board_map = self._build_board_map(
            board_rect, copper_layers, enriched, module_bboxes, locked)
        result.board_map = board_map

        logger.info("Initial map:\n%s", board_map.to_text())

        gp = GlobalPlacerAgent(model=self.model)
        board_map = gp.place_global(board_map)

        logger.info("After global placement:\n%s", board_map.to_text())

        # ===== Phase 3: Router + Critic 迭代 =====
        logger.info("=" * 50)
        logger.info("Phase 3: Router + Critic Verification")
        logger.info("=" * 50)

        for iteration in range(max_iterations):
            logger.info("--- Iteration %d ---", iteration + 1)

            # Router 验证
            router_report = evaluate_ratsnest_mode_a(board_map)
            result.router_report = router_report
            logger.info("Router: routability=%.2f, crossings=%d, hotspots=%d",
                        router_report.routability_score,
                        router_report.ratsnest_crossings,
                        len(router_report.hotspots))

            # Critic 评审
            critic_report = deep_review(board_map, enriched.board_type)
            result.critic_report = critic_report
            logger.info("Critic: %s", critic_report.summary().split('\n')[0])

            # 收敛判定
            if critic_report.critical == 0 and router_report.routability_score >= 0.7:
                logger.info("Converged: no critical issues, routability >= 0.7")
                break

            if iteration < max_iterations - 1:
                logger.info("Issues remain, but skipping auto-fix in current version")

        # ===== Phase 4: 最终结果 =====
        logger.info("=" * 50)
        logger.info("Phase 4: Final Result")
        logger.info("=" * 50)

        result.success = (result.critic_report.critical == 0)
        result.summary = self._generate_summary(result)
        logger.info(result.summary)

        return result

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------

    def _build_component_inputs(self, components: list[dict]) -> dict[str, ComponentInput]:
        """从原始器件列表构建 ComponentInput 映射"""
        result = {}
        for c in components:
            ref = c.get("ref", "")
            if not ref:
                continue
            # 根据位号前缀估算封装尺寸
            w, h, pins = self._estimate_package_size(ref, c.get("value", ""))
            result[ref] = ComponentInput(
                ref=ref,
                value=c.get("value", ""),
                footprint=c.get("footprint", ""),
                width_mm=w,
                height_mm=h,
                pin_count=pins,
            )
        return result

    @staticmethod
    def _estimate_package_size(ref: str, value: str) -> tuple[float, float, int]:
        """根据位号前缀粗略估算封装尺寸"""
        prefix = ref.rstrip("0123456789*")
        if prefix in ("U",):
            return (5.0, 5.0, 20)
        if prefix in ("C", "R", "L"):
            return (1.5, 0.8, 2)
        if prefix in ("D",):
            return (1.8, 1.0, 2)
        if prefix in ("J",):
            return (8.0, 5.0, 10)
        if prefix in ("Y",):
            return (3.0, 1.5, 2)
        if prefix in ("Q",):
            return (2.0, 2.0, 3)
        if prefix in ("SW",):
            return (3.0, 3.0, 4)
        if prefix in ("TP",):
            return (1.0, 1.0, 1)
        return (2.0, 2.0, 2)

    def _build_module_connections(
        self, enriched: EnrichedNetlist, nets: list[dict],
    ) -> dict[str, list[PinPair]]:
        """为每个模块构建内部连接"""
        # ref → module_id 映射
        ref_to_module = {}
        for m in enriched.modules:
            for ref in m.components:
                ref_to_module[ref] = m.module_id

        # 从网表构建模块内连接
        module_conns: dict[str, list[PinPair]] = {}
        for net in nets:
            nodes = net.get("nodes", [])
            refs = list({n.split(".")[0] for n in nodes if "." in n})
            for i in range(len(refs)):
                for j in range(i + 1, len(refs)):
                    mi = ref_to_module.get(refs[i])
                    mj = ref_to_module.get(refs[j])
                    if mi and mj and mi == mj:
                        conns = module_conns.setdefault(mi, [])
                        conns.append(PinPair(refs[i], refs[j], 1.0))

        return module_conns

    def _build_board_map(
        self,
        board_rect: Rect,
        copper_layers: int,
        enriched: EnrichedNetlist,
        module_bboxes: dict[str, Rect],
        locked: list[dict],
    ) -> BoardMap:
        """从 Analyzer 输出和 Module Placer 结果构建地图"""
        bmap = BoardMap(board=board_rect, copper_layers=copper_layers)

        # 锚点
        for lc in locked:
            bmap.anchors.append(Anchor(
                ref=lc.get("ref", ""),
                x_mm=lc.get("x_mm", 0),
                y_mm=lc.get("y_mm", 0),
                description=lc.get("description", ""),
            ))

        # 模块矩形
        for module in enriched.modules:
            bbox = module_bboxes.get(module.module_id)
            if bbox is None or bbox.area < 0.1:
                # 估算尺寸
                n = len(module.components)
                side = max(5, n * 2.5)
                bbox = Rect.from_center(board_rect.cx, board_rect.cy, side, side)

            bmap.modules.append(ModuleRect(
                module_id=module.module_id,
                name=module.module_name,
                rect=bbox,
                component_count=len(module.components),
            ))

        # 模块间连接
        for conn in enriched.connections:
            bmap.links.append(InterModuleLink(
                from_id=conn.from_module,
                to_id=conn.to_module,
                weight=conn.total_weight,
                net_names=conn.net_names,
                constraint=conn.placement_constraint,
            ))

        return bmap

    def _generate_summary(self, result: PipelineResult) -> str:
        lines = ["=" * 50, "NeurPCB Auto-Layout Summary", "=" * 50]

        if result.enriched_netlist:
            en = result.enriched_netlist
            lines.append(f"Board type: {en.board_type}")
            lines.append(f"Components: {en.total_components}")
            lines.append(f"Modules: {en.total_modules}")
            for m in en.modules:
                lines.append(f"  {m.module_id} {m.module_name}: {len(m.components)} components")

        lines.append("")
        if result.board_map:
            lines.append(f"Board utilization: {result.board_map.calc_utilization()}%")
            lines.append(f"Module overlaps: {len(result.board_map.check_overlaps())}")

        if result.router_report:
            lines.append(f"Routability: {result.router_report.routability_score}")
            lines.append(f"Ratsnest crossings: {result.router_report.ratsnest_crossings}")

        if result.critic_report:
            lines.append(f"Critic: {result.critic_report.critical} critical, "
                         f"{result.critic_report.major} major, {result.critic_report.minor} minor")

        lines.append(f"\nResult: {'SUCCESS' if result.success else 'NEEDS_ATTENTION'}")
        return "\n".join(lines)
