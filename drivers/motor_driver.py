from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MotorConfig:
    cm_per_sec_at_full_speed: float = 20.0
    deg_per_sec_at_full_speed: float = 180.0


class MotorDriver:
    """Hardware-facing motor abstraction.

    In real Raspberry Pi deployment, replace method bodies with gpiozero/RPi.GPIO control.
    """

    def __init__(self, config: MotorConfig | None = None):
        self.config = config or MotorConfig()

    @staticmethod
    def _clamp_speed(speed: float) -> float:
        return max(0.0, min(1.0, speed))

    def move_forward(self, distance_cm: float, speed: float) -> dict:
        speed = self._clamp_speed(speed)
        duration_s = self._distance_to_duration(distance_cm, speed)
        return {"action": "forward", "distance_cm": distance_cm, "speed": speed, "duration_s": duration_s, "hardware_ack": True}

    def move_backward(self, distance_cm: float, speed: float) -> dict:
        speed = self._clamp_speed(speed)
        duration_s = self._distance_to_duration(distance_cm, speed)
        return {"action": "backward", "distance_cm": distance_cm, "speed": speed, "duration_s": duration_s, "hardware_ack": True}

    def turn_left(self, angle_deg: float, speed: float) -> dict:
        speed = self._clamp_speed(speed)
        duration_s = self._angle_to_duration(angle_deg, speed)
        return {"action": "turn_left", "angle_deg": angle_deg, "speed": speed, "duration_s": duration_s, "hardware_ack": True}

    def turn_right(self, angle_deg: float, speed: float) -> dict:
        speed = self._clamp_speed(speed)
        duration_s = self._angle_to_duration(angle_deg, speed)
        return {"action": "turn_right", "angle_deg": angle_deg, "speed": speed, "duration_s": duration_s, "hardware_ack": True}

    def _distance_to_duration(self, distance_cm: float, speed: float) -> float:
        effective_speed = max(speed, 0.01)
        cm_per_sec = self.config.cm_per_sec_at_full_speed * effective_speed
        return distance_cm / cm_per_sec

    def _angle_to_duration(self, angle_deg: float, speed: float) -> float:
        effective_speed = max(speed, 0.01)
        deg_per_sec = self.config.deg_per_sec_at_full_speed * effective_speed
        return angle_deg / deg_per_sec
