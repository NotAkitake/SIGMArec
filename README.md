# SIGMArec

**Automatically record your gameplay with OBS Studio and pixel-based game state detection.**

---

## What it does

- Records automatically whenever you play a song.
- Stops recording after the song ends and renames the file to `lastplay`.
- Press your configured key on the result screen to save the replay with a timestamped filename.

---

## Supported Games

- beatmania IIDX 32 Pinky Crush  
- beatmania IIDX INFINITAS  
- Sound Voltex: Exceed Gear
- *literally any game you want to add pixels for*

---

## Setup & Usage

### 1. Requirements

- Latest Python and pip installed  
- Run in project folder:  
  ```bash
  pip install -r requirements.txt
  ```

### 2. Configure

- Rename `example.config.json` → `config.json`  
- Edit `config.json`:  
  - Set `"key_save_play"` to your preferred save key (e.g., `"k"`)  
  - Set `"video_subfolders"` to true if you want videos to go into sub folders named after the game's shortname, false otherwise
  - Add paths to your `.wav` sound files (optional)  
  - Enter your OBS WebSocket info (`host`, `port`, `password`)  
  - Adjust timing if needed (default values usually fine)  
- **No need to touch pixel detection unless adding new games!**

### 3. Run

- Start OBS, enable WebSocket server (`Tools > WebSocket Server Settings`)  
- Copy your WebSocket password and paste it in `config.json`  
- Run the script:  
  ```bash
  python sigmarec.py
  ```  
  *(It will restart as admin to detect keys when the game is focused)*  
- Play your game! Recording starts/stops automatically.  
- On the result screen, press your save key to keep your replay.

---

## Adding or tweaking games

Each game config includes:

- List of possible process names (executables)  
- Partial window title to confirm game is active  
- Pixel groups for detecting states (Select, Playing, Result)

You can add your own games by following the format in `example.config.json`.

---

## Notes

- Increasing `check_interval` reduces CPU usage but slows detection.  
- OBS WebSocket password resets on OBS restart unless manually set or disabled (not recommended).  

---