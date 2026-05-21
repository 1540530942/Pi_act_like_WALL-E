from __future__ import annotations

import time
from typing import Any

try:
    from .envelope import DecisionEnvelope, TaskStep
    from .executors import execute_planned_task
    from .contracts import PlannedTask
except ImportError:
    from envelope import DecisionEnvelope, TaskStep
    from executors import execute_planned_task
    from contracts import PlannedTask


def _planned_from_task(task: TaskStep) -> PlannedTask:
    return PlannedTask(skill_id=task.skill_id, route="face" if task.route == "face" else "action", transcript="", metadata={"task_id": task.task_id})


def dispatch_envelope(
    envelope: DecisionEnvelope,
    *,
    cloud_config: dict[str, Any] | None,
    source: str,
    dispatch_mode: str = "dry_run",
) -> DecisionEnvelope:
    envelope.dispatch_mode = dispatch_mode if dispatch_mode in {"dry_run", "cloud_queue", "local_first"} else "dry_run"
    envelope.t_dispatch_start = time.time()
    results: list[dict[str, Any]] = []
    for task in sorted(envelope.tasks, key=lambda item: item.order):
        if task.status == "rejected":
            results.append({"task_id": task.task_id, "skill_id": task.skill_id, "status": "rejected", "error": task.error})
            continue
        if envelope.dispatch_mode == "dry_run":
            task.status = "completed"
            task.result = {"dry_run": True, "skill_id": task.skill_id, "route": task.route}
            results.append({"task_id": task.task_id, "skill_id": task.skill_id, "status": "dry_run", "result": task.result})
            continue
        task.status = "running"
        execution = execute_planned_task(_planned_from_task(task), envelope.transcript, cloud_config, source)
        if execution.get("action_error") or execution.get("face_error"):
            task.status = "failed"
            task.error = str(execution.get("action_error") or execution.get("face_error") or "")
        else:
            task.status = "completed"
        task.result = execution
        results.append({"task_id": task.task_id, "skill_id": task.skill_id, "status": task.status, "result": execution, "error": task.error})
        if task.status != "completed" or task.skill_id == "emergency_stop":
            break
    envelope.dispatch_results = results
    envelope.t_dispatch_end = time.time()
    return envelope
