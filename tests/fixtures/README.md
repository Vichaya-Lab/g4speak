`jfk.wav` is a 16 kHz mono PCM conversion of the human English speech fixture
https://github.com/openai/whisper/blob/main/tests/jfk.flac
from OpenAI Whisper, under the MIT license in `WHISPER_LICENSE`.
It tests the actual neural speech detector, including quiet/noisy variants;
it is not a Thai transcription accuracy benchmark.

The bundled `assets/silero_vad_v6.onnx` is the Silero VAD v6 sequence model
distributed in faster-whisper 1.2.1. It uses `input`, `h`, and `c` inputs,
as documented in https://github.com/SYSTRAN/faster-whisper/blob/v1.2.1/faster_whisper/vad.py
and originates from https://github.com/snakers4/silero-vad.
Its MIT license is preserved in `assets/SILERO_LICENSE`.
