## Install

Download **G4Speak-Setup-1.2.1.exe**, open it, and click **Install**. No administrator rights or Python installation are needed. Launch G4Speak from the Start Menu, then add your Groq API key from the tray menu's **Edit API Keys...** option.

The installer supports upgrades and Windows uninstall. Existing API settings and personal vocabulary are retained. The standalone **G4Speak.exe** is still available for portable use; **SHA256SUMS.txt** covers both downloads.

## Changes

- Record for up to 10 minutes, with recognition time scaled to audio length instead of a short fixed timeout.
- Cancel processing with Esc and discard late results.
- Add your preferred names, words, and phrases to the minimal English Dictionary editor, one per line. No incorrect spellings are required; saved words survive app restarts.
- Use short vocabulary hints to help recognition while retaining local speech detection and confidence filters.
- Filter low-confidence standalone thanks phrases and preserve confident dictation.
- Fix Windows regression tests failing on Thai text output.

Speech recognition still uses Groq Whisper Large-v3. It requires internet access and a Groq API key.
