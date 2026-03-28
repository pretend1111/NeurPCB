# PCB 多 Agent 自动布局系统 — 分工架构设计

> **文档版本**：v0.1-draft  
> **状态**：架构讨论稿，待评审后进入详细设计  
> **目标**：定义基于闭源顶尖 LLM（Claude / GPT / Gemini）的多 Agent 协作系统，实现从"原理图转 PCB 后的初始状态"到"可交付布线的高质量布局"的全自动流程。

---

## 1. 设计哲学与系统边界

### 1.1 核心理念

**LLM 做决策大脑，传统算法做执行手脚。**

LLM 擅长理解电路语义（"这是 LDO 的反馈电阻，必须 Kelvin 连接"）、做模糊的空间推理（"射频模块应该远离数字核心"）、以及跨领域知识调用。但 LLM 不擅长精确的几何计算、坐标运算和大规模数值优化。因此，系统中所有需要精确计算的工作（碰撞检测、距离计算、拥塞评估、布线验证）均由传统算法完成，LLM 只负责"决定做什么"和"判断结果好不好"。

**不走固定流水线，走自由迭代循环。**

真实的 PCB 布局工程师不会"先全部摆完再布线"。他们摆一片、心里跑一遍粗布线、觉得不对就回头调。本系统模拟这种认知模式：Architect 规划 → Placer 执行 → Critic/Router 验证 → 发现问题 → Placer 调整 → 再验证 → 循环直到收敛。没有"模块内阶段"和"模块间阶段"的硬性区分，Architect 可以随时决定回退到任何粒度。

**分治降复杂度，每个 Agent 只看它该看的。**

一块 200 个器件的板子，没有任何 LLM 能一次性处理全部状态。解决方案是分层抽象：Module Placer 只看模块内的 3-15 个器件；Global Placer 只看模块矩形和模块间连接；Architect 只看一张由模块矩形构成的"地图"。每一层的信息密度都被压缩到 LLM 的有效处理范围内。

### 1.2 系统输入与输出

**输入（用户提供）：**

用户提供一个 KiCad 工程文件（`.kicad_pcb` + `.kicad_sch`），该文件处于"原理图刚转 PCB"的初始状态。用户需要预先完成以下工作：

- 板框（Board Outline）已绘制在 Edge.Cuts 层
- 必须固定位置的器件已放置并锁定（如 USB-C 连接器、排针、安装孔等由产品物理约束决定位置的器件）
- 层叠结构（Stackup）已配置（层数、铜厚、介质厚度）
- 网络类（Net Class）已配置（线宽、间距、过孔规格等基本规则）

用户可选提供的额外信息：

- 特殊布局要求的自然语言描述（如"天线必须在板子右上角"、"散热片朝上"）
- 关键信号的约束说明（如"DDR 数据线等长误差 ±50mil"）
- 目标板子类型标签（如"消费电子"、"工业控制"、"射频前端"）

**输出：**

一个布局完成的 `.kicad_pcb` 文件，所有器件已放置到合理位置，朝向正确，满足 DRC 基本规则，可布线性评估达标。布线本身不在本系统范围内（由后续的自动布线器或人工完成），但布局质量应确保布线器能顺利完成工作。

### 1.3 前提假设与约束

- 当前版本仅考虑**单面贴装**布局（所有 SMD 器件放置在正面 F.Cu），走线可使用背面及内层
- 系统基于 KiCad 9.0+ 运行，通过 `kipy` Python API 与 KiCad 实时交互
- 所有操作直接作用于用户正在用 KiCad 打开的 PCB 工程，操作结果实时可见
- GND 网络默认通过铺铜（Copper Pour）实现连接，在布局阶段和布线验证阶段均不纳入飞线和走线评估
- 系统不修改原理图，不增删器件，不改变网表连接关系

---

## 2. Agent 角色全景

系统由 **4 类 LLM Agent** + **1 层传统算法工具** 构成：

```
┌─────────────────────────────────────────────────────────┐
│                    LLM Agent 层                          │
│                                                         │
│  ┌──────────┐  ┌───────────┐  ┌────────────────────┐   │
│  │ Analyzer │  │ Architect │  │     Placer 集群     │   │
│  │ (分析师)  │  │ (调度官)   │  │ ┌────────────────┐ │   │
│  └────┬─────┘  └─────┬─────┘  │ │ Module Placer  │ │   │
│       │              │        │ │ ×N (每模块一个)  │ │   │
│       │              │        │ ├────────────────┤ │   │
│       │              │        │ │ Global Placer  │ │   │
│       │              │        │ │ ×M (按复杂度)   │ │   │
│       │              │        │ └────────────────┘ │   │
│       │              │        └────────────────────┘   │
│       │              │                                  │
│  ┌────┴──────┐  ┌────┴─────┐                           │
│  │  Router   │  │  Critic  │                           │
│  │ (布线验证) │  │ (评审员)  │                           │
│  └───────────┘  └──────────┘                           │
├─────────────────────────────────────────────────────────┤
│                   传统算法工具层                          │
│                                                         │
│  Geometry Solver │ Graph Clusterer │ Congestion Estimator│
│  DRC Engine │ Global Router │ Detailed Router            │
│  Loop Area Calculator │ Ref-Plane Checker               │
│  Force-Field Evaluator │ KiCad API Bridge               │
└─────────────────────────────────────────────────────────┘
```

各 Agent 的核心定位：

| Agent | 本质 | 看到什么 | 不看什么 |
|-------|------|---------|---------|
| Analyzer | 电路理解专家 | 原理图网表、层级结构、器件数据手册摘要 | 板框、物理坐标 |
| Architect | 总指挥官 | 地图（模块矩形 + 板框）、各 Agent 反馈摘要 | 单个器件坐标、具体走线 |
| Module Placer | 模块内布局工匠 | 本模块内的器件详情、引脚位置、内部网表 | 其他模块内部、全局布线 |
| Global Placer | 全局排布策略师 | 板框、所有模块矩形、模块间连接权重 | 模块内部器件、具体走线 |
| Router | 布线可行性验证官 | 模块间连接的飞线、板框、模块矩形（作为障碍） | 模块内部走线 |
| Critic | 质量审计员 | 按需读取任意粒度的板子信息、领域知识库 | 不主动获取，按检查清单逐项查阅 |

---

## 3. Analyzer — 电路语义分析师

### 3.1 职责

Analyzer 是整个系统的第一个环节，也是 LLM 最擅长的工作。它的任务是"读懂电路"：从原始网表和原理图层级中提取出人类工程师一眼就能看出、但原始数据中没有显式表达的语义信息。

Analyzer 不需要知道板框信息，不关心物理坐标，只关心电路的逻辑结构。

### 3.2 输入

- 原理图网表（从 KiCad 工程提取）：所有器件、所有网络、所有连接关系
- 原理图层级结构（Sheet hierarchy）：原理图中的模块划分（如果有的话，仅作参考）
- 器件属性信息：封装类型、额定值、功能描述
- 用户提供的额外约束（自然语言）

### 3.3 输出：增强网表

Analyzer 的输出是一份结构化的"增强网表"（Enriched Netlist），包含以下内容：

**3.3.1 器件角色标注**

为每个器件标注其功能角色，例如：

```json
{
  "reference": "C15",
  "value": "100nF",
  "package": "0402",
  "role": "decoupling_cap",
  "belongs_to_module": "MCU_Core",
  "serves_pin": "U1.VDD3",
  "priority": "critical"
}
```

角色类型包括但不限于：core_ic、decoupling_cap、bulk_cap、feedback_resistor、pull_up、pull_down、esd_protection、crystal、load_cap（晶振负载电容）、filter_cap、filter_inductor、current_sense_resistor、voltage_divider、connector、test_point、led_indicator 等。

**3.3.2 网络信号类型标注**

为每个网络标注信号类型和约束：

```json
{
  "net_name": "USB_DP",
  "signal_type": "high_speed_differential",
  "pair_net": "USB_DN",
  "max_length_mm": 50,
  "impedance_ohm": 90,
  "reference_plane": "continuous_ground",
  "routing_layer_preference": "top",
  "sensitivity": "high"
}
```

信号类型包括：power_rail、ground、high_speed_differential、high_speed_single、clock、reset、analog_sensitive、rf、low_speed_digital、i2c、spi、uart、gpio 等。

**3.3.3 模块划分**

这是 Analyzer 最核心的输出。将所有器件划分为功能模块，每个模块包含：

```json
{
  "module_id": "M03",
  "module_name": "3V3_LDO",
  "module_type": "power_linear_regulator",
  "core_component": "U2",
  "components": ["U2", "C8", "C9", "C10", "R5"],
  "component_count": 5,
  "internal_nets": ["NET_VIN_LDO", "NET_VOUT_3V3", "NET_FB_3V3"],
  "external_interface_nets": ["NET_5V", "NET_3V3", "GND"],
  "has_fixed_component": false,
  "layout_template_hint": "ldo_standard",
  "notes": "输入端连接 5V 电源轨，输出 3.3V 供 MCU 和传感器。反馈电阻 R5 必须 Kelvin 连接到 C10 输出端。"
}
```

模块划分的原则：

- 一个模块通常包含 3-15 个器件。过少（如只有 1-2 个）应合并到相关模块；过多（如超过 20 个）应拆分为子模块
- 原理图自带的模块划分仅作参考。常见的需要修正的情况：原理图把 MCU 最小系统拆得太细（boot 电路、复位电路、去耦电容各自成页），应合并为一个"MCU 核心模块"；原理图把整个电源系统放在一页里，应按电压域拆分（5V Buck、3.3V LDO、1.8V LDO 各自成模块）
- 去耦电容归属于它所服务的 IC 所在的模块，而非电源模块
- 每个模块需标注其核心器件（core_component），模块内布局将以核心器件为中心展开

**3.3.4 模块间连接关系图**

描述模块之间的连接关系及其权重：

