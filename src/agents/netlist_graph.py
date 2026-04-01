"""
agents/netlist_graph.py — 网表图构建 + Louvain 聚类

从 bridge 读取的 NetInfo 构建 networkx 图，
用 Louvain 算法生成模块划分初稿。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import networkx as nx
from networkx.algorithms.community import louvain_communities

logger = logging.getLogger(__name__)

# GND 网络不参与模块间权重计算（铺铜处理）
_IGNORE_NETS = {"GND", "gnd", "GNDA", "GNDD", "AGND", "DGND", ""}


@dataclass
class ModuleCluster:
    """图聚类输出的模块"""
    module_id: str
    components: list[str]
    internal_nets: list[str] = field(default_factory=list)


def build_netlist_graph(
    nets: list[dict],
    ignore_nets: set[str] | None = None,
) -> nx.Graph:
    """
    从网表构建无向加权图。

    nets: [{"name": "VCC", "nodes": ["U1.1", "C1.1"]}, ...]
          每个 node 格式 "REF.PAD"
    ignore_nets: 忽略的网络名集合（默认忽略 GND 系列）

    返回 networkx 图：
    - 节点 = 器件 ref（如 "U1"）
    - 边权重 = 两个器件共享的网络数量
    """
    if ignore_nets is None:
        ignore_nets = _IGNORE_NETS

    G = nx.Graph()

    for net in nets:
        net_name = net.get("name", "")
        if net_name in ignore_nets:
            continue

        nodes = net.get("nodes", [])
        # 提取器件 ref（"U1.3" → "U1"）
        refs = list({n.split(".")[0] for n in nodes if "." in n})

        # 确保所有 ref 都在图中
        for ref in refs:
            if not G.has_node(ref):
                G.add_node(ref)

        # 同一网络内的器件两两连边，权重 +1
        for i in range(len(refs)):
            for j in range(i + 1, len(refs)):
                if G.has_edge(refs[i], refs[j]):
                    G[refs[i]][refs[j]]["weight"] += 1
                else:
                    G.add_edge(refs[i], refs[j], weight=1)

    logger.info("Built netlist graph: %d nodes, %d edges", G.number_of_nodes(), G.number_of_edges())
    return G


def cluster_louvain(
    G: nx.Graph,
    resolution: float = 1.0,
    min_module_size: int = 2,
    max_module_size: int = 20,
    seed: int = 42,
) -> list[ModuleCluster]:
    """
    Louvain 社区检测，生成模块划分。

    resolution: Louvain 分辨率参数（越大越倾向于分成更多小模块）
    min_module_size: 最小模块大小（过小的合并到最紧密相邻模块）
    max_module_size: 最大模块大小（超过的暂不自动拆分，留给 LLM）
    seed: 随机种子

    返回: 模块列表
    """
    if G.number_of_nodes() == 0:
        return []

    # 孤立节点（没有边的器件）先记录
    isolates = list(nx.isolates(G))

    # Louvain 聚类
    communities = louvain_communities(G, weight="weight", resolution=resolution, seed=seed)

    modules: list[ModuleCluster] = []
    for idx, community in enumerate(sorted(communities, key=len, reverse=True)):
        modules.append(ModuleCluster(
            module_id=f"M{idx + 1:02d}",
            components=sorted(community),
        ))

    # 合并过小的模块到最紧密邻居
    merged = _merge_small_modules(modules, G, min_module_size)

    # 添加孤立节点到最近的模块
    assigned_refs = {ref for m in merged for ref in m.components}
    unassigned = [ref for ref in G.nodes if ref not in assigned_refs]

    for ref in unassigned:
        best_module = _find_closest_module(ref, merged, G)
        if best_module is not None:
            best_module.components.append(ref)
        elif merged:
            merged[-1].components.append(ref)
        else:
            merged.append(ModuleCluster(module_id="M01", components=[ref]))

    # 标注每个模块的内部网络（后续 LLM 增强时用）
    # 这里留空，由 Analyzer Agent 填充

    logger.info("Louvain clustering: %d modules from %d components",
                len(merged), G.number_of_nodes())
    for m in merged:
        logger.debug("  %s: %d components %s", m.module_id, len(m.components), m.components[:5])

    return merged


def _merge_small_modules(
    modules: list[ModuleCluster],
    G: nx.Graph,
    min_size: int,
) -> list[ModuleCluster]:
    """将过小的模块合并到连接最紧密的邻居模块"""
    result = [m for m in modules if len(m.components) >= min_size]
    small = [m for m in modules if len(m.components) < min_size]

    for sm in small:
        best = _find_closest_module_for_group(sm.components, result, G)
        if best is not None:
            best.components.extend(sm.components)
        elif result:
            result[-1].components.extend(sm.components)
        else:
            result.append(sm)

    return result


def _find_closest_module(
    ref: str,
    modules: list[ModuleCluster],
    G: nx.Graph,
) -> ModuleCluster | None:
    """找到与 ref 连接最紧密的模块"""
    best_score = 0
    best_module = None
    for m in modules:
        score = sum(G[ref][c]["weight"] for c in m.components if G.has_edge(ref, c))
        if score > best_score:
            best_score = score
            best_module = m
    return best_module


def _find_closest_module_for_group(
    refs: list[str],
    modules: list[ModuleCluster],
    G: nx.Graph,
) -> ModuleCluster | None:
    """找到与一组 ref 连接最紧密的模块"""
    best_score = 0
    best_module = None
    for m in modules:
        score = 0
        for ref in refs:
            score += sum(G[ref][c]["weight"] for c in m.components if G.has_edge(ref, c))
        if score > best_score:
            best_score = score
            best_module = m
    return best_module
