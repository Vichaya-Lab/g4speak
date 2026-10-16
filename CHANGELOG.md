# Changelog

## [1.0.4] - 2026-10-17

- Keep the active overlay visible and above other windows by periodically restoring its native Windows topmost state without taking keyboard focus.
- Request low-latency microphone capture so recording begins sooner after the hotkey is pressed.
- Correct the application version shown by the tray icon and notifications.

## [1.0.2] - 2026-10-16

- **Restored Whisper Large-v3 Full Model**: Permanently standardizes on the 32-layer `whisper-large-v3` model. Fixes the issue where `whisper-large-v3-turbo` collapsed on Thai speech into random non-human gibberish.
- **Eliminated Prompt Leaks**: Removed static keyword prompt conditioning from Whisper requests. Whisper now transcribes only real acoustic speech without regurgitating prompt tokens.
- **Strict Acoustic Logprob Confidence Gating**: Transcriptions scoring `avg_logprob < -0.65` or `avg_no_speech > 0.35` are automatically rejected as hallucinations/noise.
- **Keyclick & Micro-noise Suppression**: Raised minimum recording duration to 0.60s and tightened VAD energy thresholds so accidental key taps and chair/mic clicks are discarded before calling the API.
- **Repetitive Loop Detection**: Added guard against looping silence hallucinations.
- **Updated Documentation**: Clear, accurate README matching the real user interface.

## [1.0.1] - 2026-10-16

- Instant zero-latency tech casing and typography formatting (`TECH_CASING_MAP`).
- Optional Groq Cloud LLM refinement support.
- PyInstaller spec stabilization.

## [1.0.0] - 2026-10-15

- Initial release of G4Speak: Floating minimal capsule overlay for Windows.
- Direct typing via SendInput + safe clipboard-restore fallback.
- Low-level WH_KEYBOARD_LL Windows hook.
- MIT license.
