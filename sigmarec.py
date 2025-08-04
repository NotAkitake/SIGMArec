import os
import sys
import json
import time
import winsound
import keyboard
import win32gui
import win32process
import psutil
import ctypes
import logging
from datetime import datetime
from obswebsocket import obsws, requests, events
from PIL import ImageGrab
from types import SimpleNamespace

def run_as_admin():
    if not ctypes.windll.shell32.IsUserAnAdmin():
        params = " ".join(sys.argv)
        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
        sys.exit(0)

run_as_admin()
ctypes.windll.kernel32.SetConsoleTitleW("SIGMArec Recorder")

class Config:
    def __init__(self, path):
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Config file not found: {path}")

        with open(path, "r") as f:
            data = json.load(f)

        self.key_save_play = data.get("key_save_play", "k")
        self.video_subfolders = bool(data.get("video_subfolders", False))
        self.screenshot_results = bool(data.get("screenshot_results", True))
        self.result_wait_time = float(data.get("result_wait_time", 3))
        self.sounds = SimpleNamespace(**data.get("sounds", {}))
        self.ows = SimpleNamespace(**data.get("obswebsocket", {}))
        self.debug = bool(data.get("debug", False))
        self.detection_frames = int(data.get("detection_frames", 2))
        self.pixel_tolerance = int(data.get("pixel_tolerance", 15))
        self.detection_interval = float(data.get("detection_interval", 0.5))
        self.games = self._parse_games(data.get("games", {}))

    def _parse_games(self, raw_games):
        parsed = []
        for game_name, info in raw_games.items():
            processes = info.get("process", [])
            if isinstance(processes, str):
                processes = [processes]
            processes = [p.lower() for p in processes]

            title = info.get("title", "").lower()
            shortname = info.get("shortname", "").lower()
            states = {}
            for state_name, pixel_groups in info.get("states", {}).items():
                states[state_name] = [
                    [((x, y), (r, g, b)) for x, y, r, g, b in group]
                    for group in pixel_groups
                ]
            parsed.append({
                "name": game_name,
                "processes": processes,
                "title": title,
                "shortname": shortname,
                "states": states
            })
        return parsed

    def get_sound_path(self, name):
        return getattr(self.sounds, name, None)

    def get_obs_config(self):
        return (
            getattr(self.ows, "host", "localhost"),
            getattr(self.ows, "port", 4455),
            getattr(self.ows, "password", "")
        )

class OBSController:
    def __init__(self, host, port, password):
        self.host = host
        self.port = port
        self.password = password
        self.ws = None
        self.output_path = ""
        self.lastplay_path = None
        self.recording = False
        self.connected = False
        self._reconnecting = False

    def on_recording_changed(self, event):
        logging.info(f"[OBS] RecordStateChanged fired: {event}")
        self.output_path = event.getOutputPath()
        self.recording = event.getOutputState() == "OBS_WEBSOCKET_OUTPUT_STARTED"

    def on_event(self, message):
        logging.debug(f"[OBS EVENT] {message}")

    def connect_loop(self):
        while True:
            try:
                self.ws = obsws(self.host, self.port, self.password)
                self.ws.connect()
                self.ws.call(requests.StopRecord())
                self.ws.register(self.on_event)
                self.ws.register(self.on_recording_changed, events.RecordStateChanged)
                self.connected = True
                self._reconnecting = False
                break
            except Exception as e:
                if not self._reconnecting:
                    logging.warning(f"OBS connection failed! Retrying every 3s...")
                    self._reconnecting = True
                time.sleep(3)

    def connect(self):
        self.connect_loop()

    def ensure_connected(self):
        if not self.ws or not self.connected:
            self.connect_loop()
            return
        try:
            self.ws.call(requests.GetVersion())
        except Exception as e:
            self.connected = False
            self.connect_loop()

    def start_recording(self):
        self.ensure_connected()
        self.ws.call(requests.StartRecord())
        logging.info("Start recording requested")

    def stop_recording(self):
        self.ensure_connected()
        self.ws.call(requests.StopRecord())
        logging.info("Stop recording requested")

    def disconnect(self):
        if self.ws and self.connected:
            self.ws.disconnect()
            logging.info("Disconnected from OBS")
            self.connected = False

