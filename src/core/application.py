"""
Main application class with improved architecture.
"""

import logging
import os
import sys
import threading
import time
from typing import Optional

import keyboard
from src.config import AppSettings
from src.core.interfaces import IDetectionEngine
from src import __version__

from .container import Container


class Application:
    """
    Main application class that manages the SIGMArec lifecycle.

    This replaces the monolithic SIGMArecApp with a cleaner, more maintainable
    architecture using dependency injection.
    """

    def __init__(self, config_path: str = "config.toml"):
        """
        Initialize the application.

        Args:
            config_path: Path to configuration file
        """
        self.container = Container()
        self.config_path = config_path

        self.hotkey_thread: Optional[threading.Thread] = None
        self.hotkey_running: bool = False
        self.save_key_pressed: bool = False
        self._shutdown_requested: bool = False

    def initialize(self) -> bool:
        """
        Initialize all application components.

        Returns:
            True if initialization successful, False otherwise
        """
        try:
            self._setup_logging()
            self.container.configure_application(self.config_path)
            self._setup_logging_level()
            self._setup_hotkeys()

            logging.info("SIGMArec initialization completed")
            return True

        except Exception as e:
            logging.error("Failed to initialize SIGMArec: %s", e)
            return False

    def run(self) -> None:
        """
        Run the main application loop.
        """
        if not self.container.has("IDetectionEngine"):
            logging.error("Detection engine not available - cannot run")
            return

        detection_engine = self.container.get("IDetectionEngine")
        settings = self.container.get("AppSettings")

        try:
            logging.info(
                "SIGMArec is running... Press Ctrl+C with the window focused to exit at any time"
            )

            while not self._shutdown_requested:
                try:
                    detection_engine.detect_and_control()
                    time.sleep(settings.detection_interval)

                except ConnectionRefusedError:
                    logging.error(
                        "[OBS] Connection lost - retrying in %s seconds...",
                        settings.obs_timeout,
                    )
                    time.sleep(settings.obs_timeout)

        except KeyboardInterrupt:
            logging.info("Shutdown requested by user")
        except Exception as e:
            logging.error("Unexpected error in main loop: %s", e)
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        """Gracefully shutdown the application."""
        if self._shutdown_requested:
            return

        logging.info("SIGMArec is shutting down...")
        self._shutdown_requested = True

        self.hotkey_running = False
        if self.hotkey_thread and self.hotkey_thread.is_alive():
            self.hotkey_thread.join(timeout=1.0)

        keyboard.unhook_all()

        self.container.cleanup()

        logging.info("SIGMArec shutdown complete")

    def save_lastplay(self) -> None:
        """Handle save lastplay hotkey press."""
        if not self.container.has("IDetectionEngine"):
            logging.warning("[Application] Detection engine not available")
            return

        detection_engine: IDetectionEngine = self.container.get("IDetectionEngine")

        sound_service = None
        if self.container.has("SoundService"):
            sound_service = self.container.get("SoundService")

        if not detection_engine.can_save_lastplay():
            status = detection_engine.get_current_status()
            if not status.get("can_save_lastplay", False):
                if status.get("recording_active", False):
                    logging.info("[Application] Cannot save while recording")
                else:
                    logging.info("[Application] No lastplay available to save")
                if sound_service:
                    sound_service.play_failed()
            return

        success, message = detection_engine.save_current_lastplay()

        if success:
            logging.info(message)
            if sound_service:
                sound_service.play_saved()
        else:
            logging.error("Failed to save lastplay")
            if sound_service:
                sound_service.play_failed()

    def _setup_logging(self) -> None:
        """Configure application logging."""
        log_file_path = os.path.join(".", "SIGMArec.log")

        logging.basicConfig(
            level=logging.INFO,
            format="[%(asctime)s] [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
            handlers=[
                logging.FileHandler(log_file_path, mode="w", encoding="utf-8"),
                logging.StreamHandler(sys.stdout),
            ],
        )

        logging.info("Starting SIGMArec (%s)", __version__)

    def _setup_logging_level(self) -> None:
        """Configure application logging level."""
        if self.container.has("AppSettings"):
            settings: AppSettings = self.container.get("AppSettings")
            logging.getLogger().setLevel(
                logging.DEBUG if settings.debug else logging.INFO
            )

    def _setup_hotkeys(self) -> None:
        """Setup keyboard hotkey monitoring."""
        if not self.container.has("AppSettings"):
            logging.warning("[Application] Settings not available for hotkeys")
            return

        self.hotkey_running = True
        self.hotkey_thread = threading.Thread(
            target=self._hotkey_loop, daemon=True, name="HotkeyMonitor"
        )
        self.hotkey_thread.start()

    def _hotkey_loop(self) -> None:
        """Hotkey monitoring loop."""
        if not self.container.has("AppSettings"):
            return

        settings: AppSettings = self.container.get("AppSettings")

        while self.hotkey_running and not self._shutdown_requested:
            try:
                key_pressed = keyboard.is_pressed(settings.save_key)

                if key_pressed and not self.save_key_pressed:
                    self.save_lastplay()

                self.save_key_pressed = key_pressed
                time.sleep(0.05)

            except Exception as e:
                logging.debug("[Application] Hotkey monitoring error: %s", e)
                time.sleep(0.1)
