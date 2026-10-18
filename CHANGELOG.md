# Changelog

## [1.2.1] - 2026-10-18

- Add an English Windows Setup for per-user installation without administrator rights, a Start Menu shortcut, optional desktop shortcut, and Windows uninstall support. Preserve API settings and personal vocabulary on upgrades and uninstall. Include installer and portable EXE checksums in releases.
- Add a minimal English dictionary editor: enter only desired words, one per line. Persist locally, migrate desired spellings from old correction pairs, send bounded spelling hints only after speech detection, and preserve preferred casing after proofreading.
- Fix Windows regression test discovery failing under cp1252 by moving guard checks into unittest without printing Thai text during imports.
- Extend recording sessions to 10 minutes and scale recognition time from 30 to 180 seconds with duration, passing the remaining deadline to the API. Process local speech detection in bounded batches. Keep optional refinement capped at 350 ms; allow cancellation during processing and discard late results.
- Filter low-confidence standalone thanks phrases while preserving confident dictation and local speech detection.

## [1.2] - 2026-10-18

- Detect speech locally with the bundled Silero VAD v6 model before uploading audio; silence, hiss, hum, and clicks no longer pass on energy alone. Stop recognition if the detector is unavailable.
- Reject high no-speech probability, low-confidence, and repetitive transcription segments, including responses missing confidence metadata.
- Preserve quiet speech and microphone tails, trim outer silence, and cap amplification at 2x after speech detection.
- Add saved Auto, Thai, and English dictation language choices to the tray menu.
- Bound processing to 1.8 seconds with API retries disabled. Fall back to the transcript if optional refinement times out; notify on recognition failures and discard late results.
- Add real human speech, noise rejection, confidence parsing, and deadline regression tests. Accuracy and successful transcription within two seconds still depend on audio quality and the API.

## [1.1] - 2026-10-17

- Restore the floating overlay above other windows in idle, recording, and processing states without stealing focus. Reposition it after taskbar or display changes.
- Keep the microphone stream ready between recordings to remove repeated device startup delays. Idle samples are discarded; only active sessions are retained.
- Reconnect after microphone failures and reject stale recording results after cancellation.

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
