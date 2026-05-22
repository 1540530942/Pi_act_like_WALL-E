from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

import requests

try:
    from .envelope import DecisionEnvelope, ToolCall
    from .face_router import is_face_skill
    from .planner import build_task_planner
except ImportError:
    from envelope import DecisionEnvelope, ToolCall
    from face_router import is_face_skill
    from planner import build_task_planner


SEQUENCE_SPLIT_PATTERN = re.compile(r"(?:\u7136\u540e|\u518d|\u63a5\u7740|\u4e4b\u540e|\uff0c|,|;|\uff1b)")
DEFAULT_LLM_ENDPOINT = "https://www.wangyutang.cn/common/api/llm/chat"
DEFAULT_LLM_MODEL = "qwen3.5-9b"


def _tool_for_skill(skill_id: str) -> str:
    if skill_id == "emergency_stop":
        return "emergency_stop"
    return "dispatch_face" if is_face_skill(skill_id) else "dispatch_action"


class RuleReactAgent:
    """Legacy compatibility shim. Real execution builds LlmReactAgent only."""

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
        envelope.reasoning_summary = f"Generated {len(tool_calls)} structured tool call(s) from transcript." if tool_calls else "No allowed voice skill matched the transcript."
        envelope.t_agent_end = time.time()
        return envelope