class StateMachine:
    def __init__(self, obs, detection_frames=2):
        self.current_state = None
        self.last_state = None
        self.obs = obs
        self.can_save = False
        self.detection_frames = detection_frames
        self.transitions = {
            ("*", "Playing"): self.handle_enter_playing,
            ("*", "Result"): self.handle_enter_result,
            ("*", "Select"): self.handle_enter_select,
        }
        self.state_history = []

    def update(self, new_state, current_shortname):
        self.state_history.append(new_state)
        if len(self.state_history) > self.detection_frames:
            self.state_history.pop(0)

        # Only update if the last `detection_frames` states are identical and different from current_state
        if len(self.state_history) == self.detection_frames and len(set(self.state_history)) == 1 and self.state_history[0] != self.current_state:
            stable_state = self.state_history[0]
            logging.info(f"{self.current_state or 'None'} → {stable_state}")
            self.last_state = self.current_state
            self.current_state = stable_state

            handler = self.transitions.get(
                (self.last_state, stable_state),
                self.transitions.get(("*", stable_state))
            )

            if handler:
                try:
                    handler()
                except Exception as e:
                    logging.info(f"[StateMachine] Error during transition to {stable_state}: {e}")
                    self.can_save = False

        self.poll_state(current_shortname)

    def poll_state(self, current_shortname):
        if keyboard.is_pressed(config.key_save_play) and self.can_save:
            logging.debug(f"Key '{config.key_save_play}' was pressed; attempting to save play")
            name = f"{current_shortname}_{datetime.now():%Y-%m-%d_%H-%M-%S}"
            path = rename_recording(self.obs.lastplay_path, name, current_shortname)
            try_play_sound("saved")
            logging.info(f"Saved: {path}")
            self.can_save = False

    def handle_enter_playing(self):
        if self.obs.recording:
            self.obs.stop_recording()
            if not wait_recording_stop(self.obs):
                raise RuntimeError("Recording did not stop in time")
            if os.path.isfile(self.obs.output_path):
                os.remove(self.obs.output_path)
            try_play_sound("fail")
            self.can_save = False
        try_play_sound("start")
        self.obs.start_recording()

    def handle_enter_result(self):
        if self.obs.recording:
            time.sleep(config.result_wait_time)
            self.obs.stop_recording()
            if not wait_recording_stop(self.obs):
                raise RuntimeError("Recording did not stop in time")

            wait_time = 0
            while not self.obs.output_path and wait_time < 3.0:
                time.sleep(0.1)
                wait_time += 0.1

            if not self.obs.output_path:
                logging.warning("[handle_enter_result] Output path is still None after waiting. Skipping save.")
                return

            if config.screenshot_results:
                screenshot_path = os.path.join(os.path.dirname(self.obs.output_path), "lastplay.png")
                save_result_screenshot(screenshot_path)

            self.obs.lastplay_path = rename_recording(self.obs.output_path, "lastplay")
            if self.obs.lastplay_path:
                self.can_save = True
                try_play_sound("ready")
                logging.info("Ready to save! Press assigned key on result screen to keep the last play.")
            else:
                logging.info("[handle_enter_result] Failed to rename last recording.")

    def handle_enter_select(self):
        if self.obs.recording:
            self.obs.stop_recording()
            if not wait_recording_stop(self.obs):
                raise RuntimeError("Recording did not stop in time")
            if os.path.isfile(self.obs.output_path):
                os.remove(self.obs.output_path)
            try_play_sound("fail")
        self.can_save = False

class LoggingFilter(logging.Filter):
    def filter(self, record):
        return "GetVersion" not in record.getMessage()

def save_result_screenshot(path):
    try:
        img = ImageGrab.grab()
        img.save(path)
        logging.info(f"Screenshot saved to {path}")
    except Exception as e:
        logging.error(f"Failed to save screenshot: {e}")

def get_foreground_window_info():
    hwnd = win32gui.GetForegroundWindow()
    if not hwnd:
        return None, None
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    try:
        proc = psutil.Process(pid)
        process_name = proc.name().lower()
        window_title = win32gui.GetWindowText(hwnd).lower()
        return process_name, window_title
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None, None

def color_match(c1, c2, tol):
    return all(abs(a - b) <= tol for a, b in zip(c1, c2))

