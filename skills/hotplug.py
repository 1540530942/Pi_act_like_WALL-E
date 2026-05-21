from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

from skills.base import ISkill
from skills.registry import SkillRegistry
from skills.schema import validate_object_schema


HOTPLUG_SPEC_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["skills"],
    "properties": {
        "skills": {"type": "array"},
    },
}


SKILL_ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["module", "class"],
    "properties": {
        "module": {"type": "string"},
        "class": {"type": "string"},
    },
}


class SkillHotplugManager:
    """Support hot-plug add/update/remove of skills from a JSON spec.

    Spec example:
    {
      "skills": [
        {"module": "skills.movement.forward", "class": "ForwardSkill"}
      ]
    }
    """

    def __init__(self, registry: SkillRegistry):
        self.registry = registry

    @staticmethod
    def _load_skill(module_name: str, class_name: str) -> ISkill:
        module = importlib.import_module(module_name)
        module = importlib.reload(module)
        cls = getattr(module, class_name)
        skill = cls()
        if not isinstance(skill, ISkill):
            raise TypeError(f"{module_name}.{class_name} is not an ISkill implementation")
        return skill

    def add_or_update(self, module_name: str, class_name: str) -> dict[str, Any]:
        skill = self._load_skill(module_name, class_name)
        existed = self.registry.update(skill)
        return {"action": "updated" if existed else "added", "skill_id": skill.id}

    def remove(self, skill_id: str) -> dict[str, Any]:
        removed = self.registry.unregister(skill_id)
        return {"action": "removed" if removed else "not_found", "skill_id": skill_id}

    def reload_from_file(self, spec_file: str) -> dict[str, Any]:
        path = Path(spec_file)
        data = json.loads(path.read_text(encoding="utf-8"))

        validate_object_schema(HOTPLUG_SPEC_SCHEMA, data)
        skills = data.get("skills", [])
        if not isinstance(skills, list):
            raise ValueError("skills must be a list")

        loaded = []
        for item in skills:
            validate_object_schema(SKILL_ITEM_SCHEMA, item)
            loaded.append(self.add_or_update(item["module"], item["class"]))
        return {"loaded": loaded}
