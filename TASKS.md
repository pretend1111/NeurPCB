# NeurPCB 开发任务清单

> 最后更新: 2026-04-01
> 当前阶段: Phase 3 — Agent 框架 + Analyzer

---

## 开发规则

1. **每次开始写代码前**，先在这里领一个任务，把状态改成 `🔵 进行中`
2. **每次完成一个任务**，把状态改成 `✅ 完成`，写一行完成备注，commit + push
3. **每次遇到意外发现**（API 限制、设计文档没考虑到的情况），记录到下面的「开发日志」
4. **每个任务对应一个 git commit**，commit message 格式: `[模块名] 做了什么`
5. **严禁写了一堆东西不 commit**。写完一个功能就 commit，别攒着

---

## 当前任务

### Phase 0: KiCad Bridge 层
> 目标: 封装所有 kipy 操作，其他模块不直接碰 kipy

| # | 任务 | 状态 | 备注 |
|---|------|------|------|
| 0.1 | 建立项目目录结构 | ✅ 完成 | 目录已存在 |
| 0.2 | 实现 KiCadBridge 基础类（连接、读取 footprint 列表） | ✅ 完成 | `bridge/kicad_bridge.py` 统一桥接类 |
| 0.3 | 实现 move/rotate footprint | ✅ 完成 | 支持单个/批量 move、rotate、lock |
| 0.4 | 实现读取板框、网表、焊盘坐标 | ✅ 完成 | get_board_outline / get_nets / get_pad_positions |
| 0.5 | 实现 checkpoint 管理（begin/push/drop commit） | ✅ 完成 | begin_commit / push_commit / drop_commit |
| 0.6 | 写集成测试：用测试板跑一遍所有 bridge 功能 | ✅ 完成 | 22 个离线 mock 测试 + --live 在线测试 |

### Phase 1: 几何计算层
> 目标: 纯算法，不碰 KiCad API，不碰 LLM

| # | 任务 | 状态 | 备注 |
|---|------|------|------|
| 1.1 | 基础几何（距离、bbox、矩形重叠检测） | ✅ 完成 | `geometry/core.py` Rect + 重叠消解 |
| 1.2 | 飞线分析（交叉数、总长度统计） | ✅ 完成 | `geometry/ratsnest.py` 叉积法线段交叉 |
| 1.3 | 拥塞热力图 + 磁力场势能 | ✅ 完成 | `geometry/congestion.py` 网格热力图 + 弹簧模型 |
| 1.4 | 通道容量计算 | ✅ 完成 | `geometry/channel.py` 多层走线容量 |

### Phase 2: 布局 Skills
> 目标: 确定性布局算法，不走 LLM

| # | 任务 | 状态 | 备注 |
|---|------|------|------|
| 2.1 | skill_decap_cluster（去耦电容排列） | ✅ 完成 | 支持引脚对准模式和均匀环绕模式 |
| 2.2 | skill_ldo_layout（LDO 标准布局） | ✅ 完成 | 4 方向信号流 + 反馈电阻 Kelvin 连接 |
| 2.3 | skill_crystal_layout（晶振布局） | ✅ 完成 | 负载电容对称 + 可配接近角度 |
| 2.4 | skill_force_directed_place（力导向通用布局） | ✅ 完成 | 弹簧吸引+斥力排斥+模拟退火+bbox约束 |
| 2.5 | skill_led_indicator | ✅ 完成 | LED+限流电阻串联紧凑排列 |
| 2.6 | skill_voltage_divider | ✅ 完成 | 分压器对称排列 |
| 2.7 | 更多 skill 按需添加... | ⬚ 待做 | buck_layout / usb_esd 等后续按需 |

### Phase 3: Agent 框架 + Analyzer
> 目标: LLM Tool-Calling 框架 + 第一个 Agent

