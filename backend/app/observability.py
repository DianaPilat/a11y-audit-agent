"""Structured log of every tool call, with tokens and cost, per subagent.

Hooks see the tool call and how long it took but not token counts; the message stream
has the tokens (AssistantMessage.usage) but not the timing. UsageTracker joins the two
by tool_use_id and writes one JSON log line per call. Cost is only known per agent run
(ResultMessage.total_cost_usd), so it is recorded on the agent summary, not per call.
"""

import json
import logging
from dataclasses import asdict, dataclass, field
from typing import Any

from claude_agent_sdk import HookMatcher

log = logging.getLogger("usage")

TOKEN_KEYS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")


def _tokens(usage: dict[str, Any] | None) -> dict[str, int]:
    usage = usage or {}
    return {k: int(usage.get(k) or 0) for k in TOKEN_KEYS}


@dataclass
class ToolCallRecord:
    agent: str  # "crawler", "auditor", "ticket_writer"
    target: str  # page url for the auditor, empty otherwise
    tool: str
    tool_use_id: str
    ok: bool | None = None  # None until the hook reports
    duration_ms: int | None = None
    error: str | None = None
    # Tokens of the model turn that issued this call. Calls issued in the same turn share it.
    turn_tokens: dict[str, int] = field(default_factory=dict)


@dataclass
class AgentSummary:
    agent: str
    target: str
    model_calls: int = 0
    tool_calls: int = 0
    tokens: dict[str, int] = field(default_factory=lambda: dict.fromkeys(TOKEN_KEYS, 0))
    cost_usd: float = 0.0


class UsageTracker:
    """Collects records for one audit; one `agent_run` per subagent run."""

    def __init__(self) -> None:
        self.calls: list[ToolCallRecord] = []
        self.agents: list[AgentSummary] = []

    def start_agent(self, agent: str, target: str = "") -> "AgentRun":
        summary = AgentSummary(agent=agent, target=target)
        self.agents.append(summary)
        return AgentRun(self, summary)

    @property
    def cost_usd(self) -> float:
        return sum(a.cost_usd for a in self.agents)

    def totals_by_agent(self) -> dict[str, AgentSummary]:
        out: dict[str, AgentSummary] = {}
        for a in self.agents:
            t = out.setdefault(a.agent, AgentSummary(agent=a.agent, target="*"))
            t.model_calls += a.model_calls
            t.tool_calls += a.tool_calls
            t.cost_usd += a.cost_usd
            for k in TOKEN_KEYS:
                t.tokens[k] += a.tokens[k]
        return out

    def to_jsonl(self) -> str:
        rows = [{"type": "tool_call", **asdict(c)} for c in self.calls]
        rows += [{"type": "agent", **asdict(a)} for a in self.agents]
        return "\n".join(json.dumps(r) for r in rows) + "\n"

    def format_summary(self) -> str:
        lines = [f"{'agent':<14}{'tools':>6}{'in':>9}{'out':>8}{'cache_r':>9}{'cost':>9}"]
        for name, t in self.totals_by_agent().items():
            lines.append(
                f"{name:<14}{t.tool_calls:>6}{t.tokens['input_tokens']:>9}{t.tokens['output_tokens']:>8}"
                f"{t.tokens['cache_read_input_tokens']:>9}{'$%.4f' % t.cost_usd:>9}"
            )
        lines.append(f"{'total':<14}{'':>6}{'':>9}{'':>8}{'':>9}{'$%.4f' % self.cost_usd:>9}")
        return "\n".join(lines)


class AgentRun:
    """Per-run handle: feeds stream messages in, supplies the hooks for ClaudeAgentOptions."""

    def __init__(self, tracker: UsageTracker, summary: AgentSummary) -> None:
        self.tracker = tracker
        self.summary = summary
        self._by_id: dict[str, ToolCallRecord] = {}

    # --- message stream side ---
    def on_assistant(self, message: Any) -> None:
        tokens = _tokens(message.usage)
        self.summary.model_calls += 1
        for k, v in tokens.items():
            self.summary.tokens[k] += v
        for block in message.content:
            tool_id = getattr(block, "id", None)
            name = getattr(block, "name", None)
            if tool_id and name and hasattr(block, "input"):
                rec = self._record(tool_id, name)
                rec.turn_tokens = tokens

    def on_result(self, message: Any) -> None:
        self.summary.cost_usd += message.total_cost_usd or 0.0
        log.info("agent done: %s", json.dumps({"type": "agent", **asdict(self.summary)}))

    # --- hook side ---
    def _record(self, tool_use_id: str, tool: str) -> ToolCallRecord:
        rec = self._by_id.get(tool_use_id)
        if rec is None:
            rec = ToolCallRecord(self.summary.agent, self.summary.target, tool, tool_use_id)
            self._by_id[tool_use_id] = rec
            self.tracker.calls.append(rec)
            self.summary.tool_calls += 1
        return rec

    async def _finished(self, input_data: Any, tool_use_id: str | None, context: Any) -> dict[str, Any]:
        rec = self._record(input_data["tool_use_id"], input_data["tool_name"])
        failed = input_data["hook_event_name"] == "PostToolUseFailure"
        rec.ok = not failed
        rec.duration_ms = input_data.get("duration_ms")
        rec.error = input_data.get("error") if failed else None
        log.info("tool call: %s", json.dumps({"type": "tool_call", **asdict(rec)}))
        return {}

    def hooks(self) -> dict[str, list[HookMatcher]]:
        matcher = [HookMatcher(hooks=[self._finished])]
        return {"PostToolUse": matcher, "PostToolUseFailure": matcher}