```json
{
  "from_module": "MCU_Core",
  "to_module": "DDR_Memory",
  "connections": [
    {"net_type": "high_speed_bus", "count": 32, "name": "DDR_DQ[0:31]"},
    {"net_type": "

<cp_artifact title="PCB 多 Agent 自动布局系统 — 分工架构设计（续）" format="markdown">
<!-- 接续上文：3.3.4 模块间连接关系图 -->

```json
{
  "from_module": "MCU_Core",
  "to_module": "DDR_Memory",
  "connections": [
    {"net_type": "high_speed_bus", "count": 32, "name": "DDR_DQ[0:31]"},
    {"net_type": "high_speed_bus", "count": 16, "name": "DDR_A[0:15]"},
    {"net_type": "clock_differential", "count": 1, "name": "DDR_CLK/CLK#"},
    {"net_type": "control", "count": 6, "name": "DDR_CS#/RAS#/CAS#/WE#/CKE/ODT"}
  ],
  "total_weight": 92,
  "placement_constraint": "adjacent_tight",
  "routing_constraint": "length_matched_group"
}
```

权重计算规则：高速差分对/总线每根线权重高（如 ×1.5），普通数字信号权重 ×1.0，电源轨权重 ×0.8（因为可以走内层绕远路），可走背面的信号权重再打折。权重之和决定了两个模块之间的"亲密度"——权重越高，全局布局时两个模块应该越靠近。

**3.3.5 全局约束清单**

汇总所有跨模块的特殊约束：

```json
{
  "constraints": [
    {
      "type": "differential_pair",
      "nets": ["USB_DP", "USB_DN"],
      "modules_involved": ["MCU_Core", "USB_Connector"],
      "impedance_ohm": 90,
      "max_skew_mm": 0.15
    },
    {
      "type": "length_match_group",
      "nets": ["DDR_DQ0", "DDR_DQ1", "...", "DDR_DQ31"],
      "modules_involved": ["MCU_Core", "DDR_Memory"],
      "max_mismatch_mm": 2.0
    },
    {
      "type": "isolation",
      "module_a": "RF_2G4",
      "module_b": "Digital_Core",
      "min_gap_mm": 8.0,
      "reason": "防止数字噪声耦合到射频前端"
    },
    {
      "type": "board_edge_proximity",
      "module": "RF_2G4",
      "requirement": "antenna_pad_at_board_edge",
      "reason": "天线辐射需要净空"
    }
  ]
}
```

**3.3.6 板子评估信息**

```json
{
  "board_category": "mixed_signal_with_rf",
  "complexity": "medium_high",
  "total_components": 187,
  "total_modules": 12,
  "total_nets": 312,
  "critical_signal_count": 48,
  "estimated_difficulty": 7.5,
  "special_concerns": [
    "包含 2.4G 射频模块，需要严格的隔离和阻抗控制",
    "DDR3 总线 32 位宽，等长约束严格",
    "3 个独立电源域，需要注意电源分区和去耦策略"
  ]
}
```

### 3.4 实现要点

Analyzer 的实现分两步：先用传统算法生成初稿，再用 LLM 校正和增强。

第一步，图聚类算法（如 Louvain 算法或谱聚类）基于网表的连通性生成模块划分初稿。算法以器件为节点、网络为边，边权重按共享网络数量和网络类型加权。这一步能快速给出一个"大致合理"的分组。

第二步，LLM 接收图聚类的结果，结合对电路功能的理解进行校正。典型的校正包括：将被错误归入电源模块的去耦电容重新分配到对应 IC 的模块；将原理图中过度拆分的子电路合并；为每个模块命名并标注核心器件；识别信号类型和约束关系。

Analyzer 应支持多轮自检：LLM 生成增强网表后，由一个验证脚本检查格式完整性（每个器件都被分配到了模块、每个模块都有核心器件、所有跨模块连接都被记录），如果有遗漏则反馈给 LLM 补充。

---

## 4. Architect — 总调度官

### 4.1 职责

Architect 是整个系统的指挥中枢。它不直接操作任何器件，而是通过以下方式掌控全局：

- 制定宏观布局策略（功能分区、模块排布方向）
- 分配和调度 Placer、Router、Critic 的工作
- 监控全局状态（通过"地图"），识别瓶颈和冲突
- 决定何时推进到下一阶段、何时回退重做
- 接收各 Agent 的反馈，做出战略级决策

Architect 的角色类似于古代将领看着沙盘指挥战役——它看到的是抽象化的全局态势，而非战场上每一个士兵的位置。

### 4.2 地图系统（The Map）

地图是 Architect 感知世界的核心抽象。它将复杂的 PCB 布局状态压缩为一个 Architect 能在有限上下文中理解的简洁表示。

**地图的构成要素：**

- **板框边界**：板子的外轮廓，定义了地图的"疆域"
- **固定锚点**：用户预先锁定的器件位置（连接器、安装孔等），在地图上标记为不可移动的点
- **模块矩形（行政区）**：每个模块在板面上占据的外接矩形区域。矩形的尺寸由模块内器件的实际排列决定（模块初始化完成后确定，后续可能因 Global Placer 的要求而调整长宽比）
- **模块间连接线**：连接两个模块矩形的加权边，权重反映连接的重要性和数量
- **隔离带**：模块间必须保持的最小间距区域

**地图的文本表示示例：**

```
Board: 100×80mm, 4-layer
Fixed anchors: J1(USB-C) at (5,40), J2(SWD) at (95,10), H1-H4(mounting holes) at corners

Modules (12 total):
  M01 "MCU_Core"      rect(35,10, 30×25mm) status=placed  components=23
  M02 "DDR_Memory"    rect(68,8,  25×20mm) status=placed  components=15
  M03 "3V3_LDO"       rect(12,5,  8×12mm)  status=placed  components=5
  M04 "5V_Buck"       rect(5,5,   12×15mm) status=placed  components=8
  M05 "USB_Interface"  rect(5,33,  10×14mm) status=placed  components=6  [anchored to J1]
  M06 "RF_2G4"        rect(85,55, 12×20mm) status=placed  components=11
  ...

Inter-module connections (top 10 by weight):
  M01↔M02: weight=92 (DDR bus 55 nets, length-matched)
  M01↔M05: weight=34 (USB 2.0 DP/DN differential + control)
  M01↔M06: weight=18 (SPI bus 4 nets)
  M01↔M03: weight=12 (power rail 3V3)
  ...

Isolation requirements:
  M06(RF) ↔ M01(Digital): min gap 8mm, current gap 12mm [OK]
  M04(Buck) ↔ M07(Analog): min gap 5mm, current gap 3mm [VIOLATION]

Overall metrics:
  Board utilization: 68%
  Module overlap: none
  Routability estimate: 0.74 (target ≥ 0.85)
```

这个地图表示大约 300-500 token，完全在 LLM 的舒适处理范围内。Architect 每次决策时都会获取最新的地图快照。

### 4.3 调度逻辑

Architect 的调度不是预编程的状态机，而是 LLM 基于当前地图状态和各 Agent 反馈做出的动态决策。但系统会为 Architect 提供一个"标准流程模板"作为 system prompt 的一部分，Architect 可以遵循也可以偏离：

```
标准流程模板（供 Architect 参考，非强制）：
1. 接收 Analyzer 输出 → 分配 Module Placer
2. 等待所有 Module Placer 完成模块初始化 → 构建地图
3. 分配 Global Placer → 全局排布
4. 调用 Router 验证模块间布线可行性
5. 根据 Router 反馈调度 Placer 修改 → 重复 4-5
6. 调用 Critic 全面评审
7. 根据 Critic 反馈调度 Placer 修改 → 重复 4-7
8. 收敛判定 → 完成
```

Architect 可以在任何时刻偏离模板。例如，如果 Router 反馈"M01 和 M02 之间的 DDR 总线完全走不通"，Architect 可能决定不是微调，而是让 Global Placer 重新排布这两个模块的相对位置，甚至让 Module Placer 重新初始化 M02 的内部布局以改变其长宽比。

### 4.4 Architect 的上下文管理

Architect 的上下文由以下部分构成，按优先级排列：

1. **底层上下文（始终存在）**：Analyzer 的输出摘要（板子类型、复杂度、模块清单、关键约束）+ Architect 自己制定的分工方案。约 800-1200 token。
2. **地图快照（每次决策前刷新）**：当前地图状态。约 300-500 token。
3. **最近反馈（滚动窗口）**：最近 3-5 轮 Agent 反馈的摘要。约 500-1000 token。
4. **历史决策日志（压缩）**：之前做过的重大决策及其结果的简要记录，防止重复犯错。约 200-400 token。

总计约 2000-3000 token 的持续上下文，远低于任何主流 LLM 的上下文窗口限制。

---

## 5. Module Placer — 模块布局器

### 5.1 职责与生命周期

每个功能模块分配一个独立的 Module Placer 实例。Module Placer 的职责是将模块内的器件从初始散乱状态排列为一个紧凑、合理、内部布线友好的布局。

Module Placer 的生命周期：

1. **初始化阶段**：接收 Analyzer 分配的模块信息，完成模块内部的首次布局（模块初始化）
2. **待命阶段**：模块初始化完成后进入待命，等待 Architect 的调整指令
3. **调整阶段**：响应 Architect 转发的 Global Placer / Router / Critic 的修改请求，对模块内部布局进行局部调整
4. **终止**：Architect 宣布布局完成后释放

Module Placer 是可以并行运行的——在模块初始化阶段，所有 Module Placer 同时工作，互不干扰。

### 5.2 状态表示：局部视图

Module Placer 看到的世界只有自己模块内部的信息：

```
Module: "3V3_LDO" (M03)
Type: power_linear_regulator
Template hint: ldo_standard

Components (5):
  U2 (AMS1117-3.3, SOT-223, core): pos=(—), role=LDO_IC
    Key pins: VIN(pin1) at local(-1.1, 0), VOUT(pin3) at local(1.1, 0), GND(pin2/tab)
  C8 (10uF, 0805, input_bulk_cap): pos=(—), serves=U2.VIN
  C9 (100nF, 0402, input_decap): pos=(—), serves=U2.VIN
  C10 (22uF, 0805, output_bulk_cap): pos=(—), serves=U2.VOUT
  R5 (10k/20k divider, 0402, feedback_resistor): pos=(—), serves=U2.ADJ
    Constraint: Kelvin connection to C10 output side

