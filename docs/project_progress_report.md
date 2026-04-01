# NeurPCB 项目进展报告

> **更新日期**：2026-04-01  
> **当前状态**：Phase 0-7 全部完成，端到端 Pipeline 已在真实 PCB 上验证  
> **测试覆盖**：124 个单元测试全部通过  
> **代码规模**：51 个 Python 文件，约 7200 行

---

## 1. 项目概要

NeurPCB 是一个基于多 Agent + LLM 的 PCB 自动布局系统。核心思想是 **"LLM 做决策大脑，传统算法做执行手脚"**，通过黑盒递归降维将数百个器件的布局问题分解为 LLM 可处理的规模。

系统从一个打开的 KiCad 9.0 工程读取网表，经过 Analyzer（模块划分）→ Module Placer（模块内布局）→ Global Placer（全局排布）→ Router + Critic（验证评审）→ 写回 KiCad 的完整闭环。

**LLM 后端**：DeepSeek（OpenAI 兼容接口），通过 tool-calling 驱动 Agent 循环。

---

## 2. 架构总览

```
KiCad 9.0 (.kicad_pcb)
    │
    ▼
┌─────────────────────────────────────────────────┐
│  bridge/kicad_bridge.py  (KiCad IPC 桥接)       │
│  读取器件/网表/板框/叠层 ↔ 写入器件坐标          │
└────────────┬────────────────────────────────────┘
             │
    ┌────────▼────────┐
    │   Architect      │  ← 总调度官，编排全流程
    │  (architect.py)  │
    └──┬─────┬────┬───┘
       │     │    │
  ┌────▼──┐ ┌▼────▼─────┐ ┌──────────┐
  │Analyzer│ │Module     │ │Global    │
  │  (LLM) │ │Placer ×N │ │Placer    │
  │        │ │  (LLM)   │ │  (LLM)   │
  └────────┘ └──────────┘ └──────────┘
       │          │              │
  ┌────▼──────────▼──────────────▼────┐
  │     geometry/ + skills/            │
  │  纯算法层（不碰 LLM、不碰 KiCad） │
  └──────────────┬────────────────────┘
                 │
  ┌──────────────▼────────────────────┐
  │   routing/router.py + critic.py    │
  │   飞线分析 + 磁力场 + 规则引擎     │
  └────────────────────────────────────┘
```

---

## 3. 各层详细说明

### 3.1 Bridge 层 (`src/bridge/kicad_bridge.py`)

统一的 KiCad IPC 桥接类，**所有上层模块通过此类与 KiCad 交互，不直接 import kipy**。

| 功能 | 方法 |
|------|------|
| 连接管理 | `connect()` / `disconnect()` / context manager |
| 读取器件 | `get_footprints()` → `ComponentInfo` 列表 |
| 读取网表 | `get_nets()` → `NetInfo` 列表 |
| 读取板框 | `get_board_outline()` → `BoardOutline` |
| 读取叠层 | `get_stackup()` / `get_copper_layer_count()` |
| 真实封装尺寸 | `get_real_footprint_sizes()` → pad 坐标算 bbox |
| 移动/旋转 | `move_footprint()` / `rotate_footprint()` / `batch_move_footprints()` |
| 事务管理 | `begin_commit()` / `push_commit()` / `drop_commit()` |

**踩坑记录**：
- kipy `update_items()` 必须传列表 `[fp]`，不能传单个对象
- kipy `get_footprints()` 会返回撤销栈旧副本，需按 UUID 去重
- kipy `FootprintInstance` 没有 `.reference`/`.value`/`.pads` 属性，需用 `.reference_field.text.value` 等路径访问
- `KiCad()` 没有 `close()` 或 context manager

### 3.2 几何计算层 (`src/geometry/`)

纯算法，不碰 KiCad API，不碰 LLM。

| 模块 | 功能 |
|------|------|
| `core.py` | `Rect` 数据结构、`calc_distance`、`calc_bbox`、`calc_overlap`、`resolve_overlap_minimum_displacement` |
| `ratsnest.py` | `calc_ratsnest_crossings`（叉积法）、`calc_ratsnest_total_length` |
| `congestion.py` | `calc_congestion_heatmap`（网格密度）、`calc_force_field_energy`（弹簧势能 0~1 评分） |
| `channel.py` | `calc_channel_capacity`（通道走线容量，支持多层+过孔） |

