"""Local Silero VAD v6 sequence model; no audio is sent by this module."""
import threading
from functools import lru_cache

import numpy as np


class SpeechDetector:
    def __init__(self, model_path):
        import onnxruntime as ort

        options = ort.SessionOptions()
        options.inter_op_num_threads = 1
        options.intra_op_num_threads = 1
        self.session = ort.InferenceSession(
            str(model_path), sess_options=options, providers=['CPUExecutionProvider']
        )
        self.lock = threading.Lock()

    def probabilities(self, audio):
        # Sequence model uses 512 fresh samples plus 64 previous samples per frame.
        frames = np.pad(audio, (0, (-len(audio)) % 512)).reshape(-1, 512)
        state = np.zeros((1, 1, 128), dtype=np.float32)
        # Both recurrent states are reset for every recording, including after silence.
        h, c = state, state.copy()
        probabilities = []
        with self.lock:
            # Bound inference memory for long dictations while preserving recurrent context.
            for start in range(0, len(frames), 256):
                chunk = frames[start:start + 256]
                context = np.zeros((len(chunk), 64), dtype=np.float32)
                if start:
                    context[0] = frames[start - 1, -64:]
                context[1:] = chunk[:-1, -64:]
                inputs = np.concatenate([context, chunk], axis=1).astype(np.float32)
                scores, h, c = self.session.run(None, {'input': inputs, 'h': h, 'c': c})
                probabilities.append(np.asarray(scores).reshape(-1))
        return np.concatenate(probabilities) if probabilities else np.zeros(0, dtype=np.float32)

    def speech_bounds(self, audio):
        scores = self.probabilities(audio)
        speech = scores >= 0.6
        # Require at least 128 ms overall and a 96 ms continuous speech run.
        if np.count_nonzero(speech) < 4 or not np.any(np.convolve(speech.astype(int), np.ones(3, dtype=int), 'valid') >= 3):
            return None
        voiced = np.flatnonzero(scores >= 0.35)
        return max(0, int(voiced[0]) * 512 - 2560), min(len(audio), (int(voiced[-1]) + 1) * 512 + 2560)


@lru_cache(maxsize=1)
def get_speech_detector(model_path):
    return SpeechDetector(model_path)
