<div align="center">
  <img src="assets/logo.png" alt="G4Speak Logo" width="100">
  <h1>G4Speak</h1>
  <p>Voice dictation for Windows (Thai + English)</p>
  <p>Hold <code>Ctrl + Space</code> to talk, release to type anywhere.</p>

  <p>
    <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg?style=flat-square" alt="License"></a>
    <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.12-3776AB.svg?style=flat-square&logo=python&logoColor=white" alt="Python 3.12"></a>
    <img src="https://img.shields.io/badge/platform-Windows_10_%7C_11-0078D6.svg?style=flat-square&logo=windows&logoColor=white" alt="Windows 10/11">
    <a href="https://console.groq.com/keys"><img src="https://img.shields.io/badge/STT-Whisper_Large--v3-f55036.svg?style=flat-square" alt="Whisper Large-v3"></a>
  </p>
</div>

---

## Overview

| State | Preview | Action |
|---|:---:|---|
| **Idle** | <img src="assets/demo-idle.png" width="120" alt="Idle state"> | Sits right above your taskbar. |
| **Speaking** | <img src="assets/demo-recording.png" width="260" alt="Recording state"> | **Hold `Ctrl + Space`** to speak. The bar expands and shows your live voice waves. Release to type. |
| **Hands-Free Lock** | <img src="assets/demo-locked.png" width="300" alt="Locked state"> | **Double-tap `Ctrl + Space`** (or click the bar) to lock. Speak hands-free, then tap again to submit. |

### Controls
- **Hold `Ctrl + Space`**: Speak while holding; release to finish and type.
- **Double-tap `Ctrl + Space`** (or click the bar): Hands-free lock mode. Tap `Ctrl + Space` again or click to stop and type.
- **`Esc`**: Cancel recording without typing anything.

---

## Features

- **Thai & English**: Transcribes spoken Thai and English naturally using Whisper Large-v3.
- **Types Anywhere**: Directly types at your cursor in Notepad, Word, Discord, browser, or code editors.
- **Clipboard Safe**: Uses direct Windows keyboard input; your clipboard is kept intact.
- **Fast & Lightweight**: Speech recognition runs via Groq Cloud API; no heavy local models to download.
- **Noise Filtering**: Automatically drops accidental key clicks, mouse taps, and background silence.

---

## Getting Started

### 1. Download
Grab `G4Speak.exe` from [Releases](https://github.com/Vichaya-Lab/g4speak/releases).

### 2. Add API Key
1. Get a free API key at [console.groq.com/keys](https://console.groq.com/keys).
2. Run `G4Speak.exe`, right-click the tray icon > **Edit API Keys...**.
3. Paste your key in `.env` and save:
   ```env
   GROQ_API_KEY=gsk_your_key_here
   ```
4. Right-click the tray icon > **Reload API Keys**.

---

The microphone stays open while G4Speak is running so dictation starts promptly. Audio outside an active recording is discarded and is never sent to the API.

## Tray Menu

Right-click the icon by the Windows clock:
- **Edit API Keys...** — Opens `.env` in Notepad.
- **Reload API Keys** — Updates keys without restarting.
- **Run at Startup** — Toggle Windows autostart.
- **Quit G4Speak** — Exit application.

---

## Development

Requires Python 3.12+ on Windows:

```bash
git clone https://github.com/Vichaya-Lab/g4speak.git
cd g4speak
pip install -r requirements.txt
python main.py
```

Run test suite:
```bash
python tests/test_guards.py
```

Build standalone `.exe`:
```cmd
build.bat
```

Output binary is saved to `dist/G4Speak.exe`.

---

## License

[MIT](LICENSE)
