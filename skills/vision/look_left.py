from skills.base import ISkill, SkillContext
from skills.vision.common import validate_look_params


class LookLeftSkill(ISkill):
    id = "look.left"
    name = "向左看"

    def schema(self) -> dict:
        return {"step_deg": "float > 0"}

    def validate(self, params: dict) -> dict:
        return validate_look_params(params)

    def execute(self, params: dict, ctx: SkillContext) -> dict:
        return ctx.gimbal_driver.look_left(params["step_deg"])
