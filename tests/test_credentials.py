"""Credentials remain masked, save through one controlled callback, and report failures."""
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))
from PySide6.QtWidgets import QApplication, QDialog, QLineEdit
from g4speak.ui.credentials_dialog import CredentialsDialog
from g4speak.app import user_error_message


class CredentialsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_masked_key_is_saved_without_changing_other_settings(self):
        save = MagicMock()
        dialog = CredentialsDialog('test-key', save)
        self.addCleanup(dialog.close)
        self.assertEqual(dialog.key_input.echoMode(), QLineEdit.EchoMode.Password)
        dialog._save()
        save.assert_called_once_with('test-key')
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)

    def test_invalid_key_and_save_failure_keep_dialog_open(self):
        save = MagicMock(side_effect=OSError('private diagnostic details'))
        dialog = CredentialsDialog('', save)
        self.addCleanup(dialog.close)
        dialog._save()
        save.assert_not_called()
        dialog.key_input.setText('test-key')
        dialog._save()
        self.assertNotEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertNotIn('private diagnostic', dialog.error_label.text())

    def test_service_notifications_hide_raw_diagnostics(self):
        self.assertIn('API Credentials', user_error_message('401 authentication failed API_KEY'))
        self.assertIn('longer than expected', user_error_message('TimeoutError: request timed out'))
        self.assertNotIn('traceback', user_error_message('Traceback: private error dump'))
