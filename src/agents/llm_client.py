"""
agents/llm_client.py — LLM 客户端封装

支持 DeepSeek（OpenAI 兼容接口）。
API key 从环境变量读取，严禁硬编码。
支持两种模式：
  1. JSON 模式：直接返回结构化 JSON
  2. Tool-calling 模式：注册工具函数，多轮调用循环
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from openai import OpenAI

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

_DEFAULT_MODEL = "deepseek-chat"
_DEFAULT_BASE_URL = "https://api.deepseek.com"


def _get_client() -> OpenAI:
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError(
            "DEEPSEEK_API_KEY environment variable is not set. "
            "Run: export DEEPSEEK_API_KEY=sk-..."
        )
    base_url = os.environ.get("DEEPSEEK_BASE_URL", _DEFAULT_BASE_URL)
    return OpenAI(api_key=api_key, base_url=base_url)


# ---------------------------------------------------------------------------
# Tool 定义
# ---------------------------------------------------------------------------

@dataclass
class ToolDef:
    """工具定义，供 LLM tool-calling 使用"""
    name: str
    description: str
    parameters: dict           # JSON Schema
    handler: Callable[..., Any]


def tool_def_to_openai(tool: ToolDef) -> dict:
    """转换为 OpenAI tool-calling 格式"""
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }


# ---------------------------------------------------------------------------
# JSON 模式调用
# ---------------------------------------------------------------------------

def query_llm_json(
    system_prompt: str,
    user_prompt: str,
    model: str = _DEFAULT_MODEL,
    temperature: float = 0.0,
) -> dict:
    """
    发送 prompt 并以 JSON 格式解析返回。

    返回 dict，解析失败返回 {}。
    """
    client = _get_client()
    logger.info("LLM JSON query (%d + %d chars)", len(system_prompt), len(user_prompt))

    messages = [
        {"role": "system", "content": system_prompt + "\nYou must respond in valid JSON format."},
        {"role": "user", "content": user_prompt},
    ]

    completion = client.chat.completions.create(
        model=model,
        messages=messages,
        response_format={"type": "json_object"},
        temperature=temperature,
    )

    text = completion.choices[0].message.content
    # 有些模型会在 json_object 模式下仍然返回 markdown 包裹
    match = re.search(r'```json\s*(.*?)\s*```', text, re.DOTALL)
    if match:
        text = match.group(1)

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        logger.error("Failed to parse LLM JSON response: %s\nRaw: %s", e, text[:500])
        return {}


# ---------------------------------------------------------------------------
# Tool-calling 模式调用
# ---------------------------------------------------------------------------

@dataclass
class ToolCallResult:
    """一次 tool-calling 会话的结果"""
    final_message: str = ""
    tool_calls_made: list[dict] = field(default_factory=list)
    messages: list[dict] = field(default_factory=list)


def run_tool_calling_loop(
    system_prompt: str,
    user_prompt: str,
    tools: list[ToolDef],
    model: str = _DEFAULT_MODEL,
    max_rounds: int = 10,
    temperature: float = 0.0,
) -> ToolCallResult:
    """
    多轮 tool-calling 循环。

    LLM 可以调用注册的工具，工具结果自动回填，
    直到 LLM 返回纯文本（不再调用工具）或达到最大轮次。
    """
    client = _get_client()
    tool_map = {t.name: t for t in tools}
    openai_tools = [tool_def_to_openai(t) for t in tools]

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    result = ToolCallResult(messages=messages)

    for round_idx in range(max_rounds):
        logger.info("Tool-calling round %d", round_idx + 1)

        completion = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=openai_tools if openai_tools else None,
            temperature=temperature,
        )

        choice = completion.choices[0]
        msg = choice.message

        # 没有 tool calls → 结束循环
        if not msg.tool_calls:
            result.final_message = msg.content or ""
            messages.append({"role": "assistant", "content": result.final_message})
            break

        # 有 tool calls → 执行每个工具并回填结果
        # 先把 assistant 消息加入历史
        messages.append(msg.model_dump())

        for tc in msg.tool_calls:
            fn_name = tc.function.name
            fn_args_str = tc.function.arguments

            logger.info("  Tool call: %s(%s)", fn_name, fn_args_str[:200])
            result.tool_calls_made.append({
                "name": fn_name,
                "arguments": fn_args_str,
            })

            tool = tool_map.get(fn_name)
            if tool is None:
                tool_result = json.dumps({"error": f"Unknown tool: {fn_name}"})
            else:
                try:
                    args = json.loads(fn_args_str)
                    ret = tool.handler(**args)
                    tool_result = json.dumps(ret, ensure_ascii=False, default=str)
                except Exception as e:
                    logger.error("Tool %s failed: %s", fn_name, e)
                    tool_result = json.dumps({"error": str(e)})

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": tool_result,
            })
    else:
        logger.warning("Tool-calling loop hit max rounds (%d)", max_rounds)

    result.messages = messages
    return result