| # | 任务 | 状态 | 备注 |
|---|------|------|------|
| 3.1 | LLM Client 封装（DeepSeek, tool-calling） | ✅ 完成 | JSON 模式 + tool-calling 多轮循环，env var 读 key |
| 3.2 | BaseAgent 类（system prompt + tool calling 循环） | ✅ 完成 | run_json / run_tools 两种模式 |
| 3.3 | 网表提取器（从 KiCad 读连接关系） | ✅ 完成 | netlist_graph.py networkx 图构建 |
| 3.4 | 图聚类模块划分（Louvain） | ✅ 完成 | 自动聚类 + 小模块合并 + 孤立节点分配 |
| 3.5 | Analyzer Agent（LLM 校正模块划分 + 输出增强网表） | ✅ 完成 | ESP32-C3 实测: 55 器件 → 5 模块，DeepSeek 标注角色/连接 |

### Phase 4: Module Placer
> 目标: LLM 驱动的模块内布局

| # | 任务 | 状态 | 备注 |
|---|------|------|------|
| 4.1 | Module Placer 工具集注册（原子操作 + Skills） | ⬚ 待做 | |
| 4.2 | observe_module_layout / observe_violations 实现 | ⬚ 待做 | |
| 4.3 | Module Placer Agent + system prompt | ⬚ 待做 | |
| 4.4 | 在 LDO 模块上测试通过 | ⬚ 待做 | |

### Phase 5: Global Placer + 地图系统
| # | 任务 | 状态 | 备注 |
|---|------|------|------|
| 5.1 | 模块矩形表示 + 批量移动 | ⬚ 待做 | |
| 5.2 | 地图系统（状态 → 文本压缩） | ⬚ 待做 | |
| 5.3 | skill_gp_force_directed | ⬚ 待做 | |
| 5.4 | skill_gp_resolve_overlap | ⬚ 待做 | |
| 5.5 | Global Placer Agent | ⬚ 待做 | |

### Phase 6: Router + Critic
| # | 任务 | 状态 | 备注 |
|---|------|------|------|
| 6.1 | 飞线分析评估（模式 A） | ⬚ 待做 | |
| 6.2 | 磁力场评估模型 | ⬚ 待做 | |
| 6.3 | Critic Fast Check 规则引擎 | ⬚ 待做 | |
| 6.4 | Critic Deep Review | ⬚ 待做 | |

### Phase 7: Architect + 端到端编排
| # | 任务 | 状态 | 备注 |
|---|------|------|------|
| 7.1 | Architect 上下文管理 | ⬚ 待做 | |
| 7.2 | Phase 0-4 流程编排 | ⬚ 待做 | |
| 7.3 | 迭代循环 + 收敛判定 | ⬚ 待做 | |
| 7.4 | 端到端测试（用真实 PCB 跑通） | ⬚ 待做 | |

---

## 开发日志

> 每次遇到重要发现、设计变更、踩坑记录，写在这里。格式: `日期 | 简述`

| 日期 | 记录 |
|------|------|
| 2026-03-28 | 项目启动，建立任务清单和目录结构 |
| 2026-04-01 | Phase 0 完成：重写 bridge 层为统一 KiCadBridge 类，替代原有分散的 extractor/executor |
| 2026-04-01 | Phase 1 完成：geometry 层 4 个模块（core/ratsnest/congestion/channel），40 个测试全部通过 |
| 2026-04-01 | Phase 2 完成：6 个 Skills（decap/ldo/crystal/force_directed/led/divider），17 个测试通过 |
| 2026-04-01 | Phase 3 完成：LLM Client + BaseAgent + Louvain 聚类 + Analyzer Agent，ESP32 实测成功 |

---

## 设计变更记录

> 跟架构设计文档不一致的地方记录在这里，避免日后混乱

| 日期 | 变更内容 | 原因 |
|------|---------|------|
| 2026-04-01 | 废弃 kicad_extractor.py / kicad_executor.py，统一为 KiCadBridge 类 | 架构文档要求"其他模块不直接碰 kipy"，统一入口更好管理连接和事务 |
