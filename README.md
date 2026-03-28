# NeurPCB

PCB 多 Agent 自动布局系统 — 基于 LLM + KiCad Python API

## 环境

- Python: conda activate kicad
- KiCad: 9.0+，需启用 API Server
- LLM: Claude / GPT / Gemini（配置见 src/config.py）

## 项目状态

见 [TASKS.md](TASKS.md)

## 目录结构

```
src/
├── bridge/          # KiCad API 封装层
├── geometry/        # 几何计算（纯算法）
├── skills/          # 布局 Skills（确定性算法）
│   ├── module/      # 模块级 Skill
│   └── global/      # 全局级 Skill
├── agents/          # LLM Agent
├── routing/         # 布线评估
├── orchestrator/    # 流程编排
└── utils/           # 工具类
```

## 快速开始

```bash
conda activate kicad
python src/main.py --board path/to/your.kicad_pcb
```