Internal nets:
  NET_VIN_LDO: U2.pin1 — C8.pin1 — C9.pin1
  NET_VOUT_3V3: U2.pin3 — C10.pin1 — R5.pin1
  NET_FB: R5.pin2 — U2.ADJ (if adjustable version)

External interface nets (need to be at module edge):
  NET_5V (from M04 "5V_Buck") → connects to C8/C9 input side → prefer LEFT edge
  NET_3V3 (to M01 "MCU_Core" and others) → connects to C10 output side → prefer RIGHT edge
  GND → handled by copper pour, ignore

Fixed components in this module: none

Module bounding constraint: none (free to determine shape)
```

注意 `pos=(—)` 表示初始化前器件尚未放置。Module Placer 的任务就是为每个器件确定位置。

### 5.3 工具集：原子操作

原子操作是直接映射到 KiCad API 调用的最底层操作。Module Placer 通常不直接调用这些操作，而是通过上层操作间接使用。但在需要精细微调时，Module Placer 可以直接调用。

| 操作名 | 参数 | 说明 |
|--------|------|------|
| `move_component` | ref, x_mm, y_mm | 移动器件到绝对坐标 |
| `move_component_relative` | ref, dx_mm, dy_mm | 相对当前位置平移 |
| `rotate_component` | ref, angle_deg | 设置器件旋转角度（0/90/180/270） |
| `flip_component` | ref | 翻面（F.Cu ↔ B.Cu），当前版本不使用 |
| `swap_components` | ref_a, ref_b | 交换两个器件的位置 |
| `get_component_info` | ref | 查询器件当前位置、朝向、封装尺寸、引脚坐标 |
| `get_clearance` | ref_a, ref_b | 查询两个器件间的最小间距（courtyard 边界） |
| `check_overlap` | ref 或 region | 检查指定器件或区域内是否存在重叠 |

### 5.4 工具集：上层操作（布局 Skills）

上层操作是本系统的核心竞争力。它们将常见的布局模式封装为一键调用的高级操作，让 LLM 不需要逐个器件地迭代，而是直接调用一个 Skill 完成整块布局，效果不好再微调。

上层操作分为两类：**模板型 Skill**（基于已知的最佳实践布局模板）和 **算法型 Skill**（基于传统 EDA 算法的封装）。

#### 5.4.1 模板型 Skill

这些 Skill 封装了特定电路类型的标准布局模式。每个 Skill 内部是一套参数化的放置规则，不需要 LLM 参与计算。

| Skill 名称 | 适用场景 | 内部逻辑 |
|------------|---------|---------|
| `skill_ldo_layout` | 线性稳压器模块 | 输入电容→IC→输出电容 线性排列，反馈电阻 Kelvin 连接到输出电容焊盘，GND 过孔就近打 |
| `skill_buck_layout` | 开关降压电源 | 最小化 VIN→高侧FET→电感→VOUT 的功率环路面积，开关节点铜皮最小化，反馈远离电感 |
| `skill_crystal_layout` | 晶振及负载电容 | 晶振紧贴 MCU 时钟引脚，两颗负载电容对称放置在晶振两侧，周围留净空区 |
| `skill_decap_cluster` | BGA 芯片去耦电容群 | 按电源引脚位置扇形排列去耦电容，每颗电容对准最近的电源引脚，最小化 3D 环路面积 |
| `skill_usb_esd_layout` | USB 接口 + ESD 保护 | ESD 器件紧贴连接器，差分对从连接器→ESD→MCU 保持对称路径 |
| `skill_diff_pair_termination` | 差分对端接电阻 | 端接电阻对称放置在差分对末端，靠近接收端 IC 引脚 |
| `skill_led_indicator` | LED + 限流电阻 | LED 和电阻紧凑排列，LED 朝向统一 |
| `skill_connector_fanout` | 多引脚连接器扇出 | 连接器引脚按信号分组，去耦/滤波器件沿连接器边缘排列 |
| `skill_voltage_divider` | 电阻分压器 | 两颗电阻串联紧凑排列，中间抽头点靠近采样目标 |
| `skill_rc_filter` | RC/LC 滤波器 | 滤波器件按信号流方向串联排列，输入输出端分离 |

每个 Skill 的调用接口示例：

```json
{
  "skill": "skill_ldo_layout",
  "params": {
    "core_ic": "U2",
    "input_caps": ["C8", "C9"],
    "output_caps": ["C10"],
    "feedback_resistors": ["R5"],
    "signal_flow_direction": "left_to_right",
    "external_input_edge": "left",
    "external_output_edge": "right"
  }
}
```

Skill 执行后返回：所有器件的新坐标 + 模块外接矩形尺寸 + 内部布线预评估分数。如果 Module Placer 对结果不满意，可以在 Skill 输出的基础上用原子操作微调。

#### 5.4.2 算法型 Skill

这些 Skill 封装了经典的 EDA 布局算法，用于没有现成模板的通用场景。

| Skill 名称 | 内部算法 | 适用场景 |
|------------|---------|---------|
| `skill_force_directed_place` | 力导向布局算法 | 通用的模块内器件排布，以连接关系为弹簧力，以间距约束为斥力 |
| `skill_simulated_annealing_place` | 模拟退火优化 | 在当前布局基础上做全局优化，跳出局部最优 |
| `skill_align_and_distribute` | 对齐+等间距分布 | 将一组同类器件（如电阻阵列）整齐排列 |
| `skill_compact_module` | 紧凑化算法 | 在保持相对位置关系的前提下，收紧器件间距到最小合法值 |
| `skill_orient_passives_uniform` | 朝向统一化 | 将模块内所有被动元件的朝向统一为 0° 或 90°，选择使飞线交叉最少的方向 |
| `skill_minimize_loop_area` | 3D 环路面积最小化 | 针对电源去耦网络，计算并优化电流环路的三维面积 |
| `skill_pin_escape_check` | BGA 引脚逃逸分析 | 检查 BGA 封装的内层引脚能否成功逃逸，预留过孔空间 |

#### 5.4.3 查询与观测工具

Module Placer 在迭代过程中需要观测当前布局状态来决定下一步操作：

| 工具名 | 返回内容 |
|--------|---------|
| `observe_module_layout` | 当前模块内所有器件的坐标、朝向、外接矩形尺寸 |
| `observe_ratsnest` | 模块内飞线列表（起点、终点、长度、是否交叉） |
| `observe_violations` | 当前模块内的 DRC 违规列表（重叠、间距不足等） |
| `query_pin_distance` | 查询两个引脚之间的直线距离 |
| `query_routing_channel` | 查询两个器件之间的可用布线通道宽度 |
| `trial_route_module` | 调用简易布线器尝试模块内部布线，返回布通率和失败网络 |
| `get_module_bbox` | 获取当前模块的外接矩形尺寸（上报给 Architect 更新地图） |

### 5.5 固定器件处理

如果模块内包含用户预先锁定位置的器件（如 USB 连接器 J1 属于 USB_Interface 模块），Module Placer 的初始化必须以该固定器件为锚点展开布局。具体规则：

- 固定器件的位置和朝向不可修改
- 模块内其他器件围绕固定器件排布
- 模块的外接矩形必须包含固定器件
- 如果固定器件位于板边（连接器通常如此），模块的外部接口方向由固定器件的朝向决定

### 5.6 模块初始化的目标与验收标准

模块初始化完成的标准：

1. 模块内所有器件已放置，无重叠，满足最小间距
2. 关键约束已满足（去耦电容距离、晶振净空、Kelvin 连接等）
3. 模块内部飞线交叉数低于阈值
4. 外部接口网络的焊盘尽量位于模块矩形的边缘，方便后续模块间布线
5. `trial_route_module` 的内部布通率 ≥ 90%

注意：模块初始化阶段，不同模块的器件之间可能存在物理重叠（因为所有模块还没有被全局排布），这些跨模块的 DRC 报错在此阶段忽略。

---

## 6. Global Placer — 全局布局器

### 6.1 职责

Global Placer 的任务是将已完成内部初始化的模块矩形在板面上排布，使得模块间的连接关系得到最优的物理映射。它操作的对象不是单个器件，而是模块矩形。

Global Placer 本质上在解决一个带约束的矩形排列优化问题：在板框内放置 N 个矩形，使得矩形不重叠、满足隔离约束、且加权连接总长度最小。

### 6.2 层级结构

对于简单板子（≤8 个模块），一个 Global Placer 即可处理。

对于复杂板子（>8 个模块），Architect 会将模块分组为若干"区域"（Region），每个区域分配一个 Regional Placer，再由一个顶层 Global Placer 协调区域间的排布。例如：

```
顶层 Global Placer
├── Region A "电源区" → Regional Placer A
│   ├── M03 "3V3_LDO"
│   ├── M04 "5V_Buck"
│   └── M08 "1V8_LDO"
├── Region B "主控区" → Regional Placer B
│   ├── M01 "MCU_Core"
│   ├── M02 "DDR_Memory"
│   └── M09 "Flash_Storage"
└── Region C "接口区" → Regional Placer C
    ├── M05 "USB_Interface"
    ├── M06 "RF_2G4"
    └── M10 "Sensor_Interface"
