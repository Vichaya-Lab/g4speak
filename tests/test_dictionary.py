"""Vocabulary persistence, matching, migration, and the minimal editor."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from g4speak.text.dictionary import PersonalDictionary
from g4speak.ui.dictionary_dialog import DictionaryDialog
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QLabel


class TemporaryDictionaryTestCase(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'settings' / 'dictionary.json'
        self.dictionary = PersonalDictionary(self.path)


class DictionaryTests(TemporaryDictionaryTestCase):
    def test_missing_file_is_empty_without_creating_settings(self):
        self.assertEqual(self.dictionary.words, ())
        self.assertEqual(self.dictionary.prompt(), '')
        self.assertIsNone(self.dictionary.load_error)
        self.assertEqual(self.dictionary.apply('hello'), 'hello')
        self.assertFalse(self.path.exists())

    def test_words_persist_and_can_be_edited_and_deleted(self):
        self.dictionary.save(['Gemini', 'คลอดด์'])
        reopened = PersonalDictionary(self.path)
        self.assertEqual(reopened.words, ('Gemini', 'คลอดด์'))
        self.assertIn('คลอดด์', self.path.read_text(encoding='utf-8'))
        reopened.save(['Gemini Pro'])
        self.assertEqual(PersonalDictionary(self.path).words, ('Gemini Pro',))
        reopened.save([])
        self.assertEqual(PersonalDictionary(self.path).words, ())

    def test_spelling_casing_does_not_replace_unrelated_words(self):
        self.dictionary.save(['Gemini', 'AI'])
        self.assertEqual(self.dictionary.apply('gemini ai said aim ai_2'), 'Gemini AI said aim ai_2')
        self.assertEqual(self.dictionary.apply('ใช้geminiทำงาน'), 'ใช้Geminiทำงาน')
        self.assertEqual(self.dictionary.apply('เจมินาย'), 'เจมินาย')

    def test_longest_literal_phrase_matches(self):
        self.dictionary.save(['Claude', 'Claude Code', 'C++'])
        self.assertEqual(self.dictionary.apply('claude code uses c++'), 'Claude Code uses C++')

    def test_invalid_entries_leave_file_and_active_words_unchanged(self):
        self.dictionary.save(['Gemini'])
        original = self.path.read_bytes()
        for words in ([''], ['A', 'a'], ['x\ny'], ['x\ty'], ['x' * 201], ['word'] * 501, [('old', 'new')]):
            with self.subTest(words=words[:2]):
                with self.assertRaises(ValueError):
                    self.dictionary.save(words)
                self.assertEqual(self.path.read_bytes(), original)
                self.assertEqual(self.dictionary.words, ('Gemini',))

    def test_short_hint_is_bounded_without_cutting_multilingual_words(self):
        words = ['Gemini', 'ภาษาไทย', *[f'product{index}' for index in range(100)]]
        self.dictionary.save(words)
        prompt = self.dictionary.prompt()
        self.assertLessEqual(len(prompt.encode('utf-8')), 200)
        self.assertTrue(prompt.startswith('Gemini, ภาษาไทย'))
        self.assertTrue(all(word in words for word in prompt.split(', ')))
        self.assertEqual(len(self.dictionary.words), len(words))

    def test_legacy_pairs_preserve_desired_spellings_without_requiring_sources(self):
        self.path.parent.mkdir()
        self.path.write_text(json.dumps({'version': 1, 'entries': [['เจมินาย', 'Gemini'], ['jemini', 'Gemini'], ['คลอด', 'Claude']]}), encoding='utf-8')
        reopened = PersonalDictionary(self.path)
        self.assertIsNone(reopened.load_error)
        self.assertEqual(reopened.words, ('Gemini', 'Claude'))
        reopened.save(list(reopened.words))
        self.assertEqual(json.loads(self.path.read_text(encoding='utf-8')), {'version': 2, 'words': ['Gemini', 'Claude']})

    def test_failed_write_preserves_file_and_active_words(self):
        self.dictionary.save(['Gemini'])
        original = self.path.read_bytes()
        with patch('g4speak.text.dictionary.os.replace', side_effect=OSError('disk error')):
            with self.assertRaises(OSError):
                self.dictionary.save(['Claude'])
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.dictionary.words, ('Gemini',))
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_corrupt_file_is_reported_without_overwriting_it(self):
        self.path.parent.mkdir()
        for content in ('{broken', json.dumps({'version': 2, 'words': 'invalid'}), json.dumps({'version': 9, 'words': []})):
            self.path.write_text(content, encoding='utf-8')
            reopened = PersonalDictionary(self.path)
            self.assertIsNotNone(reopened.load_error)
            self.assertEqual(reopened.apply('hello'), 'hello')
            self.assertEqual(self.path.read_text(encoding='utf-8'), content)


class DictionaryDialogTests(TemporaryDictionaryTestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def dialog(self):
        dialog = DictionaryDialog(self.dictionary)
        self.addCleanup(dialog.close)
        return dialog

    def test_editor_saves_only_desired_words_and_reopens(self):
        dialog = self.dialog()
        dialog.editor.setPlainText('Gemini\n\nClaude Code\n')
        dialog.buttons.button(QDialogButtonBox.StandardButton.Save).click()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(self.dictionary.words, ('Gemini', 'Claude Code'))
        reopened = self.dialog()
        self.assertEqual(reopened.editor.toPlainText(), 'Gemini\nClaude Code')
        self.assertEqual(reopened.count_label.text(), '2 words')

    def test_cancel_does_not_change_saved_words(self):
        self.dictionary.save(['Gemini'])
        dialog = self.dialog()
        dialog.editor.setPlainText('Claude')
        dialog.buttons.button(QDialogButtonBox.StandardButton.Cancel).click()
        self.assertEqual(self.dictionary.words, ('Gemini',))
        self.assertEqual(PersonalDictionary(self.path).words, ('Gemini',))

    def test_editing_and_clearing_words(self):
        self.dictionary.save(['Gemini', 'Claude'])
        dialog = self.dialog()
        dialog.editor.setPlainText('Gemini Pro')
        dialog._save()
        self.assertEqual(PersonalDictionary(self.path).words, ('Gemini Pro',))
        dialog.editor.clear()
        dialog._save()
        self.assertEqual(PersonalDictionary(self.path).words, ())

    def test_duplicate_word_keeps_editor_open_with_english_error(self):
        dialog = self.dialog()
        dialog.editor.setPlainText('Gemini\ngemini')
        dialog._save()
        self.assertIn('already listed', dialog.error_label.text())
        self.assertNotEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertFalse(self.path.exists())

    def test_ui_labels_are_english(self):
        dialog = self.dialog()
        labels = [dialog.windowTitle(), dialog.editor.placeholderText(), *[label.text() for label in dialog.findChildren(QLabel)]]
        labels += [button.text() for button in dialog.buttons.buttons()]
        self.assertTrue(all(text.isascii() for text in labels))
