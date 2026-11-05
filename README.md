# CaptionShot

A screenshot tool for Windows and macOS that lives in your system tray or menu bar. Press the hotkey, draw on the
screenshot (pen, line, arrow, rectangle, oval, marker, text), add a caption bar, and save or copy it. Captions can
be typed in Hindi as well as English.

## Install

Open a terminal and paste one line. Python is not needed.

**Windows** (PowerShell):

```powershell
irm https://raw.githubusercontent.com/alokstates/captionshot/main/install.ps1 | iex
```

**macOS** (Terminal):

```bash
curl -fsSL https://raw.githubusercontent.com/alokstates/captionshot/main/install.sh | bash
```

Run the same line again to update to the latest version.

| | Windows | macOS |
|---|---|---|
| Hotkey | Print Screen | Cmd+Shift+2 |
| Installs to | `%LocalAppData%\Programs\CaptionShot` | `/Applications` (or `~/Applications`) |
| Settings | `%APPDATA%\CaptionShot` | `~/.config/CaptionShot` |
| Admin rights | Not needed | Not needed |

**What the Windows install changes:** CaptionShot starts when you sign in, and the Print Screen key opens it
instead of Snipping Tool. To give the key back, turn on *Use the Print Screen key to open screen capture* in
Windows Settings > Accessibility > Keyboard.

**macOS permission:** the first capture asks for Screen Recording permission. Turn on CaptionShot in System
Settings > Privacy & Security > Screen & System Audio Recording, then quit and reopen it. The app is not notarized
by Apple, so macOS may ask you to allow it again after an update.

**Not code-signed:** neither build has a paid signing certificate. A setup file downloaded through a browser on
Windows may show "Windows protected your PC" (More info > Run anyway). On macOS, use the terminal command above,
because a browser-downloaded copy is blocked by Gatekeeper.

## Uninstall

**Windows:** Settings > Apps > CaptionShot > Uninstall.

**macOS:**

```bash
pkill -x CaptionShot; rm -rf /Applications/CaptionShot.app ~/Applications/CaptionShot.app ~/Library/LaunchAgents/com.captionshot.agent.plist
```

Both leave your settings in place, so a reinstall keeps them. Delete the settings folder listed above to remove
them too.

## Privacy

Screenshots stay on your computer. When you type a caption in Hindi, the words are sent to Google's Input Tools
service (`inputtools.google.com`) to fetch spelling suggestions; without a connection the app uses its built-in
suggestions instead.

## Run or build from source

Needs Python 3.10 to 3.15.

```bash
python -m pip install -r packaging/requirements-build.txt
python captionshot.py
```

- **Windows installer:** run `build.bat`. The result is `dist\CaptionShot-Setup-<version>.exe`.
- **macOS app:** run `./build.sh`. The result is `dist/CaptionShot.app` and a zip of it.

Both build in a private `.venv-build` folder and run the packaged app's self-test.

## Publishing a new version

1. Change the version in `captionshot.py` (`APP_VERSION`), `packaging/CaptionShot.iss`,
   `packaging/version_info.txt` and `build.bat`.
2. Commit, then tag and push:

   ```bash
   git tag v1.2.3
   git push origin main --tags
   ```

GitHub Actions builds both platforms, publishes the release, and tests the install commands on clean Windows and
Mac machines. The install commands always fetch the latest release.

## Licence

The bundled Mukta fonts are under the SIL Open Font License (`fonts/OFL.txt`).
