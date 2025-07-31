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

class Config:
    def __init__(self, path):
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Config file not found: {path}")

        with open(path, "r") as f:
            data = json.load(f)

        self.key_save_play = data.get("key_save_play", "k")
        self.video_subfolders = bool(data.get("video_subfolders", False))
        self.result_wait_time = float(data.get("result_wait_time", 3))
        self.sounds = SimpleNamespace(**data.get("sounds", {}))
        self.ows = SimpleNamespace(**data.get("obswebsocket", {}))
        self.pixel_tolerance = int(data.get("pixel_tolerance", 15))
        self.check_interval = float(data.get("check_interval", 0.5))
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

config = Config("config.json")
DEBUG = False

class OBSController:
    def __init__(self, host, port, password):
        self.ws = obsws(host, port, password)
        self.output_path = ""
        self.lastplay_path = None
        self.recording = False

    def on_recording_changed(self, event):
        self.output_path = event.getOutputPath()
        self.recording = event.getOutputState() == "OBS_WEBSOCKET_OUTPUT_STARTED"
        if DEBUG:
            print(f"[OBS] Recording state changed: {self.recording}, Path: {self.output_path}")

    def on_event(self, message):
        if DEBUG:
            print(f"[OBS EVENT] {message}")

    def connect(self):
        self.ws.connect()
        self.ws.register(self.on_event)
        self.ws.register(self.on_recording_changed, events.RecordStateChanged)
        print("Connected to OBS")

    def start_recording(self):
        self.ws.call(requests.StartRecord())

    def stop_recording(self):
        self.ws.call(requests.StopRecord())

    def disconnect(self):
        self.ws.disconnect()

class StateMachine:
    def __init__(self, obs):
        self.current_state = None
        self.last_state = None
        self.obs = obs
        self.can_save = False
        self.transitions = {
            ("*", "Playing"): self.handle_enter_playing,
            ("*", "Result"): self.handle_enter_result,
            ("*", "Select"): self.handle_enter_select,
        }

    def update(self, new_state, current_shortname):
        if new_state != self.current_state:
            print(f"{self.current_state or 'None'} → {new_state}")
            self.last_state = self.current_state
            self.current_state = new_state

            handler = self.transitions.get(
                (self.last_state, new_state),
                self.transitions.get(("*", new_state))
            )
            if handler:
                handler()
        self.poll_state(current_shortname)

    def poll_state(self, current_shortname):
        if keyboard.is_pressed(config.key_save_play) and self.can_save:
            name = f"{current_shortname}_{datetime.now():%Y-%m-%d_%H-%M-%S}"
            path = rename_recording(self.obs.lastplay_path, name, current_shortname)
            try_play_sound("saved")
            print(f"Saved: {path}")
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
            self.obs.lastplay_path = rename_recording(self.obs.output_path, "lastplay")
            if self.obs.lastplay_path:
                self.can_save = True
                try_play_sound("ready")
                print("Ready to save! Press assigned key on result screen to keep the last play.")

    def handle_enter_select(self):
        if self.obs.recording:
            self.obs.stop_recording()
            if not wait_recording_stop(self.obs):
                raise RuntimeError("Recording did not stop in time")
            if os.path.isfile(self.obs.output_path):
                os.remove(self.obs.output_path)
            try_play_sound("fail")
        self.can_save = False

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

def rename_recording(path, new_name, shortname = ""):
    if not os.path.isabs(path):
        raise ValueError(f"Path must be absolute: {path}")
    if not os.path.exists(path):
        return None
    base, ext = os.path.splitext(os.path.basename(path))
    if config.video_subfolders and new_name != "lastplay" and shortname != "":
        base_path = os.path.join(os.path.dirname(path), shortname)
        os.makedirs(base_path, exist_ok=True)
        new_path = os.path.join(base_path, new_name + ext)
    else:
        new_path = os.path.join(os.path.dirname(path), new_name + ext)
    os.replace(path, new_path)
    return new_path

def try_play_sound(name):
    path = config.get_sound_path(name)
    if path and os.path.isfile(path):
        try:
            winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
        except Exception as e:
            print(f"[try_play_sound] {e}")

def wait_recording_stop(obs, timeout=3.0):
    for _ in range(int(timeout / 0.25)):
        if not obs.recording:
            return True
        time.sleep(0.25)
    return False

def main():
    obs = OBSController(*config.get_obs_config())
    try:
        obs.connect()
    except Exception as e:
        print(f"[main] {e}")
        return

    last_process = None
    last_title = None
    state_machine = StateMachine(obs)

    try:
        while True:
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
                # Print only when returning to game window (was outside before)
                if not matched_game_before:
                    print("Returned to game window")

                state = check_game_state(current_process, current_title)
                state_machine.update(state, matched_game_now["shortname"].upper())

            elif matched_game_before:
                print("Exited game window")
                if obs.recording:
                    obs.stop_recording()
                    if not wait_recording_stop(obs):
                        raise RuntimeError("Recording did not stop in time")
                    if os.path.isfile(obs.output_path):
                        os.remove(obs.output_path)
                    try_play_sound("fail")

            last_process, last_title = current_process, current_title
            time.sleep(config.check_interval)

    except KeyboardInterrupt:
        print("Shutting down...")

    finally:
        obs.disconnect()
        print("Disconnected from OBS")

if __name__ == "__main__":
    main()