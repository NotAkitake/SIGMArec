"""
Recording management interfaces.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Tuple

from src.games import Game


class IRecordingStorage(ABC):
    """Interface for recording storage operations."""

    @abstractmethod
    def organize_recording(self, file_path: Path, game: Optional[Game]) -> Path:
        """Organize a recording file into the appropriate location."""

    @abstractmethod
    def generate_filename(self, game: Optional[Game]) -> str:
        """Generate a filename for a recording."""

    @abstractmethod
    def create_thumbnail(self, video_path: Path) -> Optional[Path]:
        """Create a thumbnail for a video file."""


class IRecordingManager(ABC):
    """Interface for recording management."""

    @abstractmethod
    def handle_recording_completed(self, output_path: str) -> None:
        """Handle a completed recording."""

    @abstractmethod
    def save_lastplay(self, game: Optional[Game]) -> Tuple[bool, str]:
        """Save the current lastplay."""

    @abstractmethod
    def has_lastplay(self) -> bool:
        """Check if lastplay is available."""
