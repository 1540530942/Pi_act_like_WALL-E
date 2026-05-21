from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

try:
    from .envelope import DecisionEnvelope, ToolCall
    from .face_router import is_face_skill
    from .planner import build_task_planner
except ImportError:
    from envelope import DecisionEnvelope, ToolCall
    from face_router import is_face_skill
    from planner import build_task_planner


SEQUENCE_SPLIT_PATTERN = re.compile(r"(?:然后|再|接着|之后|，|,|;|；)")


def _tool_for_skill(skill_id: str) -> str:
    if skill_id == "emergency_stop":
        return "emergency_stop"
    return "dispatch_face" if is_face_skill(skill_id) else "dispatch_action"


class RuleReactAgent:
    def __init__(self, *, base_dir: Path, router_config: dict[str, Any] | None):
        self.base_dir = base_dir
        self.router_config = router_config or {}
        self.catalog_path = self._resolve_catalog_path(base_dir, self.router_config)
        self.planner = build_task_planner(self.router_config, self.catalog_path)

    @staticmethod
    def _resolve_catalog_path(base_dir: Path, router_config: dict[str, Any]) -> Path:
        catalog_path = Path(str(router_config.get("skill_catalog") or "../action_move/skill_catalog.json"))
        if not catalog_path.is_absolute():
            catalog_path = (base_dir / catalog_path).resolve()
        return catalog_path

    def run(self, envelope: DecisionEnvelope) -> DecisionEnvelope:
        envelope.t_agent_start = time.time()
        parts = [part.strip() for part in SEQUENCE_SPLIT_PATTERN.split(envelope.transcript) if part.strip()]
        if not parts:
            parts = [envelope.transcript.strip()] if envelope.transcript.strip() else []
        tool_calls: list[ToolCall] = []
        agent_steps: list[dict[str, Any]] = []
        for order, part in enumerate(parts, start=1):
            plan = self.planner.plan(part)
            if not plan:
                agent_steps.append({"order": order, "text": part, "status": "unmatched"})
                continue
            args: dict[str, Any] = {
                "skill_id": plan.skill_id,
                "route": plan.route,
                "order": order,
                "wait_until": "completed",
                "confidence": plan.confidence,
                "text": part,
            }
            if plan.route == "action" and plan.skill_id != "emergency_stop":
                args["duration_ms"] = 800 if not plan.skill_id.startswith("turn_") else 600
            if plan.route == "face":
                args["duration_ms"] = 3000
            tool_calls.append(ToolCall(tool=_tool_for_skill(plan.skill_id), args=args))
            agent_steps.append({"order": order, "text": part, "skill_id": plan.skill_id, "route": plan.route, "planner": plan.planner})
        envelope.tool_calls = tool_calls
        envelope.agent_steps = agent_steps
        if tool_calls:
            envelope.reasoning_summary = f"Generated {len(tool_calls)} structured tool call(s) from transcript."
        else:
            envelope.reasoning_summary = "No allowed voice skill matched the transcript."
        envelope.t_agent_end = time.time()
        return envelope


def run_react_agent(*, envelope: DecisionEnvelope, base_dir: Path, router_config: dict[str, Any] | None) -> DecisionEnvelope:
    return RuleReactAgent(base_dir=base_dir, router_config=router_config).run(envelope)
