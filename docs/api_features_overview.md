# NeurPCB: System Architecture, API & Feature Overview

本文档总结了目前已在 `NeurPCB` 项目中实装的核心 Agent 架构、自动化 Pipeline 阶段以及与底层 KiCad 交互的封装 API。

---

## 1. 核心架构设计理念：黑盒递归降维
面对繁杂的 PCB 元器件（动辄上百个），LLM 直接进行平面规划会导致极为严重的“坐标幻觉”与上下文爆炸。因此，本系统引入了类似软件工程“面向对象”的物理隔离准则：
* **模块黑盒 (Blackbox Keepout)**：底层的电路群组被封装为“黑盒”。对全局而言，它是一个实心的、不可进入的**禁布区 (Keepout Zone)**。
* **虚拟引脚 (Unified I/O)**：模块内外的心跳连线全部映射到黑盒边缘的统一虚拟坐标（焊盘）上。
* **缝隙走廊 (Corridor Routing)**：全局走线只被允许在各个绝缘黑盒之间留出的缝隙通道中穿梭，极大降低了寻路难度。

---

## 2. API Tooling 底层封装 (`src/bridge/`)

为弥合大语言模型（文本语义）与 KiCad（几何坐标）之间的视觉断层，我们已开发并调通了以下核心 Python API 工具箱：

### 2.1. `BlackBoxManager` (`blackbox.py`)
负责物理边界的虚拟化与封装隔离。
* **功能**：
  - 自动收拢指定元器件的集群外框 (Bounding Box)。
  - 生成物理保护罩（伪 Keep-Out Zone），并对全局屏蔽其内部构造。
  - **`encapsulate_module(module_id, footprints, unified_io_nets)`**：输出带有边缘分布 Virtual I/O 的结构化模块信息供上层使用。

### 2.2. `LocalRadar` (`radar.py`)
赋予大模型“局部避障视野”。
* **功能**：
  - 原生 CAD 的距离换算与拓扑扫描探测器。
  - **`probe_environment(center_coord, radius)`**：向指定圆心发射雷达扫描，返回诸如 *"Obstacle 'U1' detected 2.5mm to the East"* 这样极度精简的口语化反馈。LLM 凭借该语义即可感知周围路况。

### 2.3. `TurtleRouter` (`turtle.py`)
负责将 LLM 的“意图动作”翻译为物理连线。
* **功能**：
  - 支持事务回滚（Commit / Rollback）的步进式画线器。
  - **`route_sequence(net_name, layer_name, start_coord, moves)`**：接收形如 `[{"dir": "UP_RIGHT", "dist": 2.5}]` 的相对向量集。系统在底层转化为 `kipy Track` 实体，如果在绘制中遭到碰撞，则自动熔断抛出准确的相对碰撞坐标，供模型闭环纠错（Loop feedback）。

---

## 3. Multi-Agent 架构 (`src/agents/`)

在基建齐备后，负责自动化图纸生成的大模型 Agent 军团被分为以下三个独立职责的专家：

### 3.1. `Analyzer` (智能分块分析师)
* **输入**：扁平且无序的原始 Netlist（网表）及元器件清单。
* **输出**：基于电路原理图连接紧密度（高内聚低耦合）划分好的物理逻辑模块群组（如：`电源管理模块`、`存储系模块`、`核心处理块`）。
* **接口**：`chunk_schematic(components, nets)`

### 3.2. `Architect` (宏观全局规划师)
* **输入**：Analyzer 提供的数个宏观“黑盒”、PCB 画板外形限制、用户的绝对偏好（如：*"USB接口严禁靠近天线区域"*）。
* **输出**：每个模块在画板上的绝对占地坐标 `(x, y)` 以及所需圈出的外框长宽大小。**它绝不碰内部器件，只分地盘。**
* **接口**：`orchestrator_global_layout(board_dim, abstract_modules, nets, prefs)`

### 3.3. `ModulePlacer` (精细局部布线师)
* **输入**：单一黑盒的受限天地大小（如 `15x15mm`）以及归属于该模块内的十几个具体器件。
* **输出**：在自己的相对坐标系内，把电容、电阻等寄生设备围绕主发热 IC 或引脚密集端进行紧密环绕布局。
* **接口**：`place_module_internals(module_id, components, local_bbox)`

---

## 4. 自动化流水线实装 (`src/orchestrator/`)

全链路流水线（Pipeline）已打通，并支持从虚拟原理图一键生成数据拓扑并跑通测试。代表脚本有：

* **`pipeline_advanced.py` (高阶约束测试)**：以传统的 ESP32 最小系统（11个器件）作为沙盒，在执行中同时测算了：**稀疏约束（确保发热 LDO 远离 MCU）**与**等长约束（UART TX/RX 同距走线）**。
* **`pipeline_massive.py` (海量规模极限测试)**：最高阶测试。构造了包含 60 余个器件的主板。在流水线的最后，我们**在 Python 层独立实装了一个高阶“曼哈顿 A* 全局网格走线器”**。该独立物理引擎利用 LLM 在模块黑盒之间留出的缝隙（Corridors）成功寻路避障，跑出了 100% 的总线通达率（37/37网线），完美输出了带有双层实际线路连接走向的纯手工无干预的 SVG 主板渲染图谱。

---

*（文档生成于本项目环境本地调试验证完全通过后。这套以“宏观降维封装 + 逻辑语义路由”为基石的设计范式已被完全跑通，下一步可直接对接 Kicad Python 9.0 物理落地生成真正的 `.kicad_pcb` 工程。）*
