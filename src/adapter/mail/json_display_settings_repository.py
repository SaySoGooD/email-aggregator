from __future__ import annotations

import json
from pathlib import Path

from src.application.mail.dto.display_settings_dto import DisplaySettingsDTO
from src.application.mail.interfaces.i_display_settings_repository import (
    IDisplaySettingsRepository,
)


class JsonDisplaySettingsRepository(IDisplaySettingsRepository):
    """Stores display settings as a small JSON file."""

    def __init__(self, path: str, default_limit: int) -> None:
        self._path = Path(path)
        self._default_limit = default_limit

    def load(self) -> DisplaySettingsDTO:
        if not self._path.exists():
            return DisplaySettingsDTO(limit_per_account=self._default_limit)
        with self._path.open(encoding="utf-8") as fh:
            return DisplaySettingsDTO.from_dict(json.load(fh))

    def save(self, settings: DisplaySettingsDTO) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("w", encoding="utf-8") as fh:
            json.dump(settings.to_dict(), fh, ensure_ascii=False, indent=2)
