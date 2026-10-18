"""Native credentials form without exposing configuration files to users."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QLabel, QLineEdit, QVBoxLayout,
)


class CredentialsDialog(QDialog):
    def __init__(self, key, save_key, parent=None):
        super().__init__(parent)
        self._save_key = save_key
        self.setWindowTitle('API Credentials - G4Speak')
        self.setMinimumWidth(400)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 20)
        layout.setSpacing(12)
        layout.addWidget(QLabel('Groq API Key'))
        self.key_input = QLineEdit(key)
        self.key_input.setAccessibleName('Groq API Key')
        self.key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_input.setPlaceholderText('Enter your API key')
        layout.addWidget(self.key_input)
        show_key = QCheckBox('Show API key')
        show_key.toggled.connect(lambda visible: self.key_input.setEchoMode(QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password))
        layout.addWidget(show_key)
        layout.addWidget(QLabel('Your API key is stored locally on this device.'))
        self.error_label = QLabel()
        self.error_label.setTextFormat(Qt.TextFormat.PlainText)
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        layout.addWidget(self.error_label)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self._save)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def _save(self):
        key = self.key_input.text().strip()
        if not key or any(char.isspace() for char in key):
            self.error_label.setText('Enter a valid API key without spaces.')
            self.error_label.show()
            return
        try:
            self._save_key(key)
        except OSError:
            self.error_label.setText('Your API key could not be saved. Please check folder permissions.')
            self.error_label.show()
            return
        self.accept()
