import json

from claude_agent_sdk import AssistantMessage, ResultMessage, ToolUseBlock

from app.observability import UsageTracker


def _assistant(tool_id, usage):
    return AssistantMessage(
        content=[ToolUseBlock(id=tool_id, name="mcp__a11y-browser__run_axe", input={})],
        model="m", usage=usage,
    )


async def test_joins_tokens_from_stream_with_hook_timing_and_cost():
    tracker = UsageTracker()
    run = tracker.start_agent("auditor", "https://x.com/")
    run.on_assistant(_assistant("t1", {"input_tokens": 10, "output_tokens": 4, "cache_read_input_tokens": 100}))
    hook = run.hooks()["PostToolUse"][0].hooks[0]
    await hook(
        {"hook_event_name": "PostToolUse", "tool_use_id": "t1", "tool_name": "mcp__a11y-browser__run_axe", "duration_ms": 250},
        "t1", None,
    )
    run.on_result(ResultMessage(
        subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=1,
        session_id="s", total_cost_usd=0.02,
    ))

    [call] = tracker.calls
    assert (call.agent, call.target, call.ok, call.duration_ms) == ("auditor", "https://x.com/", True, 250)
    assert call.turn_tokens["input_tokens"] == 10 and call.turn_tokens["cache_read_input_tokens"] == 100
    assert tracker.cost_usd == 0.02
    assert tracker.totals_by_agent()["auditor"].tool_calls == 1
    rows = [json.loads(line) for line in tracker.to_jsonl().splitlines()]
    assert {r["type"] for r in rows} == {"tool_call", "agent"}


async def test_failed_tool_call_is_recorded_even_if_hook_runs_first():
    tracker = UsageTracker()
    run = tracker.start_agent("crawler")
    hook = run.hooks()["PostToolUseFailure"][0].hooks[0]
    await hook(
        {"hook_event_name": "PostToolUseFailure", "tool_use_id": "t9", "tool_name": "navigate", "error": "timeout"},
        "t9", None,
    )
    run.on_assistant(_assistant("t9", {"output_tokens": 3}))
    [call] = tracker.calls
    assert call.ok is False and call.error == "timeout" and call.turn_tokens["output_tokens"] == 3
    assert tracker.agents[0].tool_calls == 1
