"""Contextual proofreading, fallback, and preservation regressions; no network."""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from g4speak import app as main
from dotenv import dotenv_values
from PySide6.QtCore import QObject
from g4speak.text.dictionary import PersonalDictionary
from g4speak.text.proofreading import protected_content_matches, text_chunks


class SmartRefinerTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {'GROQ_REFINER': 'true', 'LOCAL_REFINER': 'false', 'GROQ_LLM_MODEL': 'qwen/qwen3.8-27b'})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.client = MagicMock()
        self.client.with_options.return_value = self.client
        self.refiner = main.TextRefiner(groq_client_getter=lambda: self.client)

    def result(self, text, reason='stop'):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text), finish_reason=reason)])

    def test_contextual_thai_spelling_and_english_punctuation(self):
        for raw, expected in (('ผมไปโรงบาลมา', 'ผมไปโรงพยาบาลมา'), ('hello world this is a test', 'Hello world, this is a test.')):
            with self.subTest(raw=raw):
                self.client.chat.completions.create.return_value = self.result(expected)
                self.assertEqual(self.refiner.refine(raw), expected)
        options = self.client.chat.completions.create.call_args.kwargs
        self.assertEqual(options['reasoning_effort'], 'low')
        self.assertGreater(options['max_tokens'], 160)

    def test_reported_folder_and_thai_vocabulary_errors_are_accepted_in_context(self):
        pairs = (
            ('ช่วยจัด fonder ให้เป็นระเบียบ', 'ช่วยจัด folder ให้เป็นระเบียบ'),
            ('เพิ่ม sub ในพจนานุกรมส่วนตัว', 'เพิ่มศัพท์ในพจนานุกรมส่วนตัว'),
            ('ใช้ sub เป็นชื่อคำสั่งย่อยในโปรแกรม', 'ใช้ sub เป็นชื่อคำสั่งย่อยในโปรแกรม'),
        )
        for raw, expected in pairs:
            with self.subTest(raw=raw):
                self.client.chat.completions.create.return_value = self.result(expected)
                self.assertEqual(self.refiner.refine(raw), expected)

    def test_dictionary_supplied_as_data_with_transcript(self):
        with tempfile.TemporaryDirectory() as directory:
            dictionary = PersonalDictionary(Path(directory) / 'dictionary.json')
            dictionary.save(['Example Term', 'Example Name'])
            self.refiner._dictionary = dictionary
            self.client.chat.completions.create.return_value = self.result('Use Example Term today.')
            self.assertEqual(self.refiner.refine('use example term today'), 'Use Example Term today.')
            messages = self.client.chat.completions.create.call_args.kwargs['messages']
            data = json.loads(messages[-1]['content'])
            self.assertEqual(data['vocabulary'], ['Example Term', 'Example Name'])
            self.assertEqual(data['transcript'], 'use example term today')

    def test_long_transcript_is_chunked_without_losing_tail(self):
        raw = ('hello world this is a test. ' * 90 + 'keep the final sentence.').strip()
        def echo(**options):
            data = json.loads(options['messages'][-1]['content'])
            self.assertLessEqual(len(data['transcript']), 1000)
            return self.result(data['transcript'])
        self.client.chat.completions.create.side_effect = echo
        self.assertEqual(self.refiner.refine(raw), raw)
        self.assertGreater(self.client.chat.completions.create.call_count, 1)

    def test_chunking_preserves_characters_including_unspaced_thai(self):
        for raw in ('hello world. ' * 300, 'ทดสอบ' * 800):
            chunks = text_chunks(raw)
            self.assertEqual(''.join(chunks), raw)
            self.assertTrue(all(len(chunk) <= 1000 for chunk in chunks))

    def test_changed_numbers_negations_and_identifiers_are_rejected(self):
        pairs = (
            ('pay 2500 today', 'pay 3500 today'),
            ('do not delete the file', 'do delete the file'),
            ('do delete the file', 'do not delete the file'),
            ('ห้ามลบไฟล์นี้', 'ลบไฟล์นี้'),
            ('ไม่ส่งไฟล์วันนี้', 'ส่งไฟล์วันนี้'),
            ('open config.json', 'open settings.json'),
            ('use the API today', 'use the SDK today'),
            ('send to user@example.com', 'send to admin@example.com'),
        )
        for raw, output in pairs:
            with self.subTest(raw=raw):
                self.client.chat.completions.create.return_value = self.result(output)
                self.assertEqual(self.refiner.refine(raw), main.format_tech_casing(main.format_spacing(raw)))

    def test_case_and_contraction_changes_preserve_identifiers_and_polarity(self):
        self.assertTrue(protected_content_matches('do not call the API', "don't call the api"))
        self.assertFalse(protected_content_matches('call the API', 'call the APIs'))

    def test_dictionary_allows_phonetic_names_inside_retained_thai_context(self):
        valid = main.TextRefiner._is_valid_correction
        words = ['Python', 'API']
        self.assertTrue(valid('ผมใช้ไพทอนเขียนเอพีไอ', 'ผมใช้ Python เขียน API', vocabulary=words))
        self.assertFalse(valid('สวัสดีครับ', 'Python', vocabulary=words))
        self.assertFalse(valid('ทดสอบระบบ', 'this is a system test', vocabulary=words))

    def test_incomplete_response_and_network_errors_keep_original(self):
        self.client.chat.completions.create.return_value = self.result('part', reason='length')
        self.assertEqual(self.refiner.refine('keep this entire sentence'), 'keep this entire sentence')
        self.client.chat.completions.create.side_effect = RuntimeError('unavailable')
        self.assertEqual(self.refiner.refine('keep this entire sentence'), 'keep this entire sentence')

    def test_rate_limit_preserves_all_text_and_avoids_further_requests(self):
        error = RuntimeError('quota')
        error.status_code = 429
        self.client.chat.completions.create.side_effect = error
        notice = MagicMock()
        self.refiner._on_unavailable = notice
        raw = ('keep this sentence. ' * 100).strip()
        self.assertEqual(self.refiner.refine(raw), raw)
        self.assertEqual(self.refiner.refine('keep this too'), 'keep this too')
        self.client.chat.completions.create.assert_called_once()
        notice.assert_called_once()

    def test_refinement_stops_at_deadline_without_request(self):
        self.assertEqual(self.refiner.refine('keep this text', deadline=time.monotonic() - 1), 'keep this text')
        self.client.chat.completions.create.assert_not_called()

    def test_cancelled_proofreading_does_not_start_another_chunk(self):
        cancelled = threading.Event()
        def cancel_during_request(**options):
            cancelled.set()
            return self.result(json.loads(options['messages'][-1]['content'])['transcript'])
        self.client.chat.completions.create.side_effect = cancel_during_request
        with self.assertRaises(main.CancelledError):
            self.refiner.refine('hello world. ' * 200, cancelled=cancelled)
        self.client.chat.completions.create.assert_called_once()

    def test_fast_mode_skips_cloud_and_budget_scales_for_long_text(self):
        with patch.dict(os.environ, {'GROQ_REFINER': 'false'}):
            self.assertEqual(self.refiner.refine('hello world'), 'hello world')
            self.client.chat.completions.create.assert_not_called()
        self.assertGreaterEqual(main.refinement_budget('hello'), 6)
        self.assertEqual(main.refinement_budget('x' * 100000), 20)

    def test_unknown_configured_model_does_not_receive_qwen_options(self):
        with patch.dict(os.environ, {'GROQ_LLM_MODEL': 'custom-model'}):
            self.client.chat.completions.create.return_value = self.result('Hello world.')
            self.refiner.refine('hello world')
            self.assertNotIn('reasoning_effort', self.client.chat.completions.create.call_args.kwargs)


class DictationModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = main.QApplication.instance() or main.QApplication([])

    def controller(self):
        controller = main.G4SpeakApp.__new__(main.G4SpeakApp)
        QObject.__init__(controller)
        controller._app = self.app
        controller.stt = SimpleNamespace(_language='auto')
        controller._notify_error = MagicMock()
        self.addCleanup(controller.deleteLater)
        return controller

    def test_tray_offers_smart_and_fast_with_current_selection(self):
        controller = self.controller()
        with patch.object(main, 'QSystemTrayIcon'), patch.object(main, 'is_autostart_enabled', return_value=False), patch.dict(os.environ, {'GROQ_REFINER': 'true'}):
            controller._setup_tray()
            actions = controller._mode_group.actions()
            self.assertEqual([action.text() for action in actions], ['Enhanced', 'Standard'])
            self.assertEqual([action.isChecked() for action in actions], [True, False])

    def test_mode_choices_persist_across_settings_reload(self):
        controller = self.controller()
        with tempfile.TemporaryDirectory() as directory:
            settings = Path(directory) / '.env'
            settings.write_text('GROQ_REFINER=false\n', encoding='utf-8')
            with patch.object(main, 'ENV_FILE', settings), patch.object(main, 'ensure_env_file'), patch.object(controller, '_reload_keys'), patch.dict(os.environ):
                for mode, enabled in (('smart', True), ('fast', False)):
                    controller._set_dictation_mode(SimpleNamespace(data=lambda: mode))
                    self.assertEqual(dotenv_values(settings)['GROQ_REFINER'], str(enabled).lower())
                    main.load_dotenv(settings, override=True)
                    self.assertEqual(main.smart_mode_enabled(), enabled)
        controller._notify_error.assert_not_called()