```

顶层 Global Placer 负责区域间的相对位置；Regional Placer 负责区域内模块间的相对位置。这种层级结构进一步降低了每个 Placer 需要处理的复杂度。

### 6.3 工具集：全局操作

Global Placer 拥有一套专门为模块级操作设计的工具，与 Module Placer 的工具集完全不同。

#### 6.3.1 模块移动与排布操作

| 操作名 | 参数 | 说明 |
|--------|------|------|
| `gp_move_module` | module_id, x_mm, y_mm | 将模块矩形移动到指定位置（模块内所有器件跟随平移） |
| `gp_move_module_relative` | module_id, dx_mm, dy_mm | 相对平移模块 |
| `gp_rotate_module` | module_id, angle(0/90/180/270) | 旋转模块矩形（模块内所有器件跟随旋转） |
| `gp_swap_modules` | module_a, module_b | 交换两个模块的位置 |
| `gp_align_modules` | module_ids[], axis, reference | 将多个模块沿指定轴对齐（左对齐/居中/右对齐/顶对齐/底对齐） |
| `gp_distribute_modules` | module_ids[], axis, spacing | 沿指定轴等间距分布多个模块 |
| `gp_snap_to_anchor` | module_id, anchor_ref | 将模块吸附到固定锚点（连接器）附近 |

#### 6.3.2 模块形状调整操作

| 操作名 | 参数 | 说明 |
|--------|------|------|
| `gp_request_reshape` | module_id, target_aspect_ratio | 请求 Module Placer 调整模块内部布局以改变长宽比（异步操作，需等待 Module Placer 响应） |
| `gp_request_compact` | module_id, direction | 请求 Module Placer 沿指定方向压缩模块尺寸 |
| `gp_request_reorient_interface` | module_id, interface_net, target_edge | 请求 Module Placer 将指定外部接口移到模块矩形的指定边（上/下/左/右） |

这些 `gp_request_*` 操作是 Global Placer 与 Module Placer 之间的协作接口。Global Placer 发出请求后，Architect 将请求转发给对应的 Module Placer，Module Placer 调整内部布局后上报新的模块矩形尺寸，地图随之更新。

#### 6.3.3 全局排布 Skill

| Skill 名称 | 内部算法 | 说明 |
|------------|---------|------|
| `skill_gp_force_directed` | 力导向排布 | 以模块间连接权重为弹簧力，以模块矩形面积为斥力，迭代求解模块位置 |
| `skill_gp_signal_flow_arrange` | 信号流排布 | 按信号流方向（输入→处理→输出）从左到右或从上到下排列模块 |
| `skill_gp_partition_place` | 分区排布 | 先按电气属性（电源/数字/模拟/射频）分区，再在每个分区内排布 |
| `skill_gp_quadrant_assign` | 象限分配 

<cp_artifact title="PCB 多 Agent 自动布局系统 — 分工架构设计（续2）" format="markdown">
<!-- 接续上文：6.3.3 全局排布 Skill 表格中 skill_gp_quadrant_assign 行 -->

| 将板面分为四个象限，根据固定锚点位置和模块间亲密度，将模块分配到最优象限 |
| `skill_gp_resolve_overlap` | 重叠消解 | 当多个模块矩形重叠时，基于最小位移原则将它们推开至不重叠状态 |
| `skill_gp_create_corridor` | 通道创建 | 在两个高连接权重的模块之间强制创建指定宽度的布线通道，推开阻挡的其他模块 |

#### 6.3.4 全局观测工具

| 工具名 | 返回内容 |
|--------|---------|
| `gp_observe_map` | 当前地图快照（所有模块矩形位置、尺寸、间距） |
| `gp_observe_inter_module_ratsnest` | 模块间飞线统计（每对模块之间的飞线数量、总长度、交叉数） |
| `gp_check_overlap` | 检查是否存在模块矩形重叠 |
| `gp_check_board_fit` | 检查所有模块是否都在板框内 |
| `gp_estimate_routability` | 调用粗布线评估器，返回模块间的可布线性分数和瓶颈区域 |
| `gp_query_channel_width` | 查询两个模块之间的实际可用布线通道宽度 |
| `gp_query_module_distance` | 查询两个模块矩形之间的最短距离 |

### 6.4 Global Placer 的状态表示

Global Placer 看到的世界是高度抽象的——只有矩形和连线，没有具体器件：

```
Board: 100×80mm
Fixed anchors: J1 at (5,40), J2 at (95,10)

Module rectangles:
  M01 "MCU_Core"     30×25mm  center=(50, 22)
  M02 "DDR_Memory"   25×20mm  center=(80, 18)
  M03 "3V3_LDO"       8×12mm  center=(16, 11)
  M04 "5V_Buck"      12×15mm  center=(11, 12)
  M05 "USB_Interface" 10×14mm  center=(10, 40)  [anchored: J1]
  M06 "RF_2G4"       12×20mm  center=(91, 65)
  ...

Connection weights (sorted):
  M01↔M02: 92  (must be adjacent, right side of M01)
  M01↔M05: 34  (USB, moderate distance OK)
  M01↔M06: 18  (SPI, can route through inner layers)
  M04↔M03: 15  (power cascade, 5V→3.3V)
  ...

Constraints:
  M06 must be at board edge (antenna)
  M06 ↔ M01 gap ≥ 8mm
  M04 ↔ M07 gap ≥ 5mm
```

这个表示大约 300-400 token，Global Placer 可以轻松处理。

### 6.5 与 Module Placer 的协作机制

Global Placer 和 Module Placer 之间存在双向通信，但不直接对话，而是通过 Architect 中转：

**Global → Module 方向（形状调整请求）：**

当 Global Placer 发现某个模块的当前形状不利于全局排布时（比如一个模块太宽，挡住了两个高权重模块之间的通道），它向 Architect 发出 reshape 请求。Architect 将请求转发给对应的 Module Placer。Module Placer 尝试在满足内部约束的前提下调整长宽比，完成后上报新的模块矩形尺寸。如果 Module Placer 无法满足要求（比如核心 IC 的封装本身就很宽，无法压缩），它会上报失败原因，Architect 需要寻找替代方案。

**Module → Global 方向（尺寸变更通知）：**

当 Module Placer 在调整阶段修改了内部布局导致模块矩形尺寸变化时，新的矩形尺寸自动更新到地图中，Global Placer 在下次观测时会看到变化。

---

## 7. Router — 布线验证器

### 7.1 职责

Router 不是一个 LLM Agent，而是一个由 LLM 驱动的工具调度层。Router 的核心职责是评估当前布局的可布线性，定位布线瓶颈，并生成结构化的问题报告和修改建议。

Router 内部封装了多种布线验证算法，由 Router 的 LLM 部分根据 Architect 的指令选择合适的算法组合。

### 7.2 布线验证模式

Router 支持三种验证模式，复杂度和精度递增：

**模式 A：飞线分析（最快，秒级）**

不实际布线，仅基于飞线（Ratsnest）进行统计分析。计算内容包括：模块间飞线总长度、飞线交叉数量、局部拥塞热力图、通道容量与需求的比值。适用于全局布局的快速迭代阶段，每次 Global Placer 调整后都可以跑一次。

**模式 B：粗布线评估（中等，十秒级）**

调用全局布线器（Global Router）进行通道级别的布线规划，不生成实际走线，但评估每个通道的利用率和瓶颈。能够发现"这个通道理论上需要走 32 根线但物理上只能容纳 20 根"这类问题。适用于全局布局基本稳定后的验证。

**模式 C：实际布线验证（最慢，分钟级）**

调用详细布线器（如 KiCad 内置布线器或 FreeRouting）进行实际布线尝试。只布模块间的连接线，不布模块内部的线（模块内部已由 Module Placer 通过 `trial_route_module` 验证过）。布线时，模块矩形的正面区域被标记为禁布区（因为模块内部的正面走线已经占据了这些空间）。背面和内层不受此限制。

布线完成后，Router 统计布通率、失败网络列表、DRC 违规，并生成详细报告。

### 7.3 磁力场评估模型（Force-Field Evaluation）

这是 Router 内部的核心评估算法，用于量化当前布局下模块间连接的"舒适度"。

**基本原理：**

将每条模块间的飞线视为一根弹簧，弹簧的劲度系数（即"磁力"）由信号类型决定。所有弹簧的总势能反映了布局的全局质量；局部势能的异常高值指示了问题区域。

**磁力权重分配：**

| 信号类型 | 正面布线磁力 | 背面/内层布线磁力 | 说明 |
|---------|------------|----------------|------|
| 高速差分对 | 极强 (×3.0) | 强斥力 (×-2.0) | 差分对必须走正面短路径，走背面会引入过孔破坏阻抗连续性 |
| 时钟信号 | 强 (×2.5) | 弱斥力 (×-0.5) | 时钟线需要短且参考平面连续，尽量避免换层 |
| 高速单端总线 | 强 (×2.0) | 中性 (×0.5) | 可以走内层但有长度代价 |
| 模拟敏感信号 | 强 (×2.0) | 斥力 (×-1.0) | 模拟信号换层会引入噪声耦合风险 |
| SPI/I2C 等中速总线 | 中 (×1.0) | 中 (×0.8) | 较灵活，可走内层 |
| 电源轨 | 弱 (×0.5) | 强 (×1.5) | 电源线走内层铜皮是常规做法，甚至更优 |
| 普通 GPIO | 弱 (×0.5) | 中 (×0.8) | 最灵活，怎么走都行 |
| GND | 忽略 (×0) | 忽略 (×0) | 铺铜处理，不参与评估 |

**势能计算：**

对于每条模块间飞线 $i$，其势能为：

$$E_i = w_i \cdot f(d_i)$$

其中 $w_i$ 是该飞线的磁力权重，$d_i$ 是飞线长度（两个连接焊盘之间的直线距离），$f(d)$ 是距离惩罚函数。对于正面布线偏好的信号，$f(d) = d^2$（二次惩罚，距离越远惩罚急剧增加）；对于可走内层的信号，$f(d) = d$（线性惩罚，距离远一些也可接受）。

系统总势能 $E_{total} = \sum_i E_i$，归一化后得到 0-1 的评分。

**局部异常检测：**

将板面划分为网格（如 5mm×5mm），计算每个网格单元内穿过的飞线的势能密度。势能密度显著高于平均值的网格被标记为"热点"（Hotspot），Router 会在报告中指出这些热点的位置、涉及的模块和信号，以及建议的修改方向。

**磁力场评估的输出示例：**

```
Force-Field Evaluation Report:
  Total energy score: 0.68 (target ≥ 0.80)
  
  Hotspots (3 detected):
    1. Region (45-55mm, 15-25mm) — energy density 3.2× average
       Cause: DDR_DQ[0:15] (M01→M02) and SPI_bus (M01→M06) converge
       Suggestion: move M06 further from M01-M02 corridor, or rotate M01 
       so SPI pins face away from DDR side
       
    2. Region (8-15mm, 35-45mm) — energy density 2.1× average
       Cause: USB_DP/DN (M05→M01) forced to route around M04 "5V_Buck"
       Suggestion: swap M04 and M03 positions, or move M04 above M05
       
    3. Region (80-90mm, 50-60mm) — energy density 1.8× average
       Cause: RF SPI lines (M01→M06) too long, high weight due to 
       analog sensitivity
       Suggestion: acceptable if routed on inner layer with ground guard
  
  Differential pair status:
    USB_DP/DN: path length ~35mm, moderate [OK if routed carefully]
    DDR_CLK/CLK#: path length ~12mm, good [OK]
  
  Recommended priority: Fix hotspot #1 first (DDR routing is critical)