### 3.3 布局 Skills (`src/skills/`)

确定性布局算法，LLM 通过 tool-calling 调用。

**模块级 Skills** (`skills/module/`)：

| Skill | 用途 | 核心逻辑 |
|-------|------|---------|
| `skill_ldo_layout` | 线性稳压器 | 输入电容→IC→输出电容线性排列，反馈电阻 Kelvin 连接 |
| `skill_crystal_layout` | 晶振+负载电容 | 晶振贴近时钟引脚，负载电容对称两侧 |
| `skill_decap_cluster` | 去耦电容群 | 围绕 IC 扇形排列或对准电源引脚 |
| `skill_force_directed_place` | 通用布局 | 弹簧吸引+斥力排斥+模拟退火 |
| `skill_led_indicator` | LED+限流电阻 | 串联紧凑排列 |
| `skill_voltage_divider` | 分压器 | 对称串联 |
| `skill_compact_module` | 紧凑化 | 保持相对位置，自动缩放到最小无重叠尺寸 |

**全局级 Skills** (`skills/global_skills/`)：

| Skill | 用途 |
|-------|------|
| `skill_gp_force_directed` | 模块级力导向排布（连接权重弹簧+锚点固定+板框约束） |
| `skill_gp_resolve_overlap` | 最小位移消解模块矩形重叠 |

### 3.4 Agent 层 (`src/agents/`)

| Agent | 角色 | 工作模式 | 工具数 |
|-------|------|---------|--------|
| `AnalyzerAgent` | 电路语义分析师 | JSON 模式 | — |
| `ModulePlacerAgent` | 模块内布局工匠 | tool-calling | 8 个 |
| `GlobalPlacerAgent` | 全局排布策略师 | tool-calling | 10 个 |
| `Architect` | 总调度官 | 编排器（非 LLM Agent） | — |

**Analyzer 流程**：
1. 从网表构建 networkx 加权图（GND 自动排除）
2. Louvain 社区检测生成模块划分初稿
3. LLM（DeepSeek）校正：重命名模块、修正去耦电容归属、标注器件角色和信号类型
4. 输出 `EnrichedNetlist`（增强网表）

**Module Placer tool-calling 工具集**：
- `observe_module_layout` — 查看当前布局状态
- `observe_violations` — 检查重叠/间距违规
- `apply_skill` — 调用布局 Skill（ldo/crystal/decap/force_directed/compact 等）
- `move_component` / `rotate_component` / `swap_components` — 原子操作
- `finish_placement` — 声明布局完成

**Global Placer tool-calling 工具集**：
- `gp_observe_map` — 获取地图快照（~400 token 文本）
- `gp_apply_force_directed` — 力导向自动排布
- `gp_resolve_overlap` — 消解重叠
- `gp_move_module` / `gp_swap_modules` — 手动调整
- `gp_check_overlap` / `gp_check_board_fit` — 验证
- `gp_finish` — 声明排布完成

### 3.5 Router + Critic (`src/routing/`)

| 模块 | 功能 |
|------|------|
| `router.py` | 模式 A 飞线分析：总长度、交叉数、拥塞热力图、通道瓶颈、磁力场评分（信号类型加权） |
| `critic.py` | Fast Check（重叠/板框/间距，毫秒级）+ Deep Review（高权重距离检查+利用率分析） |

### 3.6 地图系统 (`src/agents/board_map.py`)

`BoardMap` 将整个 PCB 状态压缩为 ~400 token 的文本，供 LLM 消费：

```
Board: 22.9×63.5mm, 2-layer, origin=(130.5,68.9), end=(153.4,132.4)
  Valid X range: 130.5 ~ 153.4
  Valid Y range: 68.9 ~ 132.4

Modules (5 total):
  M01 "MCU_Core" center=(142.0,85.0) size=15×12mm components=14
  M02 "USB_Interface" center=(142.0,125.0) size=10×8mm components=8
  ...

Inter-module connections (top 5):
  M01↔M05: weight=12 [adjacent_tight]
  ...

Metrics:
  Board utilization: 68%
  Module overlaps: 0
  Routability estimate: 0.98
```

---

## 4. 端到端 Pipeline 流程

