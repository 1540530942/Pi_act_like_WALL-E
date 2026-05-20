from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    from .contracts import PlannedTask
    from .executors import execute_planned_task
    from .planner import build_task_planner
except ImportError:
    from contracts import PlannedTask
    from executors import execute_planned_task
    from planner import build_task_planner


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
) -> dict[str, Any]:
    plan = plan_transcript(base_dir, text, router_config) if text else None
    execution = execute_planned_task(plan, text, cloud_config, source) if route_action else {
        "action_task": None,
        "face_task": None,
        "action_error": "",
        "face_error": "",
    }
    return {
        "plan": plan.model_dump() if plan else None,
        "skill_id": plan.skill_id if plan else "",
        **execution,
    }


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