```

### 7.4 Router 的严格度调节

Architect 可以指定 Router 的评估严格度：

- **严格模式**：所有信号类型都按最高标准评估，差分对必须正面短路径，普通信号也要求较短路径。适用于高性能板子或最终验证阶段。
- **标准模式**：差分对和高速信号严格评估，普通信号宽松。适用于大多数迭代阶段。
- **宽松模式**：只检查差分对和时钟等关键信号，普通信号只要能布通就行。适用于全局布局的早期探索阶段，避免过早陷入细节优化。

---

## 8. Critic — 评审员

### 8.1 职责

Critic 是系统的质量守门人。它的任务是从"资深工程师评审"的视角，检查当前布局是否存在功能性、性能性或工艺性问题。Critic 不直接修改布局，只输出问题清单。

与 Router 侧重于"能不能布通"不同，Critic 侧重于"布局本身的质量"——即使布线能走通，布局也可能存在 EMC 隐患、热管理问题、可制造性缺陷等。

### 8.2 双层检查机制

**Fast Check（规则引擎层，自动触发）：**

每次 Placer 执行操作后自动运行，不经过 LLM，纯规则引擎，毫秒级完成。检查内容：

- 器件重叠（courtyard 交叉）
- 器件超出板框
- 最小间距违规
- 去耦电容距离超限（>阈值则报警）
- 器件旋转角度非正交（非 0°/90°/180°/270°）

Fast Check 的结果直接返回给 Placer，不经过 Architect。如果发现 Critical 级违规（如重叠），该操作被拒绝，Placer 必须重新生成动作。

**Deep Review（LLM 驱动层，由 Architect 触发）：**

在关键节点由 Architect 主动触发，LLM 按照领域知识库中的检查清单逐项审查。Deep Review 的 LLM 不需要一次性看到整个板子的所有信息，而是按检查项按需查询。

Deep Review 的执行流程：

1. Architect 触发 Deep Review，告知 Critic 当前板子类型和阶段
2. Critic 根据板子类型加载对应的检查清单（Skills）
3. Critic 按清单逐项检查，每项检查时调用对应的查询工具获取所需信息
4. 汇总所有发现的问题，按严重级别排序，输出问题清单

### 8.3 领域知识库（Skills）

Critic 的检查能力来自于预置的领域知识库。每种板子类型对应一套检查清单，检查清单中的每一项都包含：检查目标、检查方法（调用哪个工具、看哪些数据）、判定标准、严重级别。

**通用检查项（所有板子类型都检查）：**

| 检查项 | 级别 | 检查方法 |
|--------|------|---------|
| 去耦电容位置 | Critical | 查询每个 IC 的电源引脚与对应去耦电容的距离，超过阈值报警 |
| 参考平面连续性 | Critical | 检查高速信号走线下方的参考平面是否存在间隙或分割 |
| 晶振放置 | Critical | 检查晶振与 MCU 时钟引脚的距离、周围净空区 |
| 器件板边安全距离 | Major | 检查所有器件到板边的最小距离 |
| 差分对对称性 | Major | 检查差分对两端的器件是否对称放置 |
| 散热器件隔离 | Major | 检查大功率器件（DCDC 电感、功率 MOSFET）与敏感器件的距离 |
| 器件朝向一致性 | Minor | 检查同类器件（IC pin1 方向、极性元件方向）的朝向是否统一 |
| 丝印可读性 | Minor | 检查参考编号是否被过孔或其他器件遮挡 |
| 光学定位点 | Minor | 检查是否存在 Fiducial 标记 |

**电源板附加检查项：**

| 检查项 | 级别 | 检查方法 |
|--------|------|---------|
| 开关节点环路面积 | Critical | 计算 DCDC 的 VIN-FET-L-VOUT 环路的 3D 面积 |
| 反馈走线路径 | Critical | 检查反馈走线是否经过开关电感下方或开关节点附近 |
| 输入输出电容接地 | Major | 检查电容接地是否通过多过孔短路径连接到地平面 |

**射频板附加检查项：**

| 检查项 | 级别 | 检查方法 |
|--------|------|---------|
| 天线净空区 | Critical | 检查天线辐射区下方所有层是否净空 |
| 射频走线屏蔽过孔 | Critical | 检查射频走线两侧的缝合过孔间距是否满足 λ/20 要求 |
| 射频与数字隔离距离 | Major | 检查射频模块与数字模块的物理间距 |
| 阻抗匹配网络紧凑性 | Major | 检查匹配网络器件间距是否过大引入寄生参数 |

**混合信号板附加检查项：**

| 检查项 | 级别 | 检查方法 |
|--------|------|---------|
| 模拟/数字分区 | Critical | 检查模拟区和数字区是否存在物理分区，是否有数字走线穿越模拟区 |
| 星型接地点 | Critical | 检查模拟地和数字地的连接点是否唯一且位于 ADC 芯片下方 |
| 小信号走线隔离 | Major | 检查毫伏级模拟信号走线与高频数字信号的距离 |

### 8.4 问题清单格式

Critic 输出的问题清单是结构化的，便于 Architect 解析和分派：

```json
{
  "review_timestamp": "2026-02-07T14:30:00",
  "board_type": "mixed_signal_with_rf",
  "total_issues": 7,
  "critical": 2,
  "major": 3,
  "minor": 2,
  "issues": [
    {
      "id": "CR-001",
      "severity": "critical",
      "category": "decoupling",
      "description": "C15 (100nF decap for U1.VDD3) is 3.2mm from U1.VDD3 pin, exceeds 1.5mm threshold",
      "affected_module": "MCU_Core",
      "affected_components": ["C15", "U1"],
      "suggestion": "Move C15 closer to U1 pin 45 (VDD3), target distance < 1.5mm",
      "fix_agent": "module_placer_M01"
    },
    {
      "id": "CR-002",
      "severity": "critical",
      "category": "antenna_clearance",
      "description": "Antenna keep-out zone of M06 overlaps with M10 sensor module. Copper pour under antenna area will detune the antenna.",
      "affected_module": "RF_2G4",
      "affected_components": ["ANT1"],
      "suggestion": "Move M10 at least 5mm away from antenna radiation area, or relocate M06 to board corner",
      "fix_agent": "global_placer"
    },
    {
      "id": "MJ-001",
      "severity": "major",
      "category": "thermal",
      "description": "U3 (DCDC buck, estimated 1.2W dissipation) is adjacent to U1 (MCU, thermal sensitive). No thermal gap.",
      "affected_module": "5V_Buck",
      "suggestion": "Insert at least 3mm gap between M04 and M01, or add thermal relief vias under U3",
      "fix_agent": "global_placer"
    }
  ]
}
```

### 8.5 Critic 的触发时机

Critic Deep Review 不是每一步都触发，而是在以下节点由 Architect 调用：

1. **模块初始化完成后**：轻量检查，只检查各模块内部的 Critical 项（去耦电容距离、晶振位置等），不检查全局项
2. **全局布局完成后**：全面检查，包括分区隔离、天线净空、热管理等全局项
3. **Router 验证通过后**：最终检查，包括所有项目（含 Minor 级别的丝印、朝向等）
4. **每轮迭代修改后**：针对性检查，只检查与本轮修改相关的项目

---

## 9. 系统工作流程

### Phase 0：语义分析

```
触发条件：用户启动自动布局
执行者：Analyzer
输入：KiCad 工程文件（网表 + 原理图层级 + 板框 + 固定器件）
输出：增强网表（模块划分、信号标注、约束清单、板子评估）
耗时预估：30-60 秒（1-3 轮 LLM 调用 + 图聚类算法）
```

详细步骤：

1. 从 KiCad 工程中提取原始网表、器件列表、原理图层级结构
2. 图聚类算法生成模块划分初稿
3. LLM 校正模块划分（合并过细的模块、拆分过粗的模块、修正去耦电容归属）
4. LLM 标注每个器件的功能角色、每个网络的信号类型
5. LLM 生成模块间连接权重和全局约束清单
6. 验证脚本检查增强网表的完整性，如有遗漏则反馈 LLM 补充
7. 输出最终的增强网表，传递给 Architect

### Phase 1：模块初始化

```
触发条件：Analyzer 输出完成
执行者：Architect（调度）+ 全部 Module Placer（并行执行）
输入：增强网表中每个模块的信息
输出：每个模块的内部布局完成，模块矩形尺寸确定
耗时预估：1-5 分钟（取决于模块数量和复杂度，并行执行）
```

详细步骤：

1. Architect 接收增强网表，为每个模块分配一个 Module Placer 实例
2. Architect 向每个 Module Placer 下发模块信息（器件列表、内部网表、角色标注、约束、模板提示）
3. 所有 Module Placer 并行工作：
   a. 如果模块有模板提示（如 `ldo_standard`），优先调用对应的模板型 Skill 一键生成初始布局
   b. 如果没有模板，调用 `skill_force_directed_place` 生成初始布局
   c. 在初始布局基础上，LLM 审视结果，通过原子操作或算法型 Skill 进行微调
   d. 调用 `trial_route_module` 验证内部布通率
   e. 调用 `observe_violations` 检查内部 DRC
   f. 迭代直到满足验收标准（内部布通率 ≥ 90%，无 Critical 违规）
4. 对于包含固定器件的模块，Module Placer 以固定器件为锚点展开布局
5. 每个 Module Placer 完成后，上报模块矩形尺寸给 Architect
6. Architect 收集所有模块矩形，构建初始地图
7. **轻量 Critic 检查**：对每个模块内部的 Critical 项进行快速检查（去耦电容距离、晶振位置等），发现问题则通知对应 Module Placer 修复

### Phase 2：全局布局

```
触发条件：所有模块初始化完成，地图构建完毕
执行者：Architect（调度）+ Global Placer（执行）
输入：地图（板框 + 模块矩形 + 固定锚点 + 模块间连接权重）
输出：所有模块在板面上的位置确定，无重叠，满足隔离约束
耗时预估：2-10 分钟
```

详细步骤：

1. Architect 根据板子复杂度决定 Global Placer 的层级结构（单层 or 分区域）
2. Global Placer 首先调用 `skill_gp_signal_flow_arrange` 或 `skill_gp_partition_place` 生成初始全局排布
3. 处理固定锚点约束：包含固定器件的模块必须放置在锚点附近，其他模块围绕它们排布
4. 调用 `skill_gp_resolve_overlap` 消解重叠
5. Global Placer 审视结果，通过 `gp_move_module`、`gp_rotate_module` 等操作迭代优化
6. 每轮调整后调用 `gp_estimate_routability` 快速评估可布线性
7. 如果发现某个模块的形状不利于全局排布，通过 Architect 向对应 Module Placer 发出 reshape 请求
8. Module Placer 调整内部布局后上报新的矩形尺寸，地图更新
9. 迭代直到：无重叠、满足所有隔离约束、可布线性评分达到阈值

### Phase 3：迭代精调

```
触发条件：全局布局完成
执行者：Architect（调度）+ Router + Critic + Placer 集群（按需）
输入：当前完整布局状态
输出：布局质量持续提升，直到收敛
耗时预估：5-30 分钟（取决于问题数量和复杂度）
```

这是整个系统最核心也最复杂的阶段。它是一个自由迭代循环，没有固定的步骤序列，由 Architect 根据实时状态动态决策。

典型的迭代循环：

```
Architect 调用 Router（模式 B：粗布线评估）
  → Router 返回报告：3 个热点，DDR 通道拥塞，USB 差分对路径过长
  
