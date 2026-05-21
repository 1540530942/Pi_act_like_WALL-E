from skills.base import ISkill, SkillContext
from skills.vision.common import validate_look_params


class LookUpSkill(ISkill):
    id = "look.up"
    name = "向上看"

    def schema(self) -> dict:
        return {"step_deg": "float > 0"}

    def validate(self, params: dict) -> dict:
        return validate_look_params(params)

    def execute(self, params: dict, ctx: SkillContext) -> dict:
        return ctx.gimbal_driver.look_up(params["step_deg"])
