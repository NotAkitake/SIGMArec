"""
Recording manager for handling file operations and organization.

This module handles the recording file management including lastplay system,
organizing into folders, and thumbnail creation.
"""

import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

import mss.tools

from src.audio import SoundService
from src.config.settings import AppSettings
from src.core.interfaces.recording import IRecordingManager
from src.detection.screen_capture import ScreenCaptureService
from src.games.objects import Game


class RecordingManager(IRecordingManager):
    """Manages recording file operations and organization."""

    def __init__(
        self,
        settings: AppSettings,
        sound_service: SoundService,
        screen: ScreenCaptureService,
    ):
        """
        Initialize the recording manager.

        Args:
            settings: Application settings
            sound_service: Sound service for playing sounds
            screen: Screen capture service for creating thumbnails
            obs: OBS controller
        """
        self.settings = settings
        self.sound_service = sound_service
        self.screen = screen
        self._current_lastplay_path: Optional[Path] = None
        self._current_thumbnail_path: Optional[Path] = None

        logging.debug("[Recording] Manager initialized")

    def handle_recording_completed(self, output_path: str) -> None:
        """
        Handle a completed recording.

        Args:
            output_path: Path to the completed recording file
        """
        try:
            self.handle_recording_stopped(output_path)
            logging.debug("[Recording] Recording completed: %s", output_path)
        except Exception as e:
            logging.error("[Recording] Error handling recording completion: %s", e)

    def handle_recording_stopped(self, output_path: str) -> str:
        """
        Handle a recording that just stopped by renaming it to lastplay.

        Args:
            output_path: Original path of the recorded file
            game: Game object if detection was active

        Returns:
            Path to the lastplay file
        """
        original_path = Path(output_path)

        if not original_path.exists():
            logging.warning("[Recording] Recording file not found: %s", output_path)
            return output_path

        recording_dir = original_path.parent

        extension = original_path.suffix
        lastplay_path = recording_dir / f"lastplay{extension}"

        if lastplay_path.exists():
            lastplay_path.unlink()
            logging.debug("[Recording] Removed previous lastplay file")

        shutil.move(str(original_path), str(lastplay_path))
        self._current_lastplay_path = lastplay_path

        if self.settings.save_thumbnails:
            self._create_lastplay_thumbnail(lastplay_path)

        logging.info(
            "Recording renamed to lastplay",
        )

        self.sound_service.play_ready()

        return str(lastplay_path)

    def save_lastplay(self, game: Optional[Game]) -> Tuple[bool, str]:
        """
        Save the current lastplay file with proper organization.

        Args:
            game: Game object for organization

        Returns:
            Tuple of (success, message)
        """
        if not self.has_lastplay():
            return False, "No lastplay file available"

        if not game:
            return False, "No game context available"

        lastplay_path = self._current_lastplay_path

        if not lastplay_path:
            return False, "No lastplay found"

        new_filename = self._generate_filename(lastplay_path, game)

        target_dir = self._get_organized_directory(game)
        target_dir.mkdir(parents=True, exist_ok=True)

        final_path = target_dir / new_filename

        shutil.move(str(lastplay_path), str(final_path))

        if self._current_thumbnail_path and self._current_thumbnail_path.exists():
            self._organize_thumbnail(final_path)

        return True, f"Lastplay saved to '{target_dir.name}/{new_filename}'"

    def has_lastplay(self) -> bool:
        """
        Check if a lastplay file exists.

        Returns:
            True if lastplay file exists and is accessible
        """
        return (
            self._current_lastplay_path is not None
            and self._current_lastplay_path.exists()
        )

    def _generate_filename(
        self, original_path: Path, game: Optional[Game] = None
    ) -> str:
        """
        Generate a new filename for the recording.

        Args:
            original_path: Original file path
            game: Game object if available

        Returns:
            New filename in format: SHORTNAME_YYYY-MM-DD_HH-mm-ss.ext
        """
        now = datetime.now()
        timestamp = now.strftime("%Y-%m-%d_%H-%M-%S")

        if game and hasattr(game, "shortname"):
            prefix = game.shortname
        else:
            prefix = "RECORDING"

        extension = original_path.suffix

        return f"{prefix}_{timestamp}{extension}"

    def _get_organized_directory(self, game: Optional[Game] = None) -> Path:
        """
        Get the target directory for organizing saved recordings.
        Creates game folders in the same directory as lastplay (OBS recording directory).

        Args:
            game: Game object if available

        Returns:
            Path object for the target directory
        """
        if self._current_lastplay_path:
            base_dir = self._current_lastplay_path.parent
        else:
            base_dir = Path(".")

        if game and hasattr(game, "shortname"):
            return base_dir / game.shortname

        return base_dir / "Unknown"

    def _sanitize_filename(self, filename: str) -> str:
        """
        Sanitize a string for use as a filename or directory name.

        Args:
            filename: String to sanitize

        Returns:
            Sanitized string safe for filesystem use
        """
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            filename = filename.replace(char, "_")

        filename = filename.strip(" .")

        if len(filename) > 100:
            filename = filename[:100]

        return filename

    def _create_lastplay_thumbnail(self, video_path: Path) -> None:
        """
        Create a thumbnail for the lastplay video using current screen capture.

        Args:
            video_path: Path to the lastplay video file
        """
        screenshot = self.screen.capture_focused_window()
        if not screenshot:
            return None

        recording_dir = video_path.parent
        thumbnail_path = recording_dir / "lastplay.png"

        if thumbnail_path.exists():
            thumbnail_path.unlink()
            logging.debug("[Recording] Removed previous thumbnail")

        mss.tools.to_png(screenshot.rgb, screenshot.size, output=str(thumbnail_path))

        self._current_thumbnail_path = thumbnail_path

        logging.debug("[Recording] Created thumbnail: %s", thumbnail_path.name)

    def _organize_thumbnail(self, video_path: Path) -> None:
        """
        Copy and rename the thumbnail to match the organized video file.

        Args:
            video_path: Path to the organized video file
        """
        if (
            not self._current_thumbnail_path
            or not self._current_thumbnail_path.exists()
        ):
            return

        thumbnail_name = video_path.stem + ".png"
        organized_thumbnail_path = video_path.parent / thumbnail_name

        shutil.move(str(self._current_thumbnail_path), str(organized_thumbnail_path))

        logging.debug("[Recording] Organized thumbnail: %s", thumbnail_name)
