from __future__ import annotations

from threading import RLock
from typing import Any
from uuid import uuid4

from skills.base import ISkill, SkillContext


class SkillRegistry:
    def __init__(self, ctx: SkillContext):
        self._ctx = ctx
        self._skills: dict[str, ISkill] = {}
        self._lock = RLock()

    def register(self, skill: ISkill) -> None:
        with self._lock:
            self._skills[skill.id] = skill

    def register_many(self, skills: list[ISkill]) -> None:
        with self._lock:
            for skill in skills:
                self._skills[skill.id] = skill

    def unregister(self, skill_id: str) -> bool:
        with self._lock:
            return self._skills.pop(skill_id, None) is not None

    def update(self, skill: ISkill) -> bool:
        with self._lock:
            existed = skill.id in self._skills
            self._skills[skill.id] = skill
            return existed

    def list_skills(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "id": skill.id,
                    "name": skill.name,
                    "schema": skill.schema(),
                }
                for skill in self._skills.values()
            ]

    def execute_skill(self, skill_id: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        params = params or {}
        task_id = str(uuid4())

        with self._lock:
            skill = self._skills.get(skill_id)

        if skill is None:
            return {
                "task_id": task_id,
                "accepted": False,
                "message": f"Unknown skill: {skill_id}",
                "hardware_ack": False,
            }

        try:
            normalized = skill.validate(params)
            result = skill.execute(normalized, self._ctx)
            return {
                "task_id": task_id,
                "accepted": True,
                "message": "ok",
                "hardware_ack": bool(result.get("hardware_ack", True)),
                "result": result,
            }
        except Exception as exc:
            return {
                "task_id": task_id,
                "accepted": False,
                "message": str(exc),
                "hardware_ack": False,
            }
