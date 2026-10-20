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
from g4speak.text.proofreading import protected_content_matches, text_chunks, has_unsupported_thai_replacement


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
        self.assertEqual(options['reasoning_effort'], 'none')
        self.assertEqual(options['extra_body'], {'reasoning_format': 'hidden'})
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

    def test_proofreading_works_with_1000_output_token_account_limit(self):
        def limited_account(**options):
            if options['max_tokens'] > 1000:
                error = RuntimeError('Requested output tokens exceed OTPM limit 1000')
                error.status_code = 429
                raise error
            raw = json.loads(options['messages'][-1]['content'])['transcript']
            return self.result(raw.replace('โรงบาล', 'โรงพยาบาล'))

        self.client.chat.completions.create.side_effect = limited_account
        notice = MagicMock()
        self.refiner._on_unavailable = notice
        for raw in ('ผมไปโรงบาลมา', 'ทดสอบระบบนี้ ' * 65 + 'ผมไปโรงบาลมา'):
            with self.subTest(length=len(raw)):
                self.assertEqual(self.refiner.refine(raw.strip()), raw.strip().replace('โรงบาล', 'โรงพยาบาล'))
        notice.assert_not_called()

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

    def test_multilingual_chunks_fit_token_budget_and_keep_combining_marks(self):
        import unicodedata
        for raw in ('ทดสอบการรู้จำคำศัพท์ที่ซับซ้อน' * 80, 'check this sentence. ' * 200, '👋' * 500):
            chunks = text_chunks(raw, max_bytes=700)
            self.assertEqual(''.join(chunks), raw)
            self.assertTrue(all(len(chunk.encode('utf-8')) <= 700 for chunk in chunks))
            self.assertTrue(all(not unicodedata.category(chunk[0]).startswith('M') for chunk in chunks))

    def test_thai_output_fits_byte_budget_and_neighbors_are_read_only(self):
        raw = ('ช่วยตรวจสอบประสิทธิภาพของระบบนี้ด้วย ' * 40).strip()
        calls = []
        def echo(**options):
            data = json.loads(options['messages'][-1]['content'])
            self.assertLessEqual(len(data['transcript'].encode('utf-8')), 700)
            self.assertLessEqual(options['max_tokens'], 1000)
            calls.append(data)
            return self.result(data['transcript'])
        self.client.chat.completions.create.side_effect = echo
        self.assertEqual(self.refiner.refine(raw), raw)
        self.assertEqual(calls[0]['context_before'], '')
        self.assertTrue(calls[0]['context_after'])
        self.assertTrue(calls[1]['context_before'])
        self.assertEqual(calls[-1]['context_after'], '')

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

    def test_rejected_translation_reconsiders_original_with_bounded_reasoning(self):
        raw = 'ช่วยตรวจคูเบอร์เนทีสคลัสเตอร์ให้หน่อย'
        expected = 'ช่วยตรวจ Kubernetes คลัสเตอร์ให้หน่อย'
        self.refiner._dictionary = SimpleNamespace(words=('Kubernetes',))
        self.client.chat.completions.create.side_effect = [
            self.result('ช่วยตรวจ Kubernetes cluster ให้หน่อย'), self.result(expected),
        ]
        self.assertEqual(self.refiner.refine(raw), expected)
        calls = self.client.chat.completions.create.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertEqual([call.kwargs['reasoning_effort'] for call in calls], ['none', 'low'])
        self.assertEqual(calls[1].kwargs['max_tokens'], 1000)
        for call in calls:
            self.assertEqual(json.loads(call.kwargs['messages'][-1]['content'])['transcript'], raw)

    def test_failed_reconsideration_never_relaxes_content_guards_or_retries_again(self):
        raw = 'do not delete the file'
        self.refiner._dictionary = SimpleNamespace(words=('Example',))
        self.client.chat.completions.create.return_value = self.result('do delete the file')
        self.assertEqual(self.refiner.refine(raw), raw)
        self.assertEqual(self.client.chat.completions.create.call_count, 2)

    def test_large_local_thai_rewrite_is_not_hidden_by_long_unchanged_context(self):
        raw = 'เมื่อพิจารณาทุกสิ่งแล้วก็ไม่น่าแปลกใจเลยหากปรรณพบุรุษของเราจะแก้ไขปัญหาเรื่องโปรตีน'
        invented = raw.replace('ปรรณพบุรุษ', 'ปราชญ์บุรุษ')
        self.client.chat.completions.create.return_value = self.result(invented)
        self.assertEqual(self.refiner.refine(raw), raw)
        self.client.chat.completions.create.assert_called_once()
        self.assertTrue(main.TextRefiner._is_valid_correction(raw, raw.replace('ปรรณพบุรุษ', 'บรรพบุรุษ')))
        self.assertTrue(main.TextRefiner._is_valid_correction('พื้นผิวของดวงจำประกอบด้วยหิน', 'พื้นผิวของดวงจันทร์ประกอบด้วยหิน'))
        self.assertTrue(has_unsupported_thai_replacement('ทดสอบกขคระบบ', 'ทดสอบงจฉระบบ'))
        self.assertFalse(has_unsupported_thai_replacement('ทดสอบกขคระบบ', 'ทดสอบงจฉระบบ', ('งจฉระบบ',)))

    def test_reasoning_retry_is_skipped_when_deadline_is_near(self):
        deadline = time.monotonic() + 2
        self.refiner._dictionary = SimpleNamespace(words=('Example',))
        with patch.object(main.time, 'monotonic', return_value=deadline - 1) as clock:
            def slow_rejected_response(**options):
                clock.return_value = deadline - .5
                return self.result('do delete the file')
            self.client.chat.completions.create.side_effect = slow_rejected_response
            self.assertEqual(self.refiner.refine('do not delete the file', deadline=deadline), 'do not delete the file')
        self.client.chat.completions.create.assert_called_once()

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
            self.assertNotIn('extra_body', self.client.chat.completions.create.call_args.kwargs)


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
