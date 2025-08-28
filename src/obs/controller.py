"""
OBS WebSocket API wrapper.

Provides a simple interface for interacting with OBS.
"""

import logging
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, List, Optional

import obsws_python as obsws

from src.config.settings import AppSettings
from src.core.interfaces.obs import IOBSController, IOBSEventHandler
from src.obs.videosettings import OBSVideoSettings


@contextmanager
def _suppress_obsws_logging():
    """Context manager to temporarily suppress noisy obsws_python logging."""
    obsws_logger = logging.getLogger("obsws_python")
    websocket_logger = logging.getLogger("websocket")
    original_obsws_level = obsws_logger.level
    original_websocket_level = websocket_logger.level

    try:
        obsws_logger.setLevel(logging.CRITICAL)
        websocket_logger.setLevel(logging.CRITICAL)
        yield
    finally:
        obsws_logger.setLevel(original_obsws_level)
        websocket_logger.setLevel(original_websocket_level)


@dataclass
class OBSController(IOBSController):
    """OBS WebSocket API wrapper providing a simple interface for interacting with OBS."""

    settings: AppSettings

    req_client: obsws.ReqClient
    event_client: obsws.EventClient

    _keep_alive_thread: Optional[threading.Thread] = None
    _keep_alive_stop_event: Optional[threading.Event] = None
    _connection_lost: bool = False

    _prev_recording_active: bool = False
    recording_active: bool = False

    recording_completed_callback: Optional[Callable[[str], None]] = None
    _event_handlers: List[IOBSEventHandler] = []

    _initial_connection_thread: Optional[threading.Thread] = None

    def __post_init__(self):
        """Initialize event handlers list."""
        if self._event_handlers is None:
            self._event_handlers = []

    @property
    def is_connected(self) -> bool:
        """Check if we have active OBS clients and connection is not lost."""
        return (
            self.req_client is not None
            and self.event_client is not None
            and not self._connection_lost
        )

    @classmethod
    def connect(cls, settings: AppSettings) -> "OBSController":
        """Initialize the OBS WebSocket clients."""

        instance = cls(
            req_client=None,
            event_client=None,
            settings=settings,
            recording_active=False,
            _connection_lost=False,
        )

        instance._start_initial_connection_thread()

        return instance

    def _start_initial_connection_thread(self):
        """Start the initial connection attempt in a background thread."""
        self._initial_connection_thread = threading.Thread(
            target=self._attempt_initial_connection,
            daemon=True,
            name="OBSController-InitialConnection",
        )
        self._initial_connection_thread.start()
        logging.debug("[OBS] Initial connection attempt started in background")

    def _attempt_initial_connection(self):
        """Attempt initial connection in background thread."""
        success = self._attempt_connection()
        if success:
            logging.info("Connected to OBS")
        else:
            logging.warning("Failed to connect to OBS")
            logging.info("Attempting to reconnect...")

        self._start_keep_alive_thread()

    def _attempt_connection(self) -> bool:
        """Attempt to establish connection to OBS. Returns True if successful."""
        try:
            with _suppress_obsws_logging():
                req_client = obsws.ReqClient(
                    host=self.settings.obs_host,
                    port=self.settings.obs_port,
                    password=self.settings.obs_password,
                    timeout=self.settings.obs_timeout,
                )

                event_client = obsws.EventClient(
                    host=self.settings.obs_host,
                    port=self.settings.obs_port,
                    password=self.settings.obs_password,
                    timeout=self.settings.obs_timeout,
                )

                req_client.get_version()
                resp = req_client.get_record_status()

            self.req_client = req_client
            self.event_client = event_client
            self.recording_active = resp.output_active
            self._connection_lost = False

            self.register_events()

            return True

        except Exception as e:
            logging.debug("[OBS] Connection attempt failed: %s", str(e))
            self._connection_lost = True
            return False

    def _start_keep_alive_thread(self):
        """Start the background keep-alive monitoring thread."""
        if self._keep_alive_thread is not None:
            return

        self._keep_alive_stop_event = threading.Event()
        self._keep_alive_thread = threading.Thread(
            target=self._continuous_keep_alive,
            daemon=True,
            name="OBSController-KeepAlive",
        )
        self._keep_alive_thread.start()
        logging.debug("[OBS] Keep-alive thread started")

    def _continuous_keep_alive(self):
        """Continuously monitor connection and reconnect if needed."""
        while not self._keep_alive_stop_event.is_set():
            try:
                if not self.is_connected:
                    self._reconnect()
                else:
                    with _suppress_obsws_logging():
                        self.req_client.get_version()

                self._keep_alive_stop_event.wait(self.settings.obs_timeout)

            except Exception as e:
                logging.debug("[OBS] Keep-alive check failed: %s", str(e))
                self._connection_lost = True
                self._keep_alive_stop_event.wait(1)

    def _reconnect(self):
        """Attempt to reconnect to OBS WebSocket."""
        while not self._keep_alive_stop_event.is_set():
            if self._attempt_connection():
                logging.info("[OBS] Reconnected successfully")
                return
            self._keep_alive_stop_event.wait(1)

    def shutdown(self):
        """Gracefully shutdown the OBS controller and stop the keep-alive thread."""
        if self._keep_alive_stop_event is not None:
            self._keep_alive_stop_event.set()

        if self._keep_alive_thread is not None and self._keep_alive_thread.is_alive():
            self._keep_alive_thread.join(timeout=2.0)

        if (
            self._initial_connection_thread is not None
            and self._initial_connection_thread.is_alive()
        ):
            self._initial_connection_thread.join(timeout=2.0)

        logging.debug("[OBS] OBS controller shutdown complete")

    def __del__(self):
        """Destructor to ensure cleanup when object is garbage collected."""
        self.shutdown()

    def register_events(self):
        """Register event callbacks."""
        if self.is_connected:
            try:
                self.event_client.callback.register(self.on_record_state_changed)
            except Exception as e:
                logging.debug("[OBS] Failed to register events: %s", str(e))
                self._connection_lost = True

    def on_record_state_changed(self, event):
        """Callback for when the recording state changes."""
        self._prev_recording_active = self.recording_active
        if event.output_state == "OBS_WEBSOCKET_OUTPUT_STARTED":
            self.recording_active = True
            logging.info("Recording started")
            self._notify_recording_started()
        elif event.output_state == "OBS_WEBSOCKET_OUTPUT_STOPPED":
            self.recording_active = False
            logging.info("Recording stopped")

            if self.recording_completed_callback:
                self.recording_completed_callback(event.output_path)
            else:
                logging.debug("[OBS] Recording file available: %s", event.output_path)

            self._notify_recording_stopped(event.output_path)

    def register_event_handler(self, handler: IOBSEventHandler) -> None:
        """Register an event handler."""
        if handler not in self._event_handlers:
            self._event_handlers.append(handler)
            logging.debug(
                "[OBS] Registered event handler: %s", handler.__class__.__name__
            )

    def set_recording_completed_callback(self, callback: Callable[[str], None]) -> None:
        """Set the callback function to be called when recording completes."""
        self.recording_completed_callback = callback
        logging.debug("[OBS] Recording completed callback set")

    def _notify_recording_started(self) -> None:
        """Notify all event handlers of recording start."""
        for handler in self._event_handlers:
            try:
                handler.on_recording_started()
            except Exception as e:
                logging.error("[OBS] Error in recording started handler: %s", e)

    def _notify_recording_stopped(self, output_path: str) -> None:
        """Notify all event handlers of recording stop."""
        for handler in self._event_handlers:
            try:
                handler.on_recording_stopped(output_path)
            except Exception as e:
                logging.error("[OBS] Error in recording stopped handler: %s", e)

    def start_recording(self) -> None:
        """Start recording."""
        if not self.recording_active and self.is_connected:
            try:
                with _suppress_obsws_logging():
                    self.req_client.start_record()
                self._notify_recording_started()
            except Exception as e:
                logging.debug("[OBS] Failed to start recording: %s", str(e))
                self._connection_lost = True

    def stop_recording(self):
        """Stop recording."""
        if self.recording_active and self.is_connected:
            try:
                self.req_client.stop_record()
            except Exception as e:
                logging.debug("[OBS] Failed to stop recording: %s", str(e))
                self._connection_lost = True

    def set_video_settings(
        self,
        obssettings: OBSVideoSettings,
    ):
        """
        Set OBS video settings (base canvas, output resolution, and FPS).

        Args:
            obssettings: OBSVideoSettings object
        """
        if not self.is_connected:
            logging.warning("[OBS] Cannot set video settings - not connected")
            return

        try:
            with _suppress_obsws_logging():
                current_settings = self.req_client.get_video_settings()

                base_width = obssettings.base_width or current_settings.base_width
                base_height = obssettings.base_height or current_settings.base_height
                output_width = obssettings.output_width or current_settings.output_width
                output_height = (
                    obssettings.output_height or current_settings.output_height
                )
                fps_numerator = (
                    obssettings.fps_numerator or current_settings.fps_numerator
                )
                fps_denominator = (
                    obssettings.fps_denominator or current_settings.fps_denominator
                )

                logging.debug(
                    "[OBS] Setting video settings: %s",
                    {
                        "base_width": base_width,
                        "base_height": base_height,
                        "output_width": output_width,
                        "output_height": output_height,
                        "fps_numerator": fps_numerator,
                        "fps_denominator": fps_denominator,
                    },
                )

                self.req_client.set_video_settings(
                    base_width=base_width,
                    base_height=base_height,
                    out_width=output_width,
                    out_height=output_height,
                    numerator=fps_numerator,
                    denominator=fps_denominator,
                )
        except Exception as e:
            logging.debug("[OBS] Failed to set video settings: %s", str(e))
            self._connection_lost = True

    def get_video_settings(self) -> Optional[OBSVideoSettings]:
        """
        Get current OBS video settings.

        Returns:
            Dictionary containing video settings, or None if not connected or error occurred
        """
        if not self.is_connected:
            return None

        try:
            with _suppress_obsws_logging():
                response = self.req_client.get_video_settings()
            return OBSVideoSettings(
                base_width=response.base_width,
                base_height=response.base_height,
                output_width=response.output_width,
                output_height=response.output_height,
                fps_numerator=response.fps_numerator,
                fps_denominator=response.fps_denominator,
            )
        except Exception as e:
            logging.debug("[OBS] Failed to get video settings: %s", str(e))
            self._connection_lost = True
            return None

    def get_game_video_settings(self, game: str = "") -> Optional["OBSVideoSettings"]:
        """Get video settings for a specific game with fallback to defaults."""

        def parse_resolution(res_str: str) -> tuple[int, int] or None:
            """Parse resolution string like '1920x1080' into (width, height)."""
            if not res_str:
                return None
            parts = res_str.split("x")
            if len(parts) != 2:
                return None
            try:
                width = int(parts[0].strip())
                height = int(parts[1].strip())
                return (width, height)
            except (ValueError, TypeError):
                return None

        def parse_fps(fps_str: str) -> int or None:
            """Parse FPS string like '60' or '59.94' into (numerator, denominator)."""
            if not fps_str:
                return None
            try:
                fps_value = float(fps_str)
                if fps_value <= 0 or fps_value > 240:
                    return None
                return fps_value
            except (ValueError, TypeError):
                return None

        game_settings = self.settings.video.get(game, {})
        default_settings = self.settings.video.get("Default", {})

        combined_settings = default_settings.copy()
        combined_settings.update(game_settings)

        if not combined_settings:
            return None

        return OBSVideoSettings(
            base_width=parse_resolution(combined_settings.get("Base", None))[0],
            base_height=parse_resolution(combined_settings.get("Base", None))[1],
            output_width=parse_resolution(combined_settings.get("Output", None))[0],
            output_height=parse_resolution(combined_settings.get("Output", None))[1],
            fps_numerator=parse_fps(combined_settings.get("FPS", None)),
            fps_denominator=1,
        )

    def set_current_scene(self, scene_name: str):
        """
        Switch to the specified scene.

        Args:
            scene_name: Name of the scene to switch to
        """
        if not self.is_connected:
            logging.warning("[OBS] Cannot switch scene - not connected")
            return

        try:
            current_scene = self.get_current_scene()
            if current_scene != scene_name:
                with _suppress_obsws_logging():
                    self.req_client.set_current_program_scene(scene_name)
                logging.debug("[OBS][Scene] '%s' → '%s'", current_scene, scene_name)
        except Exception as e:
            logging.error("[OBS] Failed to switch scene: %s", str(e))
            self._connection_lost = True

    def get_current_scene(self) -> Optional[str]:
        """
        Get the name of the currently active scene.

        Returns:
            Name of the current scene, or None if not connected or error occurred
        """
        if not self.is_connected:
            return None

        try:
            with _suppress_obsws_logging():
                response = self.req_client.get_current_program_scene()
            return response.current_program_scene_name
        except Exception as e:
            logging.debug("[OBS] Failed to get current scene: %s", str(e))
            self._connection_lost = True
            return None

    def get_scene_list(self) -> List[str]:
        """
        Get a list of all available scene names.

        Returns:
            List of scene names, or empty list if not connected or error occurred
        """
        if not self.is_connected:
            return []

        try:
            with _suppress_obsws_logging():
                response = self.req_client.get_scene_list()
            return [scene["sceneName"] for scene in response.scenes]
        except Exception as e:
            logging.debug("[OBS] Failed to get scene list: %s", str(e))
            self._connection_lost = True
            return []
