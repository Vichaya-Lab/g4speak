`jfk.wav` is a 16 kHz mono PCM conversion of the human English speech fixture
https://github.com/openai/whisper/blob/main/tests/jfk.flac
from OpenAI Whisper, under the MIT license in `WHISPER_LICENSE`.
It tests the actual neural speech detector, including quiet/noisy variants;
it is not a Thai transcription accuracy benchmark.

`accuracy.json` is a synthetic text-only proofreading corpus. It includes technical
and specialized vocabulary plus already-correct controls. It is not human speech,
training data, or an ASR accuracy measurement. Run `scripts/evaluate-accuracy.py`
explicitly for live cloud evaluation; normal unit tests never call cloud APIs.

`scripts/fetch-accuracy-fixtures.py` optionally streams the first distinct test
utterances from Google FLEURS Thai at revision
`70bb2e84b976b7e960aa89f1c648e09c59f894dd`. Downloaded samples and their manifest
stay in ignored `.render/fleurs/`. Source: https://huggingface.co/datasets/google/fleurs,
Google FLEURS, CC BY 4.0: https://creativecommons.org/licenses/by/4.0/.
Float WAV is converted to mono 16 kHz PCM16; reference text is unchanged.
This deterministic convenience sample is not a representative Thai benchmark.

The bundled `assets/silero_vad_v6.onnx` is the Silero VAD v6 sequence model
distributed in faster-whisper 1.2.1. It uses `input`, `h`, and `c` inputs,
as documented in https://github.com/SYSTRAN/faster-whisper/blob/v1.2.1/faster_whisper/vad.py
and originates from https://github.com/snakers4/silero-vad.
Its MIT license is preserved in `assets/SILERO_LICENSE`.