def check_game_state(process_name, window_title):
    img = ImageGrab.grab()
    for game in config.games:
        if process_name not in game["processes"]:
            continue
        if game["title"] not in window_title:
            continue
        for state_name, groups in game["states"].items():
            for group in groups:
                if all(color_match(img.getpixel(pos), color, config.pixel_tolerance) for pos, color in group):
                    return state_name
    return "Unknown"

def rename_recording(path, new_name, shortname=""):
    if not path:
        logging.info("[rename_recording] No recording path provided, skipping rename.")
        return None
    if not os.path.isabs(path):
        logging.info(f"[rename_recording] Path is not absolute: {path}")
        return None
    if not os.path.exists(path):
        logging.info(f"[rename_recording] File does not exist: {path}")
        return None

    base, ext = os.path.splitext(os.path.basename(path))
    output_dir = os.path.dirname(path)

    if config.video_subfolders and new_name != "lastplay" and shortname:
        base_path = os.path.join(output_dir, shortname)
        os.makedirs(base_path, exist_ok=True)
        new_path = os.path.join(base_path, new_name + ext)
        new_img_path = os.path.join(base_path, new_name + ".png")
    else:
        new_path = os.path.join(output_dir, new_name + ext)
        new_img_path = os.path.join(output_dir, new_name + ".png")

    try:
        logging.debug(f"Renaming recording: from '{path}' to '{new_path}'")
        os.replace(path, new_path)

        old_img_path = os.path.join(output_dir, "lastplay.png")
        if os.path.exists(old_img_path):
            os.replace(old_img_path, new_img_path)
            logging.info(f"Renamed screenshot to {new_img_path}")

        return new_path
    except Exception as e:
        logging.error(f"Failed to rename {path} to {new_path}: {e}")
        return None

def try_play_sound(name):
    path = config.get_sound_path(name)
    if path and os.path.isfile(path):
        try:
            logging.debug(f"Trying to play sound: {name} from {path}")
            winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
        except Exception as e:
            logging.warning(f"[try_play_sound] {e}")

def wait_recording_stop(obs, timeout=3.0):
    for _ in range(int(timeout / 0.25)):
        if not obs.recording:
            return True
        time.sleep(0.25)
    return False

def main():
    global config
    # Initalize logging
    script_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    log_file_path = os.path.join(script_dir, "sigmarec.log")
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.FileHandler(log_file_path, mode="w", encoding="utf-8"),
            logging.StreamHandler(sys.stdout)
        ]
    )
    logging.getLogger().addFilter(LoggingFilter())
    for logger_name in logging.root.manager.loggerDict:
        if logger_name.startswith("obswebsocket"):
            logging.getLogger(logger_name).addFilter(LoggingFilter())
    logging.info("Logger initialized.")

    # Try load config
    try:
        config = Config("config.json")
    except Exception as e:
        logging.error(f"Failed to load config: {e}")
        input("Press Enter to exit...")
        return

    # Adjust logging level based on config
    logging.getLogger().setLevel(logging.DEBUG if config.debug else logging.INFO)

    # Create OBS Controller
    obs = OBSController(*config.get_obs_config())

    # Main logic
    last_process = None
    last_title = None
    state_machine = StateMachine(obs, config.detection_frames)
    try:
        while True:
            obs.ensure_connected()
            current_process, current_title = get_foreground_window_info()
            found = False
            for game in config.games:
                if current_process in game["processes"] and game["title"] in current_title:
                    matched_game_now = game
                    found = True
                    break
            matched_game_before = any(
                last_process in game["processes"] and game["title"] in last_title
                for game in config.games
            )

            if found:
                if not matched_game_before:
                    logging.info("Returned to game window")
                    time.sleep(3)

                state = check_game_state(current_process, current_title)
                state_machine.update(state, matched_game_now["shortname"].upper().strip())

            elif matched_game_before:
                logging.info("Exited game window")
                if obs.recording:
                    obs.stop_recording()
                    if not wait_recording_stop(obs):
                        raise RuntimeError("Recording did not stop in time")
                    if os.path.isfile(obs.output_path):
                        os.remove(obs.output_path)
                    try_play_sound("fail")

            last_process, last_title = current_process, current_title
            time.sleep(config.detection_interval)

        logging.info("Exiting gracefully")

    except Exception as e:
        logging.error(f"Exception in main loop: {e}", exc_info=True)
    except KeyboardInterrupt:
        logging.info("Shutting down...")

    finally:
        obs.disconnect()

if __name__ == "__main__":
    main()