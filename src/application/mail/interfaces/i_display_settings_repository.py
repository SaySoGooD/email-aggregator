from abc import ABC, abstractmethod

from src.application.mail.dto.display_settings_dto import DisplaySettingsDTO


class IDisplaySettingsRepository(ABC):
    """Persists the user's display/filter settings."""

    @abstractmethod
    def load(self) -> DisplaySettingsDTO: ...

    @abstractmethod
    def save(self, settings: DisplaySettingsDTO) -> None: ...
