from __future__ import annotations


def validate_distance_params(params: dict) -> dict:
    distance_cm = float(params.get("distance_cm", 5.0))
    speed = float(params.get("speed", 0.5))
    if distance_cm <= 0:
        raise ValueError("distance_cm must be > 0")
    if not 0.0 <= speed <= 1.0:
        raise ValueError("speed must be in [0,1]")
    return {"distance_cm": distance_cm, "speed": speed}


def validate_turn_params(params: dict) -> dict:
    angle_deg = float(params.get("angle_deg", 90.0))
    speed = float(params.get("speed", 0.5))
    if angle_deg <= 0:
        raise ValueError("angle_deg must be > 0")
    if not 0.0 <= speed <= 1.0:
        raise ValueError("speed must be in [0,1]")
    return {"angle_deg": angle_deg, "speed": speed}
