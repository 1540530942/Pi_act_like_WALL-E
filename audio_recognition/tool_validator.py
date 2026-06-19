from __future__ import annotations

import time
from typing import Any

try:
    from .envelope import DecisionEnvelope, TaskStep, ToolCall
    from .face_router import FACE_SKILL_IDS
    from .voice_intents import ALLOWED_VOICE_SKILL_IDS
except ImportError:
    from envelope import DecisionEnvelope, TaskStep, ToolCall
    from face_router import FACE_SKILL_IDS
    from voice_intents import ALLOWED_VOICE_SKILL_IDS


ACTION_SKILLS = ALLOWED_VOICE_SKILL_IDS - FACE_SKILL_IDS
ALLOWED_TOOLS = {"dispatch_action", "dispatch_face", "emergency_stop", "camera_snapshot", "get_robot_state", "ask_confirmation", "finish"}
MAX_MOVE_DURATION_MS = 1000
MAX_TURN_DURATION_MS = 800
MAX_FACE_DURATION_MS = 5000


def _reject(call: ToolCall, reason: str) -> ToolCall:
    updated = call.model_copy(deep=True)
    updated.status = "rejected"
    updated.error = reason
    return updated


def _validate_duration(skill_id: str, duration: int | None) -> tuple[int | None, str]:
    if duration is None:
        return None, ""
    try:
        value = int(duration)
    except (TypeError, ValueError):
        return None, "invalid_duration_ms"
    if skill_id.startswith("turn_") and value > MAX_TURN_DURATION_MS:
        return MAX_TURN_DURATION_MS, "duration_clipped"
    if skill_id.startswith("move_") and value > MAX_MOVE_DURATION_MS:
        return MAX_MOVE_DURATION_MS, "duration_clipped"
    if skill_id.startswith("face_") and value > MAX_FACE_DURATION_MS:
        return MAX_FACE_DURATION_MS, "duration_clipped"
    if value < 0:
        return None, "invalid_duration_ms"
    return value, ""


def validate_tool_calls(envelope: DecisionEnvelope) -> DecisionEnvelope:
    envelope.t_validate = time.time()
    validated: list[ToolCall] = []
    tasks: list[TaskStep] = []
    for call in envelope.tool_calls:
        if call.tool not in ALLOWED_TOOLS:
            rejected = _reject(call, "unsupported_tool")
            envelope.errors.append({"stage": "validator", "message": rejected.error, "tool_call": rejected.model_dump(), "t": time.time()})
            validated.append(rejected)
            continue
        args: dict[str, Any] = dict(call.args)
        skill_id = str(args.get("skill_id") or "")
        if call.tool == "dispatch_action" and skill_id not in ACTION_SKILLS:
            rejected = _reject(call, "unsupported_action_skill")
            envelope.errors.append({"stage": "validator", "message": rejected.error, "tool_call": rejected.model_dump(), "t": time.time()})
            validated.append(rejected)
            continue
        if call.tool == "dispatch_face" and skill_id not in FACE_SKILL_IDS:
            rejected = _reject(call, "unsupported_face_skill")
            envelope.errors.append({"stage": "validator", "message": rejected.error, "tool_call": rejected.model_dump(), "t": time.time()})
            validated.append(rejected)
            continue
        if call.tool == "emergency_stop":
            skill_id = "emergency_stop"
            args["skill_id"] = skill_id
        if call.tool in {"dispatch_action", "dispatch_face", "emergency_stop"}:
            duration, duration_note = _validate_duration(skill_id, args.get("duration_ms"))
            if duration_note == "invalid_duration_ms":
                rejected = _reject(call, duration_note)
                envelope.errors.append({"stage": "validator", "message": rejected.error, "tool_call": rejected.model_dump(), "t": time.time()})
                validated.append(rejected)
                continue
            if duration is not None:
                args["duration_ms"] = duration
            route = "face" if call.tool == "dispatch_face" else "action"
            accepted = call.model_copy(deep=True)
            accepted.args = args
            accepted.status = "validated"
            if duration_note:
                accepted.result["validator_note"] = duration_note
            validated.append(accepted)
            tasks.append(
                TaskStep(
                    task_id=accepted.call_id.replace("call_", "task_"),
                    skill_id=skill_id,
                    route=route,
                    order=int(args.get("order") or len(tasks) + 1),
                    duration_ms=args.get("duration_ms"),
                    wait_until=str(args.get("wait_until") or "completed"),
                )
            )
            continue
        accepted = call.model_copy(deep=True)
        accepted.status = "validated"
        validated.append(accepted)
    envelope.validated_tool_calls = validated
    envelope.tasks = tasks
    return envelope
