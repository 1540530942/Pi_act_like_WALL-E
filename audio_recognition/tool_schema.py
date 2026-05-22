from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    from .face_router import FACE_SKILL_IDS
    from .skill_router import load_catalog
    from .voice_intents import ALLOWED_VOICE_SKILL_IDS
except ImportError:
    from face_router import FACE_SKILL_IDS
    from skill_router import load_catalog
    from voice_intents import ALLOWED_VOICE_SKILL_IDS


DEFAULT_ACTION_SKILLS = [
    "move_forward", "move_backward", "move_left", "move_right",
    "turn_left", "turn_right", "look_left", "look_right",
    "look_up", "look_down", "reset_pose",
]
DEFAULT_FACE_SKILLS = [
    "face_neutral", "face_happy", "face_joy", "face_sad",
    "face_angry", "face_speak", "face_mouth_open", "face_blink", "face_reset",
]


def _catalog_skill_ids(catalog_path: str | Path) -> list[str]:
    try:
        catalog = load_catalog(catalog_path)
    except Exception:
        return []
    skill_ids: list[str] = []
    for item in catalog.get("skills", []):
        skill_id = str(item.get("id") or "").strip()
        if skill_id and skill_id in ALLOWED_VOICE_SKILL_IDS:
            skill_ids.append(skill_id)
    return sorted(set(skill_ids))


def tool_skill_groups(catalog_path: str | Path) -> dict[str, list[str]]:
    skill_ids = _catalog_skill_ids(catalog_path)
    action_skills = [skill_id for skill_id in skill_ids if skill_id not in FACE_SKILL_IDS and skill_id != "emergency_stop"]
    face_skills = [skill_id for skill_id in skill_ids if skill_id in FACE_SKILL_IDS]
    return {
        "action": action_skills or DEFAULT_ACTION_SKILLS,
        "face": face_skills or DEFAULT_FACE_SKILLS,
    }


def build_react_tools_schema(catalog_path: str | Path) -> list[dict[str, Any]]:
    groups = tool_skill_groups(catalog_path)
    common = {
        "order": {"type": "integer", "minimum": 1},
        "wait_until": {"type": "string", "enum": ["accepted", "completed"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "text": {"type": "string"},
    }
    return [
        {
            "type": "function",
            "function": {
                "name": "dispatch_action",
                "description": "Execute one bounded robot motion or pose skill from the configured skill catalog.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "skill_id": {"type": "string", "enum": groups["action"]},
                        "duration_ms": {"type": "integer", "minimum": 0, "maximum": 1000},
                        **common,
                    },
                    "required": ["skill_id"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "dispatch_face",
                "description": "Execute one face expression skill from the configured skill catalog.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "skill_id": {"type": "string", "enum": groups["face"]},
                        "duration_ms": {"type": "integer", "minimum": 0, "maximum": 5000},
                        **common,
                    },
                    "required": ["skill_id"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "camera_snapshot",
                "description": "Capture a camera observation before deciding the next action.",
                "parameters": {"type": "object", "properties": {"reason": {"type": "string"}, **common}, "additionalProperties": False},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_robot_state",
                "description": "Read robot health/state before deciding the next action.",
                "parameters": {"type": "object", "properties": {"reason": {"type": "string"}, **common}, "additionalProperties": False},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "ask_confirmation",
                "description": "Ask the user for confirmation when an instruction is ambiguous.",
                "parameters": {
                    "type": "object",
                    "properties": {"question": {"type": "string"}, "timeout_s": {"type": "integer", "minimum": 1, "maximum": 60}, **common},
                    "required": ["question"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "emergency_stop",
                "description": "Immediately stop robot motion.",
                "parameters": {"type": "object", "properties": {"skill_id": {"type": "string", "enum": ["emergency_stop"]}, **common}, "additionalProperties": False},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "finish",
                "description": "Finish the ReAct loop when all requested positive commands are handled.",
                "parameters": {"type": "object", "properties": {"final": {"type": "string"}}, "additionalProperties": False},
            },
        },
    ]
