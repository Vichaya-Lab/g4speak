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
- **`Esc`**: Cancel recording or processing without typing anything.

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
Download **G4Speak-Setup-1.2.1.exe** from the [latest release](https://github.com/Vichaya-Lab/g4speak/releases/latest), run it, and click **Install**. Setup installs for your Windows account without administrator rights, creates a Start Menu shortcut, and offers to launch G4Speak. A desktop shortcut is optional. No Python installation is required.

To update, run the newer Setup. Your API settings and Dictionary are preserved. Uninstall from **Settings > Apps > Installed apps > G4Speak**; personal settings are retained for reinstallation. `G4Speak.exe` is also available as a portable download. `SHA256SUMS.txt` contains checksums for both files.

### 2. Add API Key
1. Get a free API key at [console.groq.com/keys](https://console.groq.com/keys).
2. Open G4Speak from the Start Menu, then right-click the tray icon > **Edit API Keys...**.
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

Record for up to 10 minutes per session. Short words and recordings around one second are also accepted when local speech detection confirms speech. Recognition gets 30 seconds plus a quarter of the recording duration, capped at 180 seconds, including audio preparation and upload. The API request uses the remaining allowance instead of a fixed short timeout. These are maximum waits, not required recording lengths; results appear as soon as they are ready. API retries are disabled. Optional proofreading gets at most 350 ms within that limit and falls back to the transcript on timeout. Press **Esc** to cancel processing; late results are discarded. If recognition times out or fails, a tray notification appears. Low-confidence standalone phrases such as "Thank you" are filtered, while confidently spoken phrases are preserved.

Local speech detection processes bounded batches while carrying the model's recurrent state between batches, avoiding one large inference allocation for long recordings. Ten minutes of 16 kHz mono PCM WAV is approximately 19.2 MB, below Groq's documented 25 MB free-tier upload limit. Server load, connectivity, and account rate limits can still affect recognition. See [Groq speech-to-text documentation](https://console.groq.com/docs/speech-to-text).

The bounded dictation pipeline skips the optional local LLM because local loading and inference cannot be interrupted reliably within this budget.

## Tray Menu

Right-click the icon by the Windows clock:
- **Edit API Keys...** — Opens `.env` in Notepad.
- **Reload API Keys** — Updates keys without restarting.
- **Dictionary...** — Save the names, brands, and words you use.
- **Dictation language** — Choose Auto, Thai, or English; the choice is saved in `.env`.
- **Run at Startup** — Toggle Windows autostart.
- **Quit G4Speak** — Exit application.

## Personal dictionary

Right-click the tray icon and choose **Dictionary...**. Enter only the desired spellings, one word or phrase per line, such as a name, a specialized term, or a phrase you use. Click **Save** to apply changes immediately. Edit or remove lines to update the list; **Cancel** discards unsaved edits. The editor and its labels are in English; vocabulary can use Thai, English, or other languages.

Words are saved locally in `%APPDATA%\G4Speak\dictionary.json` and survive app restarts and EXE updates. Up to 500 words or phrases are supported, with a maximum of 200 characters each. Duplicates are rejected. Existing dictionaries in the old correction-pair format retain the desired spellings automatically; no incorrect spellings are required.

A short vocabulary hint is sent with speech-verified audio to guide recognition. Put your most important words first: hints include whole entries in list order up to a conservative 200 UTF-8 byte budget to stay below the provider's prompt limit. Longer entries that do not fit are skipped; all saved words still participate in local casing corrections. Empty dictionaries send no hint. This guides spelling rather than training the model and does not guarantee correct recognition. Local speech detection and transcript confidence filters remain enabled. After proofreading (or its timeout fallback), exact matches use your preferred casing without guessing replacements for unrelated words.

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

Build the portable app and Windows Setup (downloads and verifies Inno Setup 6.7.3 on the first build):
```cmd
build.bat
```

Outputs are `dist/G4Speak.exe`, `dist/G4Speak-Setup-1.2.1.exe`, and `dist/SHA256SUMS.txt`. The same release build runs in GitHub Actions for `v*` tags; installation, upgrade, and uninstall are checked before publishing. Run `powershell -File packaging/smoke-test.ps1` to verify an installer on a Windows account with no existing Setup installation.

---

## License

[MIT](LICENSE)
