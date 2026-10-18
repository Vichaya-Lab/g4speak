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

Dictation removes DC offset and uses the bundled Silero VAD v6 neural model locally to distinguish speech from silence, hiss, hum, and clicks before uploading. Only recordings with sustained speech are sent for recognition. Outer silence is trimmed with context and gain is capped at 2x after speech detection. If the VAD model fails, recognition stops with a notification instead of bypassing the check. TV or other people's speech can still pass a voice detector.

Use `GROQ_STT_MODEL=whisper-large-v3` for multilingual accuracy. Set `GROQ_STT_LANGUAGE=auto` (default) to switch between Thai and English; `th` or `en` provides a language hint for single-language sessions. Reload API Keys after editing `.env`.

You can also choose **Dictation language** from the tray menu. **Thai (English words supported)** provides a Thai language hint for mainly Thai sentences containing English terms; use **English** for English dictation or **Auto** to switch freely. Language hints can reduce language-detection errors but do not guarantee correct words.

Recognition rejects individual segments with high no-speech probability, very low confidence, or excessive repetition. Responses missing segment confidence metadata are discarded. A confident-looking transcript alone cannot bypass local speech detection.

Processing has a 1.8-second budget, plus a 96 ms microphone tail and text insertion, targeting roughly 2 seconds after release. API retries are disabled. Optional proofreading falls back to the transcript when its time runs out. If recognition itself times out or fails, a tray notification appears; late results are discarded. Network/server latency can prevent a transcript within this budget; successful transcription and accuracy are not guaranteed within 2 seconds.

The bounded dictation pipeline skips the optional local LLM because local loading and inference cannot be interrupted reliably within this budget.

## Tray Menu

Right-click the icon by the Windows clock:
- **Edit API Keys...** — Opens `.env` in Notepad.
- **Reload API Keys** — Updates keys without restarting.
- **Dictation language** — Choose Auto, Thai, or English; the choice is saved in `.env`.
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
python -m unittest discover -s tests -p "test_*.py"
```

Build standalone `.exe`:
```cmd
build.bat
```

Output binary is saved to `dist/G4Speak.exe`.

---

## License

[MIT](LICENSE)
