from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class DisplaySettingsDTO:
    """User-tunable settings (edited from the Settings page)."""

    limit_per_account: int = 15

    manual_refresh: bool = True
    throttle_seconds: int = 5

    show_preview: bool = True
    neural_background: bool = True

    notifications: bool = True
    notify_minutes: int = 2

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> DisplaySettingsDTO:
        allowed = {f: data[f] for f in cls.__dataclass_fields__ if f in data}
        return cls(**allowed)  # type: ignore[arg-type]
