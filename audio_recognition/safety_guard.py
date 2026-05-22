from __future__ import annotations

import time

try:
    from .envelope import DecisionEnvelope, TaskStep
except ImportError:
    from envelope import DecisionEnvelope, TaskStep


NEGATIVE_WORDS = ("\u4e0d\u8981", "\u522b", "\u4e0d\u8bb8", "\u4e0d\u7528", "\u4e0d\u8981\u53bb", "\u522b\u53bb")
EMERGENCY_WORDS = ("\u6025\u505c", "\u505c\u6b62", "\u505c\u4e0b", "\u505c\u8f66", "\u5239\u8f66", "\u522b\u52a8", "\u4e0d\u8981\u52a8", "stop", "e-stop")
MOVEMENT_PREFIXES = ("move_", "turn_")
MAX_SEQUENCE_ACTIONS = 3
MAX_TOTAL_DURATION_MS = 10000


def _contains_any(text: str, words: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(word.lower() in lowered for word in words)


def _reject_task(task: TaskStep, reason: str) -> TaskStep:
    updated = task.model_copy(deep=True)
    updated.status = "rejected"
    updated.error = reason
    return updated


def run_safety_guard_for_task(envelope: DecisionEnvelope, task: TaskStep) -> TaskStep:
    envelope.t_safety = time.time()
    result = dict(envelope.safety_result or {"allowed": True, "reason": "", "checks": []})
    result.setdefault("checks", [])
    matching_call = next((call for call in envelope.validated_tool_calls if call.call_id.replace("call_", "task_") == task.task_id), None)
    fragment = str((matching_call.args if matching_call else {}).get("text") or "")
    if task.skill_id == "emergency_stop":
        result.update({"allowed": True, "reason": "emergency_stop_detected", "priority": "highest"})
        envelope.safety_result = result
        return task
    if _contains_any(fragment, NEGATIVE_WORDS):
        updated = _reject_task(task, "negative_instruction_detected")
        result["checks"].append("negative_instruction_detected")
        result.update({"allowed": False, "reason": "negative_instruction_detected"})
        envelope.safety_result = result
        return updated
    movement_tasks = [item for item in envelope.tasks if item.status != "rejected" and item.skill_id.startswith(MOVEMENT_PREFIXES)]
    if len(movement_tasks) > MAX_SEQUENCE_ACTIONS:
        updated = _reject_task(task, "too_many_movement_tasks")
        result["checks"].append("movement_sequence_clipped")
        result.update({"allowed": False, "reason": "too_many_movement_tasks"})
        envelope.safety_result = result
        return updated
    total_duration = sum(int(item.duration_ms or 0) for item in envelope.tasks if item.status != "rejected")
    if total_duration > MAX_TOTAL_DURATION_MS:
        updated = _reject_task(task, "total_duration_exceeded")
        result.update({"allowed": False, "reason": "total_duration_exceeded"})
        envelope.safety_result = result
        return updated
    if matching_call and float(matching_call.args.get("confidence") or 1.0) < 0.65:
        updated = _reject_task(task, "low_confidence_confirmation_required")
        envelope.needs_confirmation = True
        result["checks"].append("low_confidence_confirmation_required")
        result.update({"allowed": False, "reason": "low_confidence_confirmation_required"})
        envelope.safety_result = result
        return updated
    result.update({"allowed": True, "reason": result.get("reason", "")})
    envelope.safety_result = result
    return task


def run_safety_guard(envelope: DecisionEnvelope) -> DecisionEnvelope:
    envelope.t_safety = time.time()
    if _contains_any(envelope.transcript or "", EMERGENCY_WORDS) and not envelope.tasks:
        envelope.tasks = [TaskStep(skill_id="emergency_stop", route="action", order=0, wait_until="accepted", status="pending")]
    envelope.tasks = [run_safety_guard_for_task(envelope, task) for task in envelope.tasks]
    return envelope