Architect 分析报告，制定修改计划：
  → 任务 1：Global Placer 将 M02(DDR) 向右移 3mm，拓宽 DDR 通道
  → 任务 2：Module Placer M05 调整内部布局，将 USB 差分对焊盘移到靠近 M01 的边
  
Global Placer 执行任务 1 → 地图更新
Module Placer M05 执行任务 2 → 模块矩形可能变化 → 地图更新

Architect 再次调用 Router（模式 B）
  → Router 返回：DDR 通道 OK，USB 路径改善，但 M04 和 M03 间距不足
  
Architect 制定新计划：
  → 任务 3：Global Placer 调整 M04 位置
  
... 循环 ...

Router 报告无 Critical 热点，可布线性评分 ≥ 0.85
  → Architect 调用 Router（模式 C：实际布线验证）
  → Router 返回：布通率 97%，3 条 net 未布通（均为低优先级 GPIO）
  → Architect 判断可接受，进入 Critic 评审

Architect 调用 Critic Deep Review
  → Critic 返回问题清单：1 Critical + 2 Major + 3 Minor
  
Architect 处理 Critical 问题：
  → 分派给对应 Module Placer 修复
  
修复后再次调用 Router 验证 + Critic 复查
  → 无 Critical，1 Major（可接受），3 Minor
  
Architect 判断收敛，进入 Phase 4
```

**迭代精调阶段的关键规则：**

- Router 的严格度随迭代推进逐步

<cp_artifact title="PCB 多 Agent 自动布局系统 — 分工架构设计（续3）" format="markdown">
<!-- 接续上文：Phase 3 迭代精调阶段的关键规则 -->

- Router 的严格度随迭代推进逐步收紧：早期用宽松模式快速探索，中期用标准模式精调，后期用严格模式做最终验证
- Architect 维护一个"修改历史栈"，记录每轮迭代的修改内容和效果。如果某个修改导致整体评分下降，Architect 可以决定回滚
- 单个问题的修复尝试不超过 3 次。如果 Module Placer 连续 3 次无法解决某个问题，Architect 将问题升级为全局问题，交给 Global Placer 从更高层面解决（比如调整模块间的相对位置）
- 如果 Global Placer 也无法解决，Architect 可以决定让对应的 Module Placer 重新初始化模块内部布局（二次初始化），以全新的内部排列方式适应全局约束

**二次初始化机制：**

全局布局确定后，某些模块的外部接口方向可能与初始化时的假设不同。例如，模块初始化时假设输入从左侧进入，但全局排布后该模块的左侧紧贴板边，输入实际需要从上方进入。此时 Architect 会指示 Module Placer 进行二次初始化：保持核心器件位置不变，但重新调整外围器件的排列方向，使外部接口焊盘朝向正确的方向。

二次初始化不是从零开始，而是在现有布局基础上做方向性调整。Module Placer 可以调用 `skill_force_directed_place` 以新的接口方向约束重新优化，或者手动调整关键器件的位置。

### Phase 4：最终验证与收尾

```
触发条件：Architect 判断迭代收敛
执行者：Architect（调度）+ Critic（最终评审）+ 收尾脚本
输入：当前布局
输出：最终的 .kicad_pcb 文件
耗时预估：1-3 分钟
```

详细步骤：

1. Architect 调用 Critic 进行最终 Deep Review（包含所有级别的检查项，含 Minor）
2. 如果存在 Critical 问题，必须修复后重新验证（回到 Phase 3）
3. 如果只有 Major 和 Minor 问题，Architect 评估是否值得继续修复：
   - Major 问题如果修复成本高（需要大幅调整全局布局）且风险可控，可以标记为"已知问题"留给人工处理
   - Minor 问题中的朝向统一、丝印整理等，由收尾脚本自动处理
4. 收尾脚本执行：
   - `skill_orient_passives_uniform`：统一所有被动元件朝向
   - 丝印位置自动调整：确保所有参考编号可见且不被遮挡
   - 删除布线验证阶段产生的临时走线（如果有）
   - 更新铜区填充（Refill All Zones）
5. 最终 DRC 检查（调用 KiCad 内置 DRC）
6. 保存文件
7. 生成布局报告（包含：模块清单、关键约束满足情况、已知问题列表、布局质量评分）

---

## 10. Agent 间通信协议

### 10.1 消息格式

所有 Agent 间的通信通过统一的消息格式进行。消息不直接在 Agent 之间传递，而是通过 Architect 中转（Architect 是唯一的消息枢纽）。

```json
{
  "msg_id": "msg_20260207_143012_001",
  "from": "router",
  "to": "architect",
  "type": "report",
  "priority": "high",
  "payload": {
    "report_type": "routing_verification",
    "mode": "B",
    "routability_score": 0.72,
    "hotspots": [...],
    "failed_nets": [...],
    "suggestions": [...]
  }
}
```

消息类型包括：

| 类型 | 方向 | 说明 |
|------|------|------|
| `task_assign` | Architect → Placer/Router/Critic | 分配任务 |
| `task_complete` | Placer/Router/Critic → Architect | 任务完成，附带结果 |
| `task_failed` | Placer → Architect | 任务执行失败，附带原因 |
| `report` | Router/Critic → Architect | 验证/评审报告 |
| `reshape_request` | Architect → Module Placer | 请求调整模块形状（源自 Global Placer） |
| `reshape_response` | Module Placer → Architect | 形状调整结果 |
| `map_update` | Placer → Architect | 模块矩形尺寸变更通知 |
| `status_query` | Architect → any | 查询 Agent 当前状态 |
| `escalation` | Placer → Architect | 问题升级，请求更高层面的决策 |

### 10.2 升级与回退机制

系统定义了清晰的问题升级路径：

```
Module Placer 内部微调（3 次尝试）
  → 失败 → 升级到 Architect
    → Architect 指派 Global Placer 调整模块间位置
      → 失败 → Architect 指派 Module Placer 二次初始化
        → 失败 → Architect 指派 Global Placer 重新全局排布
          → 失败 → Architect 报告人工干预需求，输出当前最佳布局 + 问题清单
```

每一级升级都意味着更大范围的修改和更高的时间成本。Architect 在决定升级时会权衡：问题的严重性 vs. 升级的成本。对于 Minor 问题，通常不会升级超过第一级。

回退机制：系统利用 KiCad 的 Commit 事务机制，每个重要操作节点都创建一个检查点。如果某轮迭代导致整体质量下降，Architect 可以回滚到上一个检查点重新尝试不同的策略。

```python
# 检查点管理示例
commit = board.begin_commit()
try:
    # 执行一系列修改操作
    ...
    board.push_commit(commit, message="Phase3_iteration_5")
except:
    board.drop_commit(commit)  # 回滚
