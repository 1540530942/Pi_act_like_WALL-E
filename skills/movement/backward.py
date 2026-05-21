from skills.base import ISkill, SkillContext
from skills.movement.common import validate_distance_params


class BackwardSkill(ISkill):
    id = "move.backward"
    name = "后退"

    def schema(self) -> dict:
        return {"distance_cm": "float > 0", "speed": "0~1"}

    def validate(self, params: dict) -> dict:
        return validate_distance_params(params)

    def execute(self, params: dict, ctx: SkillContext) -> dict:
        return ctx.motor_driver.move_backward(params["distance_cm"], params["speed"])
