from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class DisplaySettingsDTO:
    """User-tunable settings (edited from the Settings page)."""

    limit_per_account: int = 15  # messages fetched per account

    manual_refresh: bool = True  # if True, sync only on the Refresh button
    throttle_seconds: int = 5  # min seconds between auto-syncs when not manual

    show_preview: bool = True  # show the body-snippet preview after the subject
    neural_background: bool = True  # animate the neural backdrop

    notifications: bool = True  # desktop notification on new mail
    notify_minutes: int = 2  # how often to poll for new mail (minutes)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> DisplaySettingsDTO:
        allowed = {f: data[f] for f in cls.__dataclass_fields__ if f in data}
        return cls(**allowed)  # type: ignore[arg-type]
