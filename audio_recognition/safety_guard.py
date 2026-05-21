from __future__ import annotations

import time

try:
    from .envelope import DecisionEnvelope, TaskStep
except ImportError:
    from envelope import DecisionEnvelope, TaskStep


NEGATIVE_WORDS = ("不要", "别", "不许", "不用", "不要去", "别去")
EMERGENCY_WORDS = ("急停", "停止", "停下", "停车", "刹车", "别动", "不要动", "stop", "e-stop")
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


def run_safety_guard(envelope: DecisionEnvelope) -> DecisionEnvelope:
    envelope.t_safety = time.time()
    transcript = envelope.transcript or ""
    result = {"allowed": True, "reason": "", "checks": []}
    if _contains_any(transcript, EMERGENCY_WORDS):
        envelope.tasks = [
            TaskStep(skill_id="emergency_stop", route="action", order=0, wait_until="accepted", status="pending")
        ]
        result.update({"allowed": True, "reason": "emergency_stop_detected", "priority": "highest"})
        envelope.safety_result = result
        return envelope
    if _contains_any(transcript, NEGATIVE_WORDS):
        envelope.tasks = [_reject_task(task, "negative_instruction_detected") for task in envelope.tasks]
        result.update({"allowed": False, "reason": "negative_instruction_detected"})
        envelope.safety_result = result
        return envelope
    movement_tasks = [task for task in envelope.tasks if task.skill_id.startswith(MOVEMENT_PREFIXES)]
    if len(movement_tasks) > MAX_SEQUENCE_ACTIONS:
        allowed_ids = {task.task_id for task in sorted(movement_tasks, key=lambda item: item.order)[:MAX_SEQUENCE_ACTIONS]}
        envelope.tasks = [
            task if (not task.skill_id.startswith(MOVEMENT_PREFIXES) or task.task_id in allowed_ids) else _reject_task(task, "too_many_movement_tasks")
            for task in envelope.tasks
        ]
        result["checks"].append("movement_sequence_clipped")
    total_duration = sum(int(task.duration_ms or 0) for task in envelope.tasks if task.status != "rejected")
    if total_duration > MAX_TOTAL_DURATION_MS:
        envelope.tasks = [_reject_task(task, "total_duration_exceeded") for task in envelope.tasks]
        result.update({"allowed": False, "reason": "total_duration_exceeded"})
    low_confidence = any(float(call.args.get("confidence") or 1.0) < 0.65 for call in envelope.validated_tool_calls if call.status == "validated")
    if low_confidence:
        envelope.needs_confirmation = True
        result["checks"].append("low_confidence_confirmation_required")
    envelope.safety_result = result
    return envelope
