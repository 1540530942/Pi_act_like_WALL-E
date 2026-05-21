from __future__ import annotations


def validate_look_params(params: dict) -> dict:
    step_deg = float(params.get("step_deg", 10.0))
    if step_deg <= 0:
        raise ValueError("step_deg must be > 0")
    return {"step_deg": step_deg}