```

### 10.3 并发控制

系统中存在两种并发场景：

**场景 1：模块初始化阶段的并行**

所有 Module Placer 同时工作，各自操作不同的器件，互不干扰。由于此阶段不关心跨模块的 DRC，不存在冲突。实现方式：每个 Module Placer 独立调用 KiCad API 操作自己模块内的器件，操作完成后统一提交。

**场景 2：迭代精调阶段的串行协调**

此阶段 Global Placer 和 Module Placer 可能同时需要修改布局，存在潜在冲突（比如 Global Placer 移动了模块位置，同时 Module Placer 在调整模块内部布局）。为避免冲突，迭代精调阶段采用 **Architect 串行调度**：Architect 每次只激活一个 Placer 执行任务，等待其完成后再激活下一个。虽然牺牲了并行性，但保证了状态一致性。

例外：如果两个 Module Placer 修改的是完全不相关的模块（物理上不相邻、没有共享约束），Architect 可以判断它们可以并行执行。

---

## 11. 工程细节备忘

以下是在实现过程中需要注意的工程细节，它们不属于架构层面的设计，但会显著影响系统的实际效果。

### 11.1 GND 网络处理

GND 网络通过铺铜（Copper Pour）实现连接，因此：

- Analyzer 在标注网络类型时，将 GND 标记为 `ground_pour`，不纳入模块间连接权重计算
- Module Placer 在内部布局时不考虑 GND 飞线，但需要确保 GND 焊盘附近有足够空间打过孔连接到地平面
- Router 在布线验证时忽略 GND 网络的飞线
- 磁力场评估模型中 GND 的权重为 0

### 11.2 电源平面处理

对于使用内层电源平面的设计（如 4 层板的 L2 为 GND、L3 为 VCC）：

- 电源轨的连接主要通过内层平面 + 过孔实现，不需要正面走线
- Router 在评估电源网络时，主要检查过孔位置是否合理，而非走线路径
- Module Placer 在放置去耦电容时，需要确保电容焊盘到电源平面的过孔路径最短

### 11.3 热焊盘（Exposed Pad）处理

QFN、PowerPAD 等封装的底部散热焊盘需要特殊处理：

- Module Placer 需要为散热焊盘预留过孔阵列空间（通常 3×3 或 4×4 的过孔矩阵）
- 散热焊盘的过孔连接到内层地平面或散热铜皮
- Critic 检查散热焊盘是否有足够的过孔和铜皮面积

### 11.4 测试点处理

如果板子需要测试点（Test Point）：

- Analyzer 将测试点器件标记为 `test_point` 角色
- 测试点通常不归入功能模块，而是在 Phase 4 收尾阶段由脚本自动放置在对应网络的空闲区域
- 或者由 Critic 在评审时检查关键网络是否有可探测的测试点

### 11.5 拼板与工艺边

如果设计需要拼板（Panelization）：

- 板框外的工艺边（Break-away Tab）区域不在本系统的处理范围内
- 但 Critic 需要检查板边附近的器件是否满足 V-Cut 或邮票孔的安全距离

### 11.6 层叠感知

Module Placer 和 Router 的决策需要感知板子的层叠结构：

- 2 层板：正面和背面都是信号层，布线空间有限，Module Placer 需要更紧凑的布局
- 4 层板：通常 L1=信号、L2=GND、L3=电源、L4=信号，高速信号优先走 L1 以 L2 为参考平面
- 6+ 层板：更多布线层可用，Module Placer 可以适当放松紧凑度要求

层叠信息从 KiCad 的 `board.get_stackup()` 获取，作为全局配置传递给所有 Agent。

### 11.7 封装朝向约定

为了可制造性（DFM），系统遵循以下朝向约定：

- IC 类器件：pin 1 统一朝向左上角（0° 放置时）
- 极性被动元件（电解电容、二极管）：正极/阳极统一朝向一个方向
- 非极性被动元件（电阻、MLCC）：统一 0° 或 90°，同一模块内保持一致
- 连接器：朝向板边

这些约定在 Module Placer 的 Skill 中内置，在 Critic 的 Minor 检查项中验证。

---

## 12. 收敛判定与终止条件

### 12.1 各阶段的收敛标准

| 阶段 | 收敛标准 | 最大迭代次数 |
|------|---------|-------------|
| Phase 1 模块初始化 | 每个模块：内部无重叠、关键约束满足、内部布通率 ≥ 90% | 每个模块 10 轮 |
| Phase 2 全局布局 | 无模块重叠、满足隔离约束、可布线性评分 ≥ 0.70 | 20 轮 |
| Phase 3 迭代精调 | Router 模式 C 布通率 ≥ 95%、Critic 无 Critical 问题 | 30 轮 |
| Phase 4 最终验证 | DRC 通过（忽略未布线的 DRC）、Critic 无 Critical | 3 轮 |

### 12.2 全局终止条件

系统在以下任一条件满足时终止：

1. **成功终止**：Phase 4 验证通过，输出最终布局文件
2. **超时终止**：总运行时间超过预设上限（如 60 分钟），输出当前最佳布局 + 未解决问题清单
3. **收敛失败终止**：连续 5 轮迭代整体质量评分无提升，判定为陷入局部最优，输出当前布局 + 建议人工干预的问题清单
4. **不可解终止**：Architect 判断当前板框尺寸无法容纳所有模块（面积利用率 > 95% 且存在不可消解的重叠），报告需要增大板框或减少器件

### 12.3 质量评分体系

系统维护一个综合质量评分（0-100），由以下维度加权构成：

| 维度 | 权重 | 评估方法 |
|------|------|---------|
| 可布线性 | 30% | Router 磁力场评分 + 实际布通率 |
| 约束满足度 | 25% | 关键约束（去耦距离、隔离间距、差分对称性等）的满足比例 |
| 空间效率 | 15% | 板面利用率（不能太低浪费空间，也不能太高导致拥塞） |
| 信号完整性预评估 | 15% | 高速信号路径长度、参考平面连续性、环路面积 |
| 可制造性 | 10% | 器件朝向一致性、板边安全距离、丝印可读性 |
| 热管理 | 5% | 大功率器件间距、散热路径通畅性 |

---

## 13. 开放问题与后续讨论

以下问题在当前架构中尚未完全确定，需要在详细设计阶段进一步讨论：

### 13.1 LLM 选型与成本控制

不同 Agent 对 LLM 能力的要求不同：

- Analyzer 和 Critic 需要强大的知识理解和推理能力，适合使用顶尖模型（Claude Opus / GPT-4o）
- Architect 需要较强的规划和决策能力，适合使用顶尖模型
- Module Placer 的每次调用相对简单（选择一个工具并提供参数），可以考虑使用较轻量的模型（Claude Sonnet / GPT-4o-mini）以降低成本和延迟
- Global Placer 介于两者之间

一块中等复杂度的板子（12 个模块、200 个器件），预估需要 100-300 次 LLM 调用。如果全部使用顶尖模型，成本可能在 $5-15 之间。通过对 Placer 使用轻量模型，可以降低到 $2-5。

### 13.2 模板库的构建与扩展

模板型 Skill 的质量直接决定了模块初始化的效率和效果。初期需要人工构建核心模板（LDO、Buck、晶振、USB 等 10-15 种常见电路），后续可以考虑：

- 从开源 PCB 设计中自动提取布局模板
- 让系统在成功完成布局后，将新的布局模式保存为模板
- 用户可以上传自己的布局模板供系统使用

### 13.3 磁力场模型的参数标定

磁力权重表中的具体数值（×3.0、×2.5 等）需要通过实验标定。可能的方法：

- 收集一批高质量的人工布局作为参考，反向拟合权重参数
- 让资深硬件工程师对不同布局方案打分，用评分数据训练权重
- 先用经验值启动，在实际使用中根据 Critic 的反馈逐步调整

### 13.4 与现有 EDA 工具的集成深度

当前架构基于 KiCad 9.0 的 Python API（kipy）。需要评估的集成问题：

- KiCad 内置自动布线器的能力是否足够，还是需要集成 FreeRouting 等外部布线器
- 是否需要集成信号完整性仿真工具（如 OpenEMS）做更精确的 SI/PI 评估
- KiCad API 的性能瓶颈：频繁的 `get_footprints()` / `update_items()` 调用在大型板子上的延迟

### 13.5 多面贴装的扩展

当前版本仅支持单面贴装。未来扩展到双面贴装时需要考虑：

- Module Placer 需要决定哪些器件放在背面
- Global Placer 需要同时管理正面和背面的模块排布
- 正背面器件的对位关系（避免正背面大型器件重叠导致回流焊问题）
- Critic 需要增加双面贴装相关的检查项

### 13.6 用户交互与中间干预

当前设计是全自动流程，用户只在开始时提供输入、结束时获取输出。后续可以考虑：

- 在 Phase 2（全局布局）完成后暂停，让用户确认模块排布方向是否符合预期
- 允许用户在任何阶段暂停、手动调整部分布局、然后让系统继续
- 提供实时的进度可视化（在 KiCad 中实时看到器件被移动）

---

## 附录 A：系统架构总览图（文本版）

```
用户输入                                    最终输出
  │                                           ▲
  ▼                                           │
