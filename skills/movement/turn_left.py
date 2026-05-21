from skills.base import ISkill, SkillContext
from skills.movement.common import validate_turn_params


class TurnLeftSkill(ISkill):
    id = "turn.left"
    name = "左转"

    def schema(self) -> dict:
        return {"angle_deg": "float > 0", "speed": "0~1"}

    def validate(self, params: dict) -> dict:
        return validate_turn_params(params)

    def execute(self, params: dict, ctx: SkillContext) -> dict:
        return ctx.motor_driver.turn_left(params["angle_deg"], params["speed"])
