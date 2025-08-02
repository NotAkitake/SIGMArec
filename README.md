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

## Security & Antivirus Warning

Because SIGMArec:

- Runs with administrator privileges (to detect keypresses reliably).   
- Periodically takes screenshots of your screen to detect game states.

**Windows Defender or other antivirus software may flag or block the program as suspicious or potentially harmful.**

These behaviors are common in malware but harmless in SIGMArec, hence the false positive detection.

If this happens you can either:

- Add an exclusion in Windows Defender for the SIGMArec executable.
- Use the python script directly rather than the window binary.

---

## Setup & Usage

### 1. Requirements

### Windows (binary)

Simply grab the latest tagged [release](https://github.com/NotAkitake/SIGMArec/releases/) archive and extract it!

### Manual

- Latest Python and pip installed  
- Clone the project
- Run in project folder:  
  ```bash
  pip install -r requirements.txt
  ```

### 2. Configure

- Rename `example.config.json` → `config.json`  
- Edit `config.json`:  
  - Set `"key_save_play"` to your preferred save key (e.g., `"k"`)  
  - Set `"video_subfolders"` to true if you want videos sorted into subfolders, false otherwise
  - Set `"result_wait_time"` to how long you want to record the result screen for upon detection (seconds)
  - Add paths to your `.wav` sound files (optional)  
  - Enter your OBS WebSocket info (`host`, `port`, `password`)  
  - Adjust timing if needed (default values usually fine)  
- **No need to touch pixel detection unless adding new games!**

### 3. Run

- Start OBS, enable WebSocket server (`Tools > WebSocket Server Settings`)  
- Copy your WebSocket password and paste it in `config.json`  
- Run `sigmarec.exe` or python script:  
  ```bash
  python sigmarec.py
  ```  
  *(Will restart as admin to detect keys when the game is focused)*  
- Play your game! If it's supported recordings will start/stop automatically.  
- On the result screen, press your save key to keep your replay.  
**You need to hold the key a bit longer than you might imagine, as checks happen every half a second by default.**

---

## Adding or tweaking games

Each game config includes:

- List of possible process names (executables)  
- Partial window title to confirm game is active  
- Short game name used to name saved video files
- Pixel groups for detecting states (Select, Playing, Result)

You can add your own games by following the format in `example.config.json`.

---

## Notes

- Increasing `check_interval` reduces CPU usage but slows detection.  
- OBS WebSocket password resets on OBS restart unless manually set or disabled (not recommended).  

---