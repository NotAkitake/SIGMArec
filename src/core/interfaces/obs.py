"""
OBS integration interfaces.
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from src.obs.videosettings import OBSVideoSettings


class IOBSEventHandler(ABC):
    """Interface for handling OBS events."""

    @abstractmethod
    def on_recording_started(self) -> None:
        """Handle recording start event."""

    @abstractmethod
    def on_recording_stopped(self, output_path: str) -> None:
        """Handle recording stop event."""


class IOBSController(ABC):
    """Interface for OBS control operations."""

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Check if connected to OBS."""

    @property
    @abstractmethod
    def recording_active(self) -> bool:
        """Check if recording is active."""

    @abstractmethod
    def start_recording(self) -> None:
        """Start recording."""

    @abstractmethod
    def stop_recording(self) -> None:
        """Stop recording."""

    @abstractmethod
    def get_video_settings(self) -> Optional["OBSVideoSettings"]:
        """Get current video settings."""

    @abstractmethod
    def get_game_video_settings(self) -> Optional["OBSVideoSettings"]:
        """Get current game video settings."""

    @abstractmethod
    def set_current_scene(self, scene_name: str) -> None:
        """Switch to specified scene."""

    @abstractmethod
    def get_current_scene(self) -> Optional[str]:
        """Get current scene name."""

    @abstractmethod
    def get_scene_list(self) -> List[str]:
        """Get list of available scenes."""

    @abstractmethod
    def set_video_settings(
        self,
        obssettings: "OBSVideoSettings",
    ) -> None:
        """Set video settings."""

    @abstractmethod
    def register_event_handler(self, handler: IOBSEventHandler) -> None:
        """Register an event handler."""
