# Pi_act_like_WALL-E

A pluggable skill API for Raspberry Pi robot actions (WALL-E-like), including movement and camera/gimbal look controls.

## Skill API

Unified functions:

- `list_skills()`: return all supported skills and parameter schemas.
- `execute_skill(skill_id, params)`: run a skill and return execution result.
- `hotplug_add_or_update(module_name, class_name)`: hot-load or hot-update a skill implementation.
- `hotplug_remove(skill_id)`: hot-unplug a skill from runtime list.
- `hotplug_reload_from_file(spec_file)`: bulk hot-update from JSON spec.

## Supported built-in skills

- `move.forward`: move forward with distance/speed parameters.
- `move.backward`: move backward with distance/speed parameters.
- `turn.left`: turn left with angle/speed parameters.
- `turn.right`: turn right with angle/speed parameters.
- `look.up`: tilt camera up by step angle.
- `look.down`: tilt camera down by step angle.
- `look.left`: pan camera left by step angle.
- `look.right`: pan camera right by step angle.

### Distance scaling support

Movement skills support different scales using:

- `distance_cm`: e.g. 5, 6, 10
- `speed`: range `[0.0, 1.0]`

The driver converts `distance_cm` into runtime duration using `cm_per_sec_at_full_speed`, so commands like **forward 5cm** and **forward 6cm** are supported directly.

## Raspberry Pi mapping

- `drivers/motor_driver.py`: differential motor control abstraction and distance/angle timing conversion.
- `drivers/gimbal_driver.py`: pan/tilt servo abstraction with angle clamp.
- `skills/*`: pluggable skill implementations that only call drivers.
- `api.py`: unified registry, runtime API, and hot-plug APIs.

## Example

```python
from api import create_default_api

api = create_default_api()

print(api.list_skills())
print(api.execute_skill("move.forward", {"distance_cm": 5, "speed": 0.6}))
print(api.execute_skill("move.forward", {"distance_cm": 6, "speed": 0.6}))
print(api.execute_skill("look.left", {"step_deg": 15}))

# hotplug update (reload class implementation)
print(api.hotplug_add_or_update("skills.movement.forward", "ForwardSkill"))

# hotplug remove
print(api.hotplug_remove("look.right"))
```

## Hotplug JSON spec example

```json
{
  "skills": [
    {"module": "skills.movement.forward", "class": "ForwardSkill"},
    {"module": "skills.vision.look_up", "class": "LookUpSkill"}
  ]
}
```

## Why schema is needed

Yes, schema is recommended and now included for hotplug spec validation:

- Prevent invalid runtime hotplug payloads from crashing later stages.
- Keep plugin contracts explicit (`module` + `class` required).
- Improve error messages and API stability when teams add external skills.

Current implementation validates the hotplug JSON structure before loading skill modules.
