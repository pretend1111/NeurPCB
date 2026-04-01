"""
agents/base_agent.py — Agent 基类

管理 system prompt、tool 注册、多轮调用循环。
所有具体 Agent（Analyzer、Architect、Placer 等）继承此类。
"""
from __future__ import annotations

import json
import logging
from typing import Any

from agents.llm_client import (
    ToolDef,
    ToolCallResult,
    query_llm_json,
    run_tool_calling_loop,
)

logger = logging.getLogger(__name__)


class BaseAgent:
    """
    Agent 基类。

    子类需要：
    1. 设置 self.system_prompt
    2. 通过 register_tool() 注册工具（可选）
    3. 调用 run_json() 或 run_tools() 执行任务
    """

    def __init__(self, name: str, system_prompt: str, model: str = "deepseek-chat"):
        self.name = name
        self.system_prompt = system_prompt
        self.model = model
        self._tools: list[ToolDef] = []

    def register_tool(
        self,
        name: str,
        description: str,
        parameters: dict,
        handler,
    ) -> None:
        """注册一个工具供 LLM 调用"""
        self._tools.append(ToolDef(
            name=name,
            description=description,
            parameters=parameters,
            handler=handler,
        ))
        logger.debug("Agent %s registered tool: %s", self.name, name)

    def run_json(self, user_prompt: str, temperature: float = 0.0) -> dict:
        """JSON 模式：发送 prompt，返回结构化 JSON"""
        logger.info("[%s] Running JSON query", self.name)
        return query_llm_json(
            self.system_prompt,
            user_prompt,
            model=self.model,
            temperature=temperature,
        )

    def run_tools(
        self,
        user_prompt: str,
        max_rounds: int = 10,
        temperature: float = 0.0,
    ) -> ToolCallResult:
        """Tool-calling 模式：多轮工具调用循环"""
        logger.info("[%s] Running tool-calling loop (max %d rounds)", self.name, max_rounds)
        return run_tool_calling_loop(
            self.system_prompt,
            user_prompt,
            tools=self._tools,
            model=self.model,
            max_rounds=max_rounds,
            temperature=temperature,
        )
