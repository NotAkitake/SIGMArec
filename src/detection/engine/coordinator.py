"""
Main detection coordination - orchestrates all detection components.
"""

import logging
import time
from typing import Any, Dict, List, Tuple

from src.config import AppSettings
from src.core.interfaces import (
    DetectionResult,
    IDetectionEngine,
    IOBSController,
    IRecordingManager,
)
from src.detection.detectors import GameDetector, LogStateDetector, PixelStateDetector
from src.detection.engine.state_manager import StateManager
from src.detection.processors import RecordingProcessor, SceneProcessor, VideoProcessor
from src.games import Game


class DetectionCoordinator(IDetectionEngine):
    """
    Main detection coordinator that orchestrates all detection components.

    This replaces the monolithic DetectionEngine with a composition of
    focused components.
    """

    def __init__(
        self,
        obs_controller: IOBSController,
        recording_manager: IRecordingManager,
        games: List[Game],
        settings: AppSettings,
        game_detector: GameDetector,
        video_processor: VideoProcessor,
        scene_processor: SceneProcessor,
        recording_processor: RecordingProcessor,
    ):
        """
        Initialize detection coordinator.

        Args:
            obs_controller: OBS controller interface
            recording_manager: Recording manager interface
            games: List of games to detect
            settings: Application settings
            game_detector: Game detector
            scene_processor: Scene processor
            recording_processor: Recording processor
        """
        self.obs = obs_controller
        self.recording_manager = recording_manager
        self.settings = settings

        self.state_manager = StateManager()
        self.game_detector = game_detector
        self.pixel_detector = PixelStateDetector(
            game_detector.screen, settings.detections_required
        )
        self.log_detector = LogStateDetector(settings.detections_required)
        self.video_processor = video_processor
        self.recording_processor = recording_processor
        self.scene_processor = scene_processor

        self.obs.register_event_handler(self)

        logging.debug("[DetectionCoordinator] Initialized with %d games", len(games))

    def detect_and_control(self) -> DetectionResult:
        """
        Main detection and control loop.

        Returns:
            DetectionResult with current detection status
        """
        current_time = time.time()

        active_game = self.game_detector.get_active_game()

        previous_game = self.state_manager.get_current_game()
        self.state_manager.update_game(active_game)
        if active_game != previous_game:
            if previous_game and not active_game and self.obs.recording_active:
                logging.debug("Game exited while recording, stopping and deleting")
                self.recording_processor.mark_for_deletion()
                self.recording_processor.stop_recording_immediate(play_failed=True)

            self.video_processor.process_game_change(active_game)
            self.scene_processor.process_game_change(active_game)

            self.pixel_detector.reset_detection_state()
            self.log_detector.reset_detection_state()

        if not active_game:
            return DetectionResult(
                game=None,
                state=None,
                confidence=0.0,
                metadata={"action": "no_game", "timestamp": current_time},
            )

        detected_state = None
        confidence = 0.0

        if self.pixel_detector.can_handle_game(active_game):
            detected_state = self.pixel_detector.detect_state(active_game)
            confidence = 0.8 if detected_state else 0.0
        elif self.log_detector.can_handle_game(active_game):
            detected_state = self.log_detector.detect_state(active_game)
            confidence = 0.9 if detected_state else 0.0

        # Process state changes
        state_transition = self.state_manager.update_state(detected_state)
        if state_transition:
            self.scene_processor.process_transition(state_transition)
            self.recording_processor.process_transition(state_transition)

        return DetectionResult(
            game=active_game,
            state=self.state_manager.get_current_state(),
            confidence=confidence,
            metadata={
                "detected_state": detected_state,
                "recording_active": self.obs.recording_active,
                "timestamp": current_time,
                "patterns_triggered": state_transition.triggered_patterns
                if state_transition
                else [],
            },
        )

    def can_save_lastplay(self) -> bool:
        """
        Check if lastplay can be saved.

        Returns:
            True if lastplay can be saved
        """
        if self.obs.recording_active:
            return False

        if not self.recording_manager.has_lastplay():
            return False

        current_state = self.state_manager.get_current_state()
        return current_state in [None, "Select", "Result"]

    def save_current_lastplay(self) -> Tuple[bool, str]:
        """
        Save the current lastplay.

        Returns:
            Tuple of (success, message)
        """
        current_game = self.state_manager.get_current_game()
        success, target_dir, filename = self.recording_manager.save_lastplay(
            current_game
        )

        if success:
            message = f"Lastplay saved to {target_dir}/{filename}"
        else:
            message = target_dir

        return success, message

    def get_current_status(self) -> Dict[str, Any]:
        """
        Get current engine status.

        Returns:
            Dictionary with current status information
        """
        current_game = self.state_manager.get_current_game()

        return {
            "current_game": current_game.name if current_game else None,
            "current_state": self.state_manager.get_current_state(),
            "recording_active": self.obs.recording_active,
            "can_save_lastplay": self.can_save_lastplay(),
            "obs_connected": self.obs.is_connected,
            "focused_window": self.game_detector.screen.get_focused_window_title(),
            "timestamp": time.time(),
        }

    def on_recording_started(self) -> None:
        """Handle recording start event."""
        logging.debug("[DetectionCoordinator] Recording started")

    def on_recording_stopped(self, output_path: str) -> None:
        """Handle recording stop event."""
        logging.debug("[DetectionCoordinator] Recording stopped: %s", output_path)

        # Let the recording processor handle completion first
        # It will discard the file if needed
        was_discarded = self.recording_processor.handle_recording_completed(output_path)

        # If not discarded, let the recording manager handle it
        if not was_discarded:
            self.recording_manager.handle_recording_completed(output_path)
