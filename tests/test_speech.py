"""Audio and latency regressions; no microphone, API key, or network needed."""
import os
import sys
import threading
import tempfile
import time
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from g4speak import app as main
from g4speak.text.dictionary import PersonalDictionary


class SpeechTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with wave.open(str(Path(__file__).parent / 'fixtures' / 'jfk.wav'), 'rb') as source:
            cls.real_speech = np.frombuffer(source.readframes(source.getnframes()), dtype=np.int16).astype(np.float32) / 32768

    @staticmethod
    def voice(seconds=0.3, amplitude=0.004):
        t = np.arange(int(seconds * main.SAMPLE_RATE)) / main.SAMPLE_RATE
        return (amplitude * np.sin(2 * np.pi * 220 * t)).astype(np.float32)

    def test_quiet_short_word_is_kept_and_amplified(self):
        audio = self.real_speech[16000:32000] * 0.02
        prepared = main.prepare_speech_audio(audio)
        self.assertGreater(len(prepared), 0)
        self.assertGreater(np.max(np.abs(prepared)), np.max(np.abs(audio)))

    def test_subsecond_speech_is_not_rejected_by_duration(self):
        audio = self.real_speech[16000:28000]  # 750 ms of real speech
        self.assertGreater(len(main.prepare_speech_audio(audio)), 0)

    def test_silence_dc_offset_and_single_click_are_rejected(self):
        for audio in (np.zeros(16000), np.full(16000, 0.03), np.eye(1, 16000, 5000)[0]):
            self.assertEqual(len(main.prepare_speech_audio(audio)), 0)

    def test_long_silence_does_not_dilute_quiet_word(self):
        word = self.real_speech[16000:24000] * 0.1
        prepared = main.prepare_speech_audio(np.concatenate([np.zeros(32000), word, np.zeros(32000)]))
        self.assertGreater(len(prepared), 0)
        self.assertLess(len(prepared), 16000)

    def test_loud_speech_is_not_clipped_by_gain(self):
        prepared = main.prepare_speech_audio(self.real_speech)
        self.assertLessEqual(np.max(np.abs(prepared)), 0.95)

    def engine(self, text, segments, language='auto'):
        with patch.dict(os.environ, {'GROQ_API_KEY': 'test', 'GROQ_STT_LANGUAGE': language}), patch.object(main, 'OpenAI') as factory:
            engine = main.SpeechToTextEngine()
            self.assertEqual(factory.call_args.kwargs['max_retries'], 0)
        if segments == []:
            segments = [dict(text=text, no_speech_prob=0.01, avg_logprob=-0.1)]
        engine._groq_client.audio.transcriptions.create.return_value = SimpleNamespace(text=text, segments=segments)
        return engine

    def test_dictionary_segments_preserve_moderate_confidence_thai(self):
        engine = self.engine('สวัสดีครับ', [{'text': 'สวัสดีครับ', 'no_speech_prob': 0.4, 'avg_logprob': -0.8}])
        text, no_speech, logprob = engine.transcribe(self.voice())
        self.assertEqual(text, 'สวัสดีครับ')
        self.assertEqual((no_speech, logprob), (0.4, -0.8))
        self.assertNotIn('language', engine._groq_client.audio.transcriptions.create.call_args.kwargs)

    def test_language_hint_is_sent_when_selected(self):
        for language in ('th', 'en'):
            engine = self.engine('test', [], language)
            engine.transcribe(self.voice())
            self.assertEqual(engine._groq_client.audio.transcriptions.create.call_args.kwargs['language'], language)

    def test_request_uses_duration_timeout_and_only_explicit_vocabulary(self):
        engine = self.engine('Gemini', [])
        engine.transcribe(self.voice(), timeout=75.0, vocabulary='Gemini, Claude Code')
        options = engine._groq_client.audio.transcriptions.create.call_args.kwargs
        self.assertEqual(options['timeout'], 75.0)
        self.assertEqual(options['prompt'], 'Gemini, Claude Code')
        engine.transcribe(self.voice())
        options = engine._groq_client.audio.transcriptions.create.call_args.kwargs
        self.assertNotIn('prompt', options)
        self.assertGreaterEqual(options['timeout'], 30.0)

    def test_longer_recordings_receive_more_time_with_a_finite_limit(self):
        self.assertGreaterEqual(main.processing_budget(1), 30)
        self.assertGreater(main.processing_budget(120), main.processing_budget(1))
        self.assertEqual(main.processing_budget(600), 180)
        self.assertEqual(main.processing_budget(6000), 180)

    def test_more_than_one_minute_of_real_speech_reaches_stt_intact(self):
        stt = MagicMock(is_ready=True)
        stt.transcribe.return_value = ('Long dictation.', .01, -.1)
        worker, done, failed = self.worker(stt, main.TextRefiner())
        worker._audio = np.tile(self.real_speech, int(np.ceil(120 * main.SAMPLE_RATE / len(self.real_speech))))
        with patch.dict(os.environ, {'GROQ_REFINER': 'false', 'LOCAL_REFINER': 'false'}):
            worker.run()
        self.assertEqual(done, ['Long dictation.'])
        self.assertEqual(failed, [])
        self.assertGreater(len(stt.transcribe.call_args.args[0]), 60 * main.SAMPLE_RATE)
        self.assertGreater(stt.transcribe.call_args.kwargs['timeout'], 30)

    def test_vad_chunking_preserves_sequence_probabilities(self):
        detector = main.get_speech_detector(main._asset_path('silero_vad_v6.onnx'))
        audio = self.real_speech
        frames = np.pad(audio, (0, (-len(audio)) % 512)).reshape(-1, 512)
        self.assertGreater(len(frames), 256)
        context = np.zeros((len(frames), 64), dtype=np.float32)
        context[1:] = frames[:-1, -64:]
        state = np.zeros((1, 1, 128), dtype=np.float32)
        with detector.lock:
            expected, _, _ = detector.session.run(None, {'input': np.concatenate([context, frames], axis=1), 'h': state, 'c': state.copy()})
        np.testing.assert_allclose(detector.probabilities(audio), np.asarray(expected).reshape(-1), atol=1e-6)

    def test_noisy_tail_does_not_erase_real_speech(self):
        speech = dict(text='ใช้ Python เขียน API', start=0, end=2, no_speech_prob=0.05, avg_logprob=-0.7)
        noise = dict(text='Thanks for watching', start=2, end=4, no_speech_prob=0.95, avg_logprob=-1.5)
        for convert in (lambda s: s, lambda s: SimpleNamespace(**s)):
            engine = self.engine('ใช้ Python เขียน API Thanks for watching', [convert(speech), convert(noise)])
            self.assertEqual(engine.transcribe(self.voice())[0], speech['text'])

    def test_low_confidence_noise_is_rejected(self):
        engine = self.engine('noise', [dict(no_speech_prob=0.95, avg_logprob=-1.5)])
        self.assertEqual(engine.transcribe(self.voice())[0], '')

    def test_single_letter_dictation_is_kept(self):
        engine = self.engine('I', [])
        self.assertEqual(engine.transcribe(self.voice())[0], 'I')

    def worker(self, stt, refiner):
        worker = main.ProcessingThread(self.real_speech[16000:32000], stt, refiner)
        done, failed = [], []
        worker.done.connect(done.append)
        worker.failed.connect(failed.append)
        return worker, done, failed

    def test_greeting_and_mixed_language_survive_pipeline(self):
        for text in ('สวัสดีครับ', 'ใช้ Python เขียน API', 'Hello world'):
            stt = SimpleNamespace(is_ready=True, transcribe=lambda audio, **kwargs: (text, 0.4, -0.8))
            worker, done, failed = self.worker(stt, main.TextRefiner())
            with patch.dict(os.environ, {'GROQ_REFINER': 'false', 'LOCAL_REFINER': 'false'}):
                worker.run()
            self.assertEqual(done, [text])
            self.assertEqual(failed, [])

    def test_personal_dictionary_applies_to_verified_speech_after_refinement(self):
        with tempfile.TemporaryDirectory() as directory:
            dictionary = PersonalDictionary(Path(directory) / 'dictionary.json')
            dictionary.save(['Gemini'])
            stt = SimpleNamespace(is_ready=True, transcribe=lambda audio, **kwargs: ('ผมใช้geminiทำงาน', .01, -.1))
            worker, done, failed = self.worker(stt, main.TextRefiner())
            worker._dictionary = dictionary
            with patch.dict(os.environ, {'GROQ_REFINER': 'false', 'LOCAL_REFINER': 'false'}):
                worker.run()
            self.assertEqual(done, ['ผมใช้ Gemini ทำงาน'])
            self.assertEqual(failed, [])

    def test_vocabulary_reaches_recognition_after_speech_detection(self):
        with tempfile.TemporaryDirectory() as directory:
            dictionary = PersonalDictionary(Path(directory) / 'dictionary.json')
            dictionary.save(['Gemini', 'Claude Code'])
            stt = MagicMock(is_ready=True)
            stt.transcribe.return_value = ('Gemini', .01, -.1)
            worker, done, failed = self.worker(stt, main.TextRefiner())
            worker._dictionary = dictionary
            with patch.dict(os.environ, {'GROQ_REFINER': 'false', 'LOCAL_REFINER': 'false'}):
                worker.run()
            self.assertEqual(stt.transcribe.call_args.kwargs['vocabulary'], 'Gemini, Claude Code')
            self.assertEqual(done, ['Gemini'])
            self.assertEqual(failed, [])

    def test_cancelling_a_slow_request_returns_without_typing_late_result(self):
        release = threading.Event()
        stt = SimpleNamespace(is_ready=True, transcribe=lambda audio, **kwargs: (release.wait(2) and 'late result', 0, 0))
        worker, done, failed = self.worker(stt, main.TextRefiner())
        cancel = threading.Timer(.05, worker.cancel)
        started = time.monotonic()
        cancel.start()
        try:
            worker.run()
            self.assertLess(time.monotonic() - started, .5)
            self.assertEqual(done, [])
            self.assertEqual(failed, [])
        finally:
            release.set()
            cancel.join()
        self.assertEqual(done, [])

    def test_dictionary_cannot_turn_rejected_hallucination_into_text(self):
        stt = SimpleNamespace(is_ready=True, transcribe=lambda audio, **kwargs: ('Thank you.', .4, -.8))
        worker, done, failed = self.worker(stt, main.TextRefiner())
        worker._dictionary = MagicMock()
        worker._dictionary.apply.return_value = 'invented text'
        worker.run()
        worker._dictionary.apply.assert_not_called()
        self.assertEqual(done, [''])
        self.assertEqual(failed, [])

    def test_one_second_recording_allows_cloud_result_after_two_seconds(self):
        def transcribe(audio, **kwargs):
            time.sleep(2.05)
            return 'Hello world', 0.01, -0.1

        stt = SimpleNamespace(is_ready=True, transcribe=transcribe)
        worker, done, failed = self.worker(stt, main.TextRefiner())
        with patch.dict(os.environ, {'GROQ_REFINER': 'false', 'LOCAL_REFINER': 'false'}):
            worker.run()
        self.assertEqual(done, ['Hello world'])
        self.assertEqual(failed, [])

    def test_short_thanks_require_acoustic_confidence(self):
        for text in ('Thank you.', 'THANKS!', 'ขอบคุณครับ'):
            for no_speech, logprob, expected in (
                (0.4, -0.1, ''), (0.01, -0.8, ''), (0.01, -0.1, text),
            ):
                with self.subTest(text=text, no_speech=no_speech, logprob=logprob):
                    stt = SimpleNamespace(is_ready=True, transcribe=lambda audio, **kwargs: (text, no_speech, logprob))
                    worker, done, failed = self.worker(stt, main.TextRefiner())
                    with patch.dict(os.environ, {'GROQ_REFINER': 'false', 'LOCAL_REFINER': 'false'}):
                        worker.run()
                    self.assertEqual(done, [expected])
                    self.assertEqual(failed, [])

    def test_stalled_stt_times_out_and_late_result_is_discarded(self):
        release = threading.Event()
        stt = SimpleNamespace(is_ready=True, transcribe=lambda audio, **kwargs: (release.wait(2), 0, 0))
        worker, done, failed = self.worker(stt, main.TextRefiner())
        started = time.monotonic()
        try:
            with patch.object(main, 'PROCESSING_BUDGET_S', 0.08):
                worker.run()
            self.assertLess(time.monotonic() - started, 0.5)
            self.assertEqual(done, [])
            self.assertEqual(len(failed), 1)
            self.assertIn('do not need to record longer', failed[0])
        finally:
            release.set()
        self.assertEqual(done, [])

    def test_slow_refiner_falls_back_to_transcript(self):
        release = threading.Event()
        stt = SimpleNamespace(is_ready=True, transcribe=lambda audio, **kwargs: ('hello world', 0, 0))
        refiner = SimpleNamespace(refine=lambda raw, deadline, **kwargs: release.wait(2))
        worker, done, failed = self.worker(stt, refiner)
        worker._dictionary = MagicMock()
        worker._dictionary.apply.side_effect = lambda text: text.replace('hello', 'Hi')
        started = time.monotonic()
        try:
            with patch.object(main, 'PROCESSING_BUDGET_S', 1.0), patch.object(main, 'REFINEMENT_BUDGET_S', 0.08):
                worker.run()
            self.assertLess(time.monotonic() - started, 0.5)
            self.assertEqual(done, ['Hi world'])
            worker._dictionary.apply.assert_called_once_with('hello world')
            self.assertEqual(failed, [])
        finally:
            release.set()

    def test_local_model_is_not_loaded_in_bounded_pipeline(self):
        refiner = main.TextRefiner()
        with patch.dict(os.environ, {'LOCAL_REFINER': 'true', 'GROQ_REFINER': 'false'}), patch.object(refiner, '_ensure_loaded') as load:
            self.assertEqual(refiner.refine('hello world', deadline=time.monotonic() + 1), 'hello world')
            load.assert_not_called()

    def test_tail_callback_cannot_stop_a_new_session(self):
        recorder = main.RecorderThread()
        recorder.begin(1)
        recorder.stop(discard=True)
        recorder.begin(2)
        recorder.stop(expected_session=1)
        self.assertEqual(recorder._session, 2)

    def test_real_vad_rejects_hiss_hum_and_repeated_clicks(self):
        rng = np.random.default_rng(42)
        clicks = np.zeros(32000, dtype=np.float32)
        clicks[::1800] = 0.3
        for audio in (rng.normal(0, 0.005, 32000), self.voice(2, .02), clicks):
            self.assertEqual(len(main.prepare_speech_audio(audio)), 0)

    def test_no_speech_never_calls_stt_or_types(self):
        stt = MagicMock(is_ready=True)
        stt.transcribe.return_value = ('Thank you.', 0.01, -0.1)
        worker, done, failed = self.worker(stt, main.TextRefiner())
        worker._audio = np.random.default_rng(3).normal(0, 0.005, 16000).astype(np.float32)
        worker._dictionary = MagicMock()
        worker.run()
        stt.transcribe.assert_not_called()
        worker._dictionary.apply.assert_not_called()
        self.assertEqual(done, [''])
        self.assertEqual(failed, [])

    def test_vad_failure_never_bypasses_detection(self):
        stt = MagicMock(is_ready=True)
        worker, done, failed = self.worker(stt, main.TextRefiner())
        with patch.object(main, 'get_speech_detector', side_effect=RuntimeError('VAD unavailable')):
            worker.run()
        stt.transcribe.assert_not_called()
        self.assertEqual(done, [])
        self.assertEqual(len(failed), 1)

    def test_high_no_speech_rejected_even_when_words_look_confident(self):
        engine = self.engine('invented words', [dict(no_speech_prob=.66, avg_logprob=-.29)])
        self.assertEqual(engine.transcribe(self.voice())[0], '')

    def test_missing_confidence_does_not_count_as_confident_speech(self):
        for segments in (None, [dict(text='invented')]):
            engine = self.engine('invented', segments)
            self.assertEqual(engine.transcribe(self.voice())[0], '')

    def test_vad_resets_between_speech_and_noise(self):
        self.assertGreater(len(main.prepare_speech_audio(self.real_speech)), 0)
        self.assertEqual(len(main.prepare_speech_audio(self.voice(2))), 0)

    def test_real_speech_with_microphone_noise_is_kept(self):
        audio = self.real_speech * .1
        audio = audio + np.random.default_rng(4).normal(0, .001, len(audio))
        self.assertGreater(len(main.prepare_speech_audio(audio)), 0)


if __name__ == '__main__':
    unittest.main()
