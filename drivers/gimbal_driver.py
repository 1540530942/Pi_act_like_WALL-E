from __future__ import annotations


class GimbalDriver:
    def __init__(self, pan_min: float = -60.0, pan_max: float = 60.0, tilt_min: float = -45.0, tilt_max: float = 45.0):
        self.pan_min = pan_min
        self.pan_max = pan_max
        self.tilt_min = tilt_min
        self.tilt_max = tilt_max
        self.pan = 0.0
        self.tilt = 0.0

    @staticmethod
    def _clamp(value: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, value))

    def look_up(self, step_deg: float) -> dict:
        self.tilt = self._clamp(self.tilt + step_deg, self.tilt_min, self.tilt_max)
        return {"action": "look_up", "tilt": self.tilt, "hardware_ack": True}

    def look_down(self, step_deg: float) -> dict:
        self.tilt = self._clamp(self.tilt - step_deg, self.tilt_min, self.tilt_max)
        return {"action": "look_down", "tilt": self.tilt, "hardware_ack": True}

    def look_left(self, step_deg: float) -> dict:
        self.pan = self._clamp(self.pan - step_deg, self.pan_min, self.pan_max)
        return {"action": "look_left", "pan": self.pan, "hardware_ack": True}

    def look_right(self, step_deg: float) -> dict:
        self.pan = self._clamp(self.pan + step_deg, self.pan_min, self.pan_max)
        return {"action": "look_right", "pan": self.pan, "hardware_ack": True}