┌─────────────────────────────────────────────────────────────┐
│                        Phase 0                               │
│  ┌──────────┐    原始网表     ┌──────────────┐              │
│  │ KiCad    │───────────────→│   Analyzer    │              │
│  │ 工程文件  │    原理图层级   │  (LLM Agent)  │              │
│  └──────────┘               └──────┬───────┘              │
│                                     │ 增强网表              │
├─────────────────────────────────────┼───────────────────────┤
│                        Phase 1      ▼                        │
│                    ┌────────────────────┐                    │
│                    │     Architect      │                    │
│                    │    (LLM Agent)     │                    │
│                    └────────┬───────────┘                    │
│                  分配任务    │                                │
│          ┌─────────┼─────────┼──────────┐                   │
│          ▼         ▼         ▼          ▼                   │
│    ┌─────────┐┌─────────┐┌─────────┐┌─────────┐           │
│    │Module   ││Module   ││Module   ││Module   │  ...       │
│    │Placer   ││Placer   ││Placer   ││Placer   │           │
│    │M01      ││M02      ││M03      ││M04      │           │
│    └────┬────┘└────┬────┘└────┬────┘└────┬────┘           │
│         │          │          │          │                   │
│         └──────────┴──────┬───┴──────────┘                  │
│                           │ 模块矩形尺寸                     │
│                           ▼                                  │
│                    ┌──────────────┐                          │
│                    │   地图构建    │                          │
│                    └──────┬───────┘                          │
├───────────────────────────┼──────────────────────────────────┤
│                  Phase 2  ▼                                   │
│                    ┌────────────────────┐                     │
│                    │     Architect      │                     │
│                    │    (看地图决策)     │                     │
│                    └────────┬───────────┘                     │
│                             │                                 │
│                    ┌────────▼───────────┐                     │
│                    │   Global Placer    │                     │
│                    │   (LLM Agent)      │                     │
│                    │                    │                     │
│                    │  ┌──────────────┐  │                     │
│                    │  │Regional      │  │  (复杂板子才有)      │
│                    │  │Placer ×K     │  │                     │
│                    │  └──────────────┘  │                     │
│                    └────────┬───────────┘                     │
│                             │ reshape 请求                    │
│                             ▼                                 │
│                    Module Placer 响应调整                      │
├─────────────────────────────────────────────────────────────┤
│                        Phase 3: 迭代精调循环                   │
│                                                              │
│         ┌──────────────────────────────────────┐             │
│         │            Architect                  │             │
│         │          (看地图 + 读反馈)             │             │
│         └──┬──────────┬──────────┬─────────────┘             │
│            │          │          │                            │
│            ▼          ▼          ▼                            │
│      ┌──────────┐┌────────┐┌─────────┐                      │
│      │ Placer   ││ Router ││ Critic  │                      │
│      │ 集群     ││        ││         │                      │
│      │(按需激活) ││ 模式ABC ││ Fast+Deep│                     │
│      └─────┬────┘└───┬────┘└────┬────┘                      │
│            │         │          │                            │
│            └─────────┴──────────┘                            │
│                      │ 反馈汇总                               │
│                      ▼                                       │
│               Architect 决策下一步                             │
│               (继续迭代 / 收敛 / 回退)                         │
├─────────────────────────────────────────────────────────────┤
│                        Phase 4                               │
│         最终验证 → 收尾脚本 → DRC → 保存 → 输出报告            │
└─────────────────────────────────────────────────────────────┘
```

## 附录 B：关键数据流一览

| 数据 | 生产者 | 消费者 | 生命周期 |
|------|--------|--------|---------|
| 增强网表 | Analyzer | Architect, 所有 Placer, Critic | 全程不变（除非用户修改原理图） |
| 地图快照 | 地图服务（自动从 KiCad 状态生成） | Architect, Global Placer | 每次模块位置/尺寸变化后更新 |
| 模块局部视图 | 视图服务（自动从 KiCad 状态生成） | Module Placer | 每次模块内器件变化后更新 |
| 布线验证报告 | Router | Architect | 每次验证后生成，Architect 消费后归档 |
| 问题清单 | Critic | Architect | 每次评审后生成，问题修复后标记关闭 |
| 修改历史栈 | Architect | Architect（自用） | 全程累积，用于回退决策 |
| KiCad Commit 检查点 | 系统 | 系统（回滚用） | 关键节点创建，成功后可清理旧检查点 |

## 附录 C：工具层完整清单

### C.1 KiCad API 桥接层

直接封装 kipy API 的底层操作，所有上层工具最终通过此层与 KiCad 交互。

| 函数 | 对应 kipy 调用 |
|------|---------------|
| `kicad_move_footprint(ref, x_nm, y_nm)` | `fp.position = Vector2(...); board.update_items(fp)` |
| `kicad_rotate_footprint(ref, angle_deg)` | `fp.orientation = Angle.from_degrees(...); board.update_items(fp)` |
| `kicad_get_footprint_info(ref)` | `board.get_footprints()` 过滤 + 读取属性 |
| `kicad_get_pad_positions(ref)` | `fp.pads` 遍历读取 |
| `kicad_get_all_nets()` | `board.get_nets()` |
| `kicad_get_board_outline()` | `board.get_shapes()` 过滤 Edge.Cuts 层 |
| `kicad_get_stackup()` | `board.get_stackup()` |
| `kicad_create_commit()` | `board.begin_commit()` |
| `kicad_push_commit(msg)` | `board.push_commit(commit, message=msg)` |
| `kicad_drop_commit()` | `board.drop_commit(commit)` |
| `kicad_save()` | `board.save()` |

### C.2 几何计算层

纯算法，不涉及 KiCad API 调用。

| 函数 | 功能 |
|------|------|
| `calc_distance(p1, p2)` | 两点距离 |
| `calc_bbox(components[])` | 一组器件的外接矩形 |
| `calc_overlap(rect1, rect2)` | 两个矩形的重叠面积 |
| `calc_ratsnest_crossings(ratsnest[])` | 飞线交叉数（扫除线算法） |
| `calc_congestion_heatmap(region, ratsnest[])` | 区域拥塞热力图 |
| `calc_loop_area_3d(pin_a, via, cap, via, pin_b, stackup)` | 三维电流环路面积 |
| `calc_channel_capacity(gap_width, layer_count, min_spacing, min_width)` | 通道可容纳走线数 |
| `calc_force_field_energy(modules[], connections[], weights)` | 磁力场总势能 |
| `resolve_overlap_minimum_displacement(rects[], board_outline)` | 最小位移消解重叠 |

### C.3 布线验证层

| 函数 | 功能 |
|------|------|
| `evaluate_ratsnest(mode='inter_module')` | 飞线统计分析（模式 A） |
| `run_global_router(nets[], obstacles[])` | 全局布线评估（模式 B） |
| `run_detailed_router(nets[], obstacles[], constraints)` | 详细布线验证（模式 C） |
| `evaluate_force_field(modules[], connections[])` | 磁力场评估 |

### C.4 DRC 与检查层

| 函数 | 功能 |
|------|---

<cp_artifact title="PCB 多 Agent 自动布局系统 — 分工架构设计（续4-终）" format="markdown">
<!-- 接续上文：附录 C.4 DRC 与检查层表格 -->

| 函数 | 功能 |
|------|------|
| `check_courtyard_overlap(ref_a, ref_b)` | 检查两个器件的 courtyard 是否重叠 |
| `check_board_boundary(ref)` | 检查器件是否超出板框 |
| `check_min_clearance(ref_a, ref_b)` | 检查两个器件间最小间距是否满足规则 |
| `check_decap_distance(cap_ref, ic_ref, pin_name)` | 检查去耦电容到 IC 电源引脚的距离 |
| `check_crystal_clearance(crystal_ref, radius_mm)` | 检查晶振周围净空区 |
| `check_ref_plane_continuity(net_name, layer)` | 检查指定网络下方参考平面的连续性 |
| `check_orientation_consistency(refs[])` | 检查一组器件朝向是否一致 |
| `run_kicad_drc()` | 调用 KiCad 内置 DRC 引擎，返回违规列表 |

---

## 附录 D：典型板子的 Agent 实例化示例

以一块中等复杂度的 IoT 开发板为例（STM32 + DDR3 + WiFi + 电源管理，约 200 个器件），说明系统实际运行时各 Agent 的实例化情况。

**Analyzer 输出摘要：**

- 板子类型：mixed_signal_with_rf
- 复杂度：medium_high（评分 7.5/10）
- 模块数量：12
- 关键约束：DDR3 等长、USB 差分对、WiFi 天线净空

**Architect 分配方案：**

```
Module Placer 实例：12 个（每个模块一个）
  MP-M01: MCU_Core (23 components)
  MP-M02: DDR3_Memory (15 components)
  MP-M03: 3V3_LDO (5 components)
  MP-M04: 5V_Buck (8 components)
  MP-M05: USB_Interface (6 components)
  MP-M06: WiFi_RF (11 components)
  MP-M07: Analog_Sensor (9 components)
  MP-M08: 1V8_LDO (4 components)
  MP-M09: Flash_SPI (5 components)
  MP-M10: LED_Indicators (8 components)
  MP-M11: Debug_SWD (4 components)
  MP-M12: Power_Input (6 components)

Global Placer 实例：1 个（板子复杂度中等，不需要分区域）

Router 实例：1 个

Critic 实例：1 个
```

**预估资源消耗：**

| 阶段 | LLM 调用次数 | 预估耗时 | 预估成本（Opus 级） |
|------|-------------|---------|-------------------|
| Phase 0 Analyzer | 3-5 次 | 30-60s | $0.30-0.50 |
| Phase 1 模块初始化 | 60-120 次（12 模块 × 5-10 轮） | 2-4min | $1.50-3.00 |
| Phase 2 全局布局 | 15-30 次 | 1-3min | $0.80-1.50 |
| Phase 3 迭代精调 | 50-150 次 | 5-20min | $2.00-6.00 |
| Phase 4 最终验证 | 5-10 次 | 1-2min | $0.30-0.50 |
| **合计** | **130-315 次** | **10-30min** | **$5-12** |

如果 Module Placer 使用轻量模型（Sonnet / GPT-4o-mini），成本可降低约 40-50%。

---

## 附录 E：术语表

| 术语 | 定义 |
|------|------|
| 增强网表（Enriched Netlist） | Analyzer 输出的带有语义标注的网表，包含器件角色、信号类型、模块划分、约束关系 |
| 地图（Map） | Architect 感知世界的抽象表示，由板框 + 模块矩形 + 模块间连接构成 |
| 模块矩形（Module Rectangle） | 一个模块内所有器件的外接矩形，是 Global Placer 操作的基本单元 |
| 磁力场（Force Field） | Router 的布局质量评估模型，将模块间连接建模为带权重的弹簧力 |
| 布局 Skill | 封装了特定电路类型最佳实践的高级布局操作，Module Placer 可一键调用 |
| Fast Check | Critic 的规则引擎层，每次操作后自动触发，毫秒级完成 |
| Deep Review | Critic 的 LLM 驱动层，由 Architect 在关键节点触发，按领域知识库逐项检查 |
| 二次初始化 | 全局布局确定后，Module Placer 根据新的外部接口方向重新调整模块内部布局 |
| 检查点（Checkpoint） | 利用 KiCad Commit 机制创建的状态快照，用于回滚 |
| 布通率（Completion Rate） | 详细布线器成功布通的网络数占总网络数的比例 |

---

*文档结束。本文档为架构讨论稿，后续将根据评审意见进入各模块的详细设计阶段。*