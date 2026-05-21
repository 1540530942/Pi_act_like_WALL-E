from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class SkillContext:
    motor_driver: Any
    gimbal_driver: Any


class ISkill(ABC):
    id: str
    name: str

    @abstractmethod
    def schema(self) -> dict[str, Any]:
        """Return parameter schema metadata for discovery."""

    @abstractmethod
    def validate(self, params: dict[str, Any]) -> dict[str, Any]:
        """Validate and normalize parameters."""

    @abstractmethod
    def execute(self, params: dict[str, Any], ctx: SkillContext) -> dict[str, Any]:
        """Execute skill against hardware drivers."""
