"""Tests for the recursion-limit trace logging helpers in runs.worker.

When a run exhausts the LangGraph recursion limit the bare error says nothing
about WHY the agent never converged. These helpers build a compact, log-safe
summary of the message history (tool-call histogram + trailing sequence) so the
loop is diagnosable from logs alone.
"""

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.errors import GraphRecursionError

from deerflow.runtime.runs.worker import (
    _is_recursion_error,
    _read_latest_checkpoint_messages,
    _summarize_run_messages,
)


def test_is_recursion_error_detects_graph_recursion_error():
    assert _is_recursion_error(GraphRecursionError("Recursion limit of 80 reached")) is True


def test_is_recursion_error_message_fallback():
    # Some wrappers re-raise as a plain exception — match on the message too.
    assert _is_recursion_error(RuntimeError("Recursion limit of 80 reached without...")) is True


def test_is_recursion_error_false_for_unrelated():
    assert _is_recursion_error(ValueError("bad ticker")) is False


def test_summarize_run_messages_counts_and_orders_tool_calls():
    messages = [
        HumanMessage(content="research AAPL"),
        AIMessage(content="", tool_calls=[{"name": "web_search", "args": {}, "id": "1"}]),
        ToolMessage(content="...", tool_call_id="1"),
        AIMessage(content="", tool_calls=[{"name": "web_search", "args": {}, "id": "2"}]),
        ToolMessage(content="...", tool_call_id="2"),
        AIMessage(content="", tool_calls=[
            {"name": "jina_reader", "args": {}, "id": "3"},
            {"name": "web_search", "args": {}, "id": "4"},
        ]),
    ]

    summary = _summarize_run_messages(messages)

    assert summary["total_messages"] == 6
    assert summary["ai_messages"] == 3
    assert summary["tool_messages"] == 2
    assert summary["total_tool_calls"] == 4
    assert summary["tool_calls_by_name"]["web_search"] == 3
    assert summary["tool_calls_by_name"]["jina_reader"] == 1
    # The trailing sequence is what reveals a loop.
    assert summary["recent_tool_calls"][-2:] == ["jina_reader", "web_search"]


def test_summarize_run_messages_accepts_plain_dicts():
    messages = [
        {"type": "human", "content": "go"},
        {"type": "ai", "content": "", "tool_calls": [{"name": "web_search"}]},
        {"type": "tool", "content": "r"},
    ]

    summary = _summarize_run_messages(messages)

    assert summary["total_tool_calls"] == 1
    assert summary["tool_calls_by_name"] == {"web_search": 1}


def test_summarize_run_messages_caps_recent_sequence_at_15():
    messages = [
        AIMessage(content="", tool_calls=[{"name": f"t{i}", "args": {}, "id": str(i)}])
        for i in range(30)
    ]

    summary = _summarize_run_messages(messages)

    assert summary["total_tool_calls"] == 30
    assert len(summary["recent_tool_calls"]) == 15
    assert summary["recent_tool_calls"][-1] == "t29"


@pytest.mark.asyncio
async def test_read_latest_checkpoint_messages_none_checkpointer():
    assert await _read_latest_checkpoint_messages(None, "t1") == []


@pytest.mark.asyncio
async def test_read_latest_checkpoint_messages_reads_from_checkpoint():
    saver = InMemorySaver()
    cfg = {"configurable": {"thread_id": "t1", "checkpoint_ns": ""}}
    ckpt = empty_checkpoint()
    ckpt["channel_values"] = {"messages": [HumanMessage(content="hi"), AIMessage(content="yo")]}
    await saver.aput(cfg, ckpt, {}, {})

    messages = await _read_latest_checkpoint_messages(saver, "t1")

    assert len(messages) == 2


@pytest.mark.asyncio
async def test_read_latest_checkpoint_messages_unknown_thread():
    saver = InMemorySaver()
    assert await _read_latest_checkpoint_messages(saver, "does-not-exist") == []