class LlmReactAgent(RuleReactAgent):
    def __init__(self, *, base_dir: Path, router_config: dict[str, Any] | None):
        super().__init__(base_dir=base_dir, router_config=router_config)
        agent_config = dict((router_config or {}).get("react_agent") or {})
        llm_config = dict(agent_config.get("llm") or {})
        self.endpoint = str(llm_config.get("endpoint") or os.getenv("AUDIO_REACT_LLM_ENDPOINT") or DEFAULT_LLM_ENDPOINT).strip()
        self.model = str(llm_config.get("model") or os.getenv("AUDIO_REACT_LLM_MODEL") or DEFAULT_LLM_MODEL).strip()
        self.timeout = float(llm_config.get("timeout_seconds") or os.getenv("AUDIO_REACT_LLM_TIMEOUT_SECONDS") or 90)
        self.verify_ssl = bool(llm_config.get("verify_ssl", True))
        self.retries = int(llm_config.get("retries") or os.getenv("AUDIO_REACT_LLM_RETRIES") or 2)
        if not self.endpoint or not self.model:
            raise RuntimeError("react_agent.llm.endpoint and model are required")

    def _system_prompt(self) -> str:
        allowed = {
            "dispatch_action": [
                "move_forward", "move_backward", "move_left", "move_right",
                "turn_left", "turn_right", "look_left", "look_right",
                "look_up", "look_down", "reset_pose",
            ],
            "dispatch_face": [
                "face_neutral", "face_happy", "face_joy", "face_sad",
                "face_angry", "face_speak", "face_mouth_open", "face_blink", "face_reset",
            ],
            "emergency_stop": ["emergency_stop"],
            "finish": ["finish"],
        }
        schema = {
            "protocol_version": "react_v1_single_tool",
            "reasoning_summary": "short Chinese summary, no hidden chain-of-thought",
            "tool_call": {
                "tool": "dispatch_action | dispatch_face | emergency_stop | finish",
                "args": {
                    "skill_id": "one allowed skill id, omitted for finish",
                    "duration_ms": 800,
                    "wait_until": "completed",
                    "confidence": 0.9,
                    "text": "exact minimal source fragment for this one step",
                },
            },
            "final": "only for finish",
        }
        return (
            "Output only compact JSON. protocol_version=react_v1_single_tool. No Thinking Process. One ReAct turn equals one tool_call. "
            "After a completed/dry_run tool result, choose the next unfinished positive command; output finish when done. "
            "Negated fragments such as \u4e0d\u8981/\u522b/\u4e0d\u8bb8/\u4e0d\u7528 do not create that action and do not cancel previous completed actions. "
            "\u505c\u6b62/\u6025\u505c/\u522b\u52a8/\u4e0d\u8981\u52a8 -> emergency_stop. "
            "\u5f80\u524d\u8d70=move_forward; \u5f80\u540e\u8d70=move_backward; \u62ac\u5934\u770b=look_up; \u4f4e\u5934\u770b=look_down. "
            "tool_call.args.text must be the minimal source fragment for only this step. "
            f"Allowed: {json.dumps(allowed, ensure_ascii=False)}. "
            f"Schema: {json.dumps(schema, ensure_ascii=False)}."
        )

    def _parse_response(self, text: str) -> dict[str, Any]:
        stripped = text.strip()
        if "</think>" in stripped:
            stripped = stripped.split("</think>", 1)[1].strip()
        if stripped.startswith("```"):
            stripped = "\n".join(line for line in stripped.splitlines() if not line.startswith("```")).strip()
        start = stripped.find("{")
        if start >= 0:
            decoder = json.JSONDecoder()
            data, _ = decoder.raw_decode(stripped[start:])
        else:
            data = json.loads(stripped)
        if not isinstance(data, dict):
            raise ValueError("LLM response is not a JSON object")
        return data

    def _post(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": 1200,
            "response_format": {"type": "json_object"},
            "chat_template_kwargs": {"enable_thinking": False},
        }
        response = None
        last_error: Exception | None = None
        for attempt in range(max(self.retries, 1)):
            try:
                response = requests.post(self.endpoint, json=payload, timeout=self.timeout, verify=self.verify_ssl)
                response.raise_for_status()
                break
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt + 1 >= max(self.retries, 1):
                    raise
                time.sleep(0.5 * (attempt + 1))
        if response is None:
            raise RuntimeError(str(last_error or "empty llm response"))
        raw = response.json()
        text = str(raw.get("text") or "")
        if not text:
            choices = (raw.get("raw") or {}).get("choices") if isinstance(raw.get("raw"), dict) else raw.get("choices")
            if choices:
                text = str(((choices[0] or {}).get("message") or {}).get("content") or "")
        data = self._parse_response(text)
        data["_raw"] = raw
        return data

    def run_turn(self, envelope: DecisionEnvelope, messages: list[dict[str, Any]], turn: int) -> ToolCall:
        data = self._post(messages)
        if data.get("type") == "finish":
            return ToolCall(tool="finish", args={"final": data.get("final", "done"), "order": turn, "wait_until": "completed", "confidence": 1.0})
        item = data.get("tool_call")
        if data.get("type") == "tool_call" and isinstance(item, dict):
            item = {"tool": item.get("tool") or item.get("name"), "args": item.get("args") or item.get("arguments") or {}}
        if item is None and isinstance(data.get("tool_calls"), list):
            calls = data.get("tool_calls") or []
            if len(calls) != 1:
                raise ValueError("LLM must return exactly one tool_call per turn")
            item = calls[0]
        if not isinstance(item, dict):
            raise ValueError("LLM response missing tool_call")
        args = dict(item.get("args") or {})
        args.setdefault("order", turn)
        args.setdefault("wait_until", "completed")
        args.setdefault("confidence", 0.9)
        call = ToolCall(tool=str(item.get("tool") or ""), args=args)
        envelope.reasoning_summary = str(data.get("reasoning_summary") or envelope.reasoning_summary)
        envelope.raw.setdefault("react_llm_turns", []).append({"turn": turn, "model": self.model, "raw": data.get("_raw", {})})
        return call

    def run(self, envelope: DecisionEnvelope) -> DecisionEnvelope:
        envelope.t_agent_start = time.time()
        try:
            call = self.run_turn(
                envelope,
                [
                    {"role": "system", "content": self._system_prompt()},
                    {"role": "user", "content": f"/no_think\n\u7528\u6237\u539f\u59cb\u6307\u4ee4: {envelope.transcript}"},
                ],
                1,
            )
            envelope.tool_calls = [call]
            envelope.agent_steps = [{"planner": "llm", "model": self.model, "tool_call_count": 1}]
        except Exception as exc:  # noqa: BLE001 - no rule fallback in llm mode
            envelope.tool_calls = []
            envelope.reasoning_summary = "LLM ReAct agent failed; no tool calls generated."
            envelope.add_error("react_agent", str(exc), {"mode": "llm", "model": self.model})
        envelope.t_agent_end = time.time()
        return envelope


def build_llm_react_agent(*, base_dir: Path, router_config: dict[str, Any] | None) -> LlmReactAgent:
    router_config = router_config or {}
    agent_config = dict(router_config.get("react_agent") or {})
    mode = str(agent_config.get("mode") or os.getenv("AUDIO_REACT_AGENT_MODE") or "").strip().lower()
    if mode != "llm":
        raise RuntimeError("real ReAct execution requires react_agent.mode=llm; rule and hybrid are disabled")
    return LlmReactAgent(base_dir=base_dir, router_config=router_config)


def run_react_agent(*, envelope: DecisionEnvelope, base_dir: Path, router_config: dict[str, Any] | None) -> DecisionEnvelope:
    try:
        return build_llm_react_agent(base_dir=base_dir, router_config=router_config).run(envelope)
    except Exception as exc:  # noqa: BLE001 - no rule fallback
        envelope.tool_calls = []
        envelope.reasoning_summary = "LLM ReAct agent failed; no rule fallback is allowed."
        envelope.add_error("react_agent", str(exc), {"mode_required": "llm"})
        return envelope
