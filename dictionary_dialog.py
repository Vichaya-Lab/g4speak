"""Minimal vocabulary editor; one desired spelling per line."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QPlainTextEdit, QVBoxLayout,
)


class DictionaryDialog(QDialog):
    def __init__(self, dictionary, parent=None):
        super().__init__(parent)
        self.dictionary = dictionary
        self.setWindowTitle("Dictionary - G4Speak")
        self.resize(420, 420)
        self.setMinimumSize(360, 320)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 20)
        layout.setSpacing(12)

        title = QLabel("Dictionary")
        font = title.font()
        font.setPointSize(17)
        font.setBold(True)
        title.setFont(font)
        layout.addWidget(title)
        layout.addWidget(QLabel("Add one word or phrase per line."))
        self.editor = QPlainTextEdit()
        self.editor.setAccessibleName("Dictionary words")
        self.editor.setToolTip("Put your most important words first. Recognition uses a short vocabulary hint.")
        self.editor.setPlaceholderText("Example name\nExample term\nExample phrase")
        self.editor.setPlainText("\n".join(dictionary.words))
        self.editor.setTabChangesFocus(True)
        self.editor.setStyleSheet("QPlainTextEdit { border: 1px solid palette(mid); border-radius: 8px; padding: 10px; }")
        layout.addWidget(self.editor, 1)

        self.error_label = QLabel()
        self.error_label.setTextFormat(Qt.TextFormat.PlainText)
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        layout.addWidget(self.error_label)
        if dictionary.load_error:
            self._show_error("Could not load your dictionary. Check the file before saving over it.")

        footer = QHBoxLayout()
        self.count_label = QLabel()
        footer.addWidget(self.count_label)
        footer.addStretch()
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setText("Save")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancel")
        self.buttons.accepted.connect(self._save)
        self.buttons.rejected.connect(self.reject)
        footer.addWidget(self.buttons)
        layout.addLayout(footer)
        self.editor.textChanged.connect(self._update_count)
        self._update_count()

    def _words(self):
        return [line.strip() for line in self.editor.toPlainText().splitlines() if line.strip()]

    def _update_count(self):
        count = len(self._words())
        self.count_label.setText(f"{count} word" if count == 1 else f"{count} words")

    def _show_error(self, text):
        self.error_label.setText(text)
        self.error_label.show()

    def _save(self):
        try:
            self.dictionary.save(self._words())
        except ValueError as exc:
            self._show_error(str(exc))
            return
        except OSError:
            self._show_error("Could not save your dictionary. Check folder permissions and try again.")
            return
        self.accept()
