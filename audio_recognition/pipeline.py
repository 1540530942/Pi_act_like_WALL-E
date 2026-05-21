from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    from .contracts import PlannedTask
    from .dispatcher import dispatch_envelope
    from .envelope import DecisionEnvelope
    from .executors import execute_planned_task
    from .planner import build_task_planner
    from .react_agent import run_react_agent
    from .safety_guard import run_safety_guard
    from .tool_validator import validate_tool_calls
except ImportError:
    from contracts import PlannedTask
    from dispatcher import dispatch_envelope
    from envelope import DecisionEnvelope
    from executors import execute_planned_task
    from planner import build_task_planner
    from react_agent import run_react_agent
    from safety_guard import run_safety_guard
    from tool_validator import validate_tool_calls


def resolve_catalog_path(base_dir: Path, router_config: dict[str, Any] | None) -> Path:
    router_config = router_config or {}
    catalog_path = Path(str(router_config.get("skill_catalog") or "../action_move/skill_catalog.json"))
    if not catalog_path.is_absolute():
        catalog_path = (base_dir / catalog_path).resolve()
    return catalog_path


def plan_transcript(base_dir: Path, text: str, router_config: dict[str, Any] | None) -> PlannedTask | None:
    catalog_path = resolve_catalog_path(base_dir, router_config)
    planner = build_task_planner(router_config, catalog_path)
    return planner.plan(text)


def route_transcript(
    *,
    base_dir: Path,
    text: str,
    router_config: dict[str, Any] | None,
    cloud_config: dict[str, Any] | None,
    route_action: bool,
    source: str,
    device_id: str = "turbopi-01",
) -> dict[str, Any]:
    envelope = decide_transcript(
        base_dir=base_dir,
        text=text,
        router_config=router_config,
        cloud_config=cloud_config,
        dispatch_mode="cloud_queue" if route_action else "dry_run",
        source=source,
        device_id=device_id,
    )
    plan = plan_transcript(base_dir, text, router_config) if text else None
    first_result = envelope.dispatch_results[0].get("result", {}) if envelope.dispatch_results else {}
    execution = first_result if isinstance(first_result, dict) else {}
    return {
        "plan": plan.model_dump() if plan else None,
        "skill_id": plan.skill_id if plan else "",
        "action_task": execution.get("action_task"),
        "face_task": execution.get("face_task"),
        "action_error": execution.get("action_error", ""),
        "face_error": execution.get("face_error", ""),
        "envelope": envelope.model_dump(),
    }


def decide_transcript(
    *,
    base_dir: Path,
    text: str,
    router_config: dict[str, Any] | None,
    cloud_config: dict[str, Any] | None,
    dispatch_mode: str,
    source: str,
    device_id: str = "turbopi-01",
    raw: dict[str, Any] | None = None,
) -> DecisionEnvelope:
    envelope = DecisionEnvelope(device_id=device_id, source=source, transcript=str(text or "").strip(), raw=raw or {})
    if not envelope.transcript:
        envelope.reasoning_summary = "Empty transcript."
        return envelope
    envelope = run_react_agent(envelope=envelope, base_dir=base_dir, router_config=router_config)
    envelope = validate_tool_calls(envelope)
    envelope = run_safety_guard(envelope)
    envelope = dispatch_envelope(envelope, cloud_config=cloud_config or {}, source=source, dispatch_mode=dispatch_mode)
    return envelope


def transcribe_audio_path(
    *,
    base_dir: Path,
    wav_path: str | Path,
    provider: Any,
    router_config: dict[str, Any] | None,
) -> dict[str, Any]:
    transcript = provider.transcribe(wav_path)
    text = str(transcript.get("text") or "").strip()
    plan = plan_transcript(base_dir, text, router_config) if text else None
    return {
        "text": text,
        "raw": transcript.get("raw", {}),
        "error": str(transcript.get("error") or ""),
        "plan": plan.model_dump() if plan else None,
        "skill_id": plan.skill_id if plan else "",
    }
