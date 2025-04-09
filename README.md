# DuckTrack

This is the repository for the DuckAI DuckTrack app which records all keyboard and mouse input as well as the screen for use in a multimodal computer interaction dataset.

This version includes patches to ensure proper functionality on macOS.

## Installation & Setup

### macOS Users (Recommended)

1.  **Download the App:** Go to the [**Releases**](https://github.com/anaishowland/DuckTrack-0.1.0-beta/releases) section of this GitHub repository.
    *   Find the latest release (e.g., v0.1.0-beta).
    *   Download the `DuckTrack.dmg` file from the assets.
2.  **Install:**
    *   Double-click the downloaded `DuckTrack.dmg` file to open it.
    *   Drag the `DuckTrack.app` icon into the `Applications` folder shortcut within the disk image window.
    *   You can now eject the "DuckTrack" disk image from your Finder sidebar.
3.  **OBS Setup:** Ensure you have OBS Studio installed and configured correctly:
    *   Have a screen capture source recording your *entire main screen*.
    *   Enable desktop audio and mute microphone audio sources in OBS's audio mixer.
    *   Make sure the OBS WebSocket server is enabled (usually under `Tools -> WebSocket Server Settings`). The default port `4455` and no password is expected.
    *   *More detailed OBS setup instructions: [OBS_SETUP.md](OBS_SETUP.md)*
4.  **macOS Permissions:** The first time you run DuckTrack, macOS will likely ask for permissions:
    *   **Accessibility:** Required for playing back recorded actions. Go to `System Settings -> Privacy & Security -> Accessibility` and ensure `DuckTrack.app` is listed and enabled (you might need to add it manually using the '+' button).
    *   **Input Monitoring:** Required for recording keyboard inputs. Go to `System Settings -> Privacy & Security -> Input Monitoring` and ensure `DuckTrack.app` is listed and enabled.
    *   **Screen Recording:** Required by OBS for capturing the screen. OBS itself should prompt for this, but ensure it's enabled in `System Settings -> Privacy & Security -> Screen Recording`.
    *   Accept any other security prompts that may appear.
5.  **Run:** Launch DuckTrack from your Applications folder.

### Build from source (Advanced)

Have Python >=3.11 installed.

Clone this repo and `cd` into it:
```bash
git clone https://github.com/anaishowland/DuckTrack-0.1.0-beta
cd DuckTrack-0.1.0-beta
```

Create and activate a virtual environment (recommended):
```bash
python3 -m venv venv
source venv/bin/activate
```

Install the dependencies:
```bash
pip install -r requirements.txt
# On macOS, also install PyObjC:
pip install pyobjc-framework-Cocoa
```

Build the application:
```bash
python build.py
```

The built application (`.app` on macOS, `.exe` on Windows) will be in the `dist` directory. Follow the relevant OBS setup and permissions steps from the section above before running.

## Running the App

If you installed via the `.dmg` (macOS) or ran the builder, launch the application normally.

If running directly from source: `python main.py`

You will interact with the app through an app tray icon (menu bar on macOS, system tray on Windows/Linux) or a small window.

### Recording

From the app tray or GUI, you can start and stop a recording as well as pause and resume a recording. Pausing and resuming is important for when you want to hide sensitive information like credit card or login credentials. You can optionally name your recording and give it a description upon stopping a recording. You can also view your recordings by pressing the "Show Recordings" option.

### Playback

You can playback a recording, i.e. simulate the series of events from the recording, by pressing "Play Latest Recording", which plays the latest created recording, or by pressing "Play Custom Recording", which lets you choose a recording to play. You can easily replay the most recently played recording by pressing "Replay Recording".

To stop the app mid-playback, just press `shift`+`esc` on your keyboard.

### Misc

To quit the app, you just press the "Quit" option.

## Recording Format

Recordings are stored in `Documents/DuckTrack_Recordings`. Each recording is a directory containing:

1.  `events.jsonl` file - sequence of all computer actions that happened. Includes mouse moves, clicks, scrolls, key presses/releases, and application focus changes. A sample event may look like this:
    ```json
    {"time_stamp": 1234567.89, "action": "move", "x": 69.0, "y": 420.0}
    ```
    ```json
    {"time_stamp": 1234570.12, "action": "window_focus", "app_name": "Finder", "window_title": "Finder", "x": 123.0, "y": 456.0, "button": null, "pressed": false}
    ```
1.  `metadata.json` - stores metadata about the computer that made the recording
2.  `README.md` - stores the optional description for the recording
3.  MP4 file - the screen recording from OBS of the recording.

Here is a [sample recording](example) for further reference.

## Technical Overview

<!-- maybe put a nice graphical representation of the app here -->

*TBD*

## Known Bugs

- After doing lots of playbacks on macOS, a segfault will occur.
- Mouse movement is not captured when the current application is using raw input, i.e. video games.
- OBS may not open in the background properly on some Linux machines.

## Things To Do

- Testing
- CI (with builds and testing)
- Add way to hide/show window from the app tray (and it saves that as a preference?)
- Make saving preferences a thing generally, like with natural scrolling too
- Add explicit logging to files.