```python
from agents.architect import Architect

architect = Architect()
result = architect.run_pipeline(components, nets, board_rect,
                                real_sizes=real_sizes)

# result.get_final_positions() → {ref: (x_mm, y_mm)} 可直接写回 KiCad
```

**Pipeline 内部流程**：

1. **Phase 0 — Analyzer**：Louvain 聚类 → LLM 校正 → 增强网表
2. **Phase 1 — Module Placer ×N**：每个模块独立布局 → 自动紧凑化
3. **未分配器件处理**：orphan 器件用 force_directed 放置
4. **Phase 2 — Global Placer**：力导向排布 → 消解重叠 → 推入板框
5. **Phase 3 — Router + Critic**：飞线分析 + 规则检查 → 迭代验证
6. **Phase 4 — 输出**：生成摘要 + `get_final_positions()` 写回 KiCad

---

## 5. 实测结果

### 测试板：ESP32-C3 DevKit Rust Board

| 指标 | 数值 |
|------|------|
| 板框尺寸 | 22.9 × 63.5 mm |
| 电气器件 | 55 个 |
| 网络 | 63 个 |
| 铜层 | 2 层 |

### 端到端测试（打乱所有器件 → 自动布局 → 写回 KiCad）

| 指标 | v1 (首次) | v3 (当前) |
|------|-----------|-----------|
| 器件写回 | 54/54（堆在左上角） | 54/54（板框内） |
| Critical 问题 | 16 | 2 |
| 模块重叠 | 8 | 1 |
| 未分配器件 | 有遗漏 | 0 |
| LLM 调用次数 | ~80 | ~60 |
| 总耗时 | ~3 分钟 | ~2 分钟 |

剩余 2 个 critical 主因是板面积过小（利用率 175%），需要更精确的封装 courtyard 数据。

---

## 6. 环境配置

```bash
# Python 环境
conda activate kicad
pip install kicad-python networkx openai httpx[socks]

# 环境变量
export DEEPSEEK_API_KEY=sk-...

# KiCad 9.0 打开 .kicad_pcb 文件，启用 API Server：
# Preferences → Plugins → Enable IPC API Server

# 运行测试（不需要 KiCad）
cd NeurPCB/src
python -m pytest test_bridge.py test_geometry.py test_skills.py test_agents.py test_module_placer.py test_global_placer.py test_pipeline.py -v

# 运行 live 测试（需要 KiCad + DeepSeek）
DEEPSEEK_API_KEY=sk-... python test_agents.py --live
DEEPSEEK_API_KEY=sk-... python test_module_placer.py --live
DEEPSEEK_API_KEY=sk-... python test_pipeline.py --live
```

---

## 7. 目录结构

```
NeurPCB/src/
├── bridge/
│   ├── kicad_bridge.py        # 统一 KiCad IPC 桥接（核心）
│   ├── blackbox.py            # [旧 PoC] 黑盒封装
│   ├── kicad_extractor.py     # [旧 PoC] 已废弃，由 kicad_bridge 替代
│   ├── kicad_executor.py      # [旧 PoC] 已废弃
│   ├── radar.py               # [旧 PoC] 局部雷达
│   └── turtle.py              # [旧 PoC] 步进式走线
│
├── geometry/
│   ├── core.py                # Rect、距离、bbox、重叠、消解重叠
│   ├── ratsnest.py            # 飞线交叉、总长度
│   ├── congestion.py          # 拥塞热力图、磁力场势能
│   └── channel.py             # 通道走线容量
│
├── skills/
│   ├── base.py                # Placement / SkillResult / ComponentInput
│   ├── module/
│   │   ├── ldo_layout.py      # LDO 标准布局
│   │   ├── crystal_layout.py  # 晶振布局
│   │   ├── decap_cluster.py   # 去耦电容排列
│   │   ├── force_directed.py  # 力导向通用布局
│   │   ├── compact_module.py  # 模块紧凑化
│   │   ├── led_indicator.py   # LED+限流电阻
│   │   └── voltage_divider.py # 分压器
│   └── global_skills/
│       └── gp_skills.py       # 模块级力导向+重叠消解
│
├── agents/
│   ├── llm_client.py          # DeepSeek OpenAI 兼容客户端
│   ├── base_agent.py          # Agent 基类（JSON + tool-calling）
│   ├── analyzer.py            # Analyzer Agent + EnrichedNetlist
│   ├── module_placer.py       # Module Placer Agent（8 个工具）
│   ├── global_placer.py       # Global Placer Agent（10 个工具）
│   ├── architect.py           # Architect 总调度 + Pipeline
│   ├── board_map.py           # 地图系统（BoardMap）
│   └── netlist_graph.py       # 网表图构建 + Louvain 聚类
│
├── routing/
│   ├── router.py              # Router 飞线分析+磁力场评估
│   └── critic.py              # Critic Fast Check+Deep Review
│
├── test_bridge.py             # 22 个测试
├── test_geometry.py           # 40 个测试
├── test_skills.py             # 17 个测试
├── test_agents.py             # 7 个测试
├── test_module_placer.py      # 12 个测试
├── test_global_placer.py      # 16 个测试
└── test_pipeline.py           # 10 个测试
                               # 合计 124 个测试
```

---

## 8. 已知问题与后续方向

### 8.1 当前限制

| 问题 | 原因 | 优先级 |
|------|------|--------|
| 高密度板模块重叠 | 封装 courtyard 尺寸仍有偏差（pad span ≠ courtyard） | 高 |
| Module Placer 偶尔超出 15 轮限制 | 复杂模块器件多，LLM 微调步数不够 | 中 |
| 迭代精调未自动修复 | Router/Critic 发现问题后只报警不回调 | 高 |
| 单面贴装限制 | 架构文档已规划双面支持 | 低 |

### 8.2 建议的下一步开发

**优先级高**：
1. **Critic → Architect 反馈闭环**：Critic 发现问题后，自动生成修复任务分派给对应 Placer
2. **读取真实 courtyard**：从 kipy 读封装 courtyard 层图形，替代 pad span 估算
3. **增加 Module Placer 轮数上限**，或允许分阶段多次调用

**优先级中**：
4. **更多 Skills**：`skill_buck_layout`、`skill_usb_esd_layout`、`skill_connector_fanout`
5. **Router 模式 B**：通道级粗布线评估
6. **Critic Deep Review 接入 LLM**：当前是规则引擎，可升级为 LLM 驱动的领域知识检查

**优先级低**：
7. 双面贴装支持
8. 导出布局报告（SVG 可视化）
9. 用户中间干预（暂停 + 手动调整 + 继续）

---

## 9. 关键 API 速查

### 完整 Pipeline 调用

```python
from bridge.kicad_bridge import KiCadBridge
from agents.architect import Architect
from geometry.core import Rect

# 从 KiCad 读取
bridge = KiCadBridge()
bridge.connect()
comps = bridge.get_footprints()
nets = bridge.get_nets()
outline = bridge.get_board_outline()
real_sizes = bridge.get_real_footprint_sizes()
board_rect = Rect(outline.min_x_mm, outline.min_y_mm,
                  outline.width_mm, outline.height_mm)

# 过滤非电气器件
components = [{"ref": c.ref, "value": c.value, "footprint": c.footprint}
              for c in comps if not c.ref.startswith("kibuzzard")]
net_list = [{"name": n.name, "nodes": n.nodes} for n in nets]

# 跑 Pipeline
architect = Architect()
result = architect.run_pipeline(components, net_list, board_rect,
                                real_sizes=real_sizes)

# 写回 KiCad
positions = result.get_final_positions()
bridge.begin_commit()
bridge.batch_move_footprints(positions)
bridge.push_commit("NeurPCB auto-layout")
bridge.disconnect()
```

### 单独使用各模块

```python
# Analyzer 单独使用
from agents.analyzer import AnalyzerAgent
analyzer = AnalyzerAgent()
enriched = analyzer.analyze(components, nets)

# Module Placer 单独使用
from agents.module_placer import ModulePlacerAgent
placer = ModulePlacerAgent()
result = placer.place_module(module, comp_inputs, connections, origin)

# 几何计算
from geometry.core import calc_distance, calc_bbox, Rect
from geometry.ratsnest import calc_ratsnest_crossings

# Skill 直接调用
from skills.module.ldo_layout import skill_ldo_layout
result = skill_ldo_layout(core_ic, input_caps, output_caps)
```
