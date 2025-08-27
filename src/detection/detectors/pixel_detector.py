"""
Pixel-based state detection for games that use screen analysis.
"""

import logging
from typing import Optional

from src.detection.detectors.base import BaseStateDetector
from src.detection.screen_capture import ScreenCaptureService
from src.games import Game, PixelGame


class PixelStateDetector(BaseStateDetector):
    """Detector for pixel-based game state detection."""

    def __init__(
        self,
        screen_capture_service: ScreenCaptureService,
        detection_threshold: int = 2,
    ):
        super().__init__(detection_threshold)
        self.screen = screen_capture_service

    def can_handle_game(self, game: Game) -> bool:
        """Check if this detector can handle pixel-based games."""
        return isinstance(game, PixelGame)

    def _detect_raw_state(self, game: Game) -> Optional[str]:
        """
        Detect state using pixel analysis.

        Args:
            game: PixelGame to analyze

        Returns:
            Detected state name or None
        """
        if not isinstance(game, PixelGame):
            logging.warning(
                "[PixelDetector] Cannot handle non-pixel game: %s", game.name
            )
            return None

        screenshot = self.screen.capture_focused_window()
        if not screenshot:
            return None

        state_obj = game.get_current_state(screenshot)
        return state_obj.get_name() if state_obj else None
