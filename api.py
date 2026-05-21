from __future__ import annotations

from typing import Any

from drivers.gimbal_driver import GimbalDriver
from drivers.motor_driver import MotorDriver
from skills.base import SkillContext
from skills.hotplug import SkillHotplugManager
from skills.movement.backward import BackwardSkill
from skills.movement.forward import ForwardSkill
from skills.movement.turn_left import TurnLeftSkill
from skills.movement.turn_right import TurnRightSkill
from skills.registry import SkillRegistry
from skills.vision.look_down import LookDownSkill
from skills.vision.look_left import LookLeftSkill
from skills.vision.look_right import LookRightSkill
from skills.vision.look_up import LookUpSkill


class SkillAPI:
    def __init__(self, registry: SkillRegistry):
        self.registry = registry
        self.hotplug = SkillHotplugManager(registry)

    def list_skills(self) -> list[dict[str, Any]]:
        return self.registry.list_skills()

    def execute_skill(self, skill_id: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.registry.execute_skill(skill_id, params)

    def hotplug_add_or_update(self, module_name: str, class_name: str) -> dict[str, Any]:
        return self.hotplug.add_or_update(module_name, class_name)

    def hotplug_remove(self, skill_id: str) -> dict[str, Any]:
        return self.hotplug.remove(skill_id)

    def hotplug_reload_from_file(self, spec_file: str) -> dict[str, Any]:
        return self.hotplug.reload_from_file(spec_file)


def create_default_api() -> SkillAPI:
    ctx = SkillContext(motor_driver=MotorDriver(), gimbal_driver=GimbalDriver())
    registry = SkillRegistry(ctx)

    registry.register_many(
        [
            ForwardSkill(),
            BackwardSkill(),
            TurnLeftSkill(),
            TurnRightSkill(),
            LookUpSkill(),
            LookDownSkill(),
            LookLeftSkill(),
            LookRightSkill(),
        ]
    )

    return SkillAPI(registry)
