"""Persistent user vocabulary for spelling hints and exact casing corrections."""
import json
import os
from pathlib import Path
import re
import tempfile


class PersonalDictionary:
    MAX_ENTRIES = 500
    MAX_TERM_LENGTH = 200
    # Conservative byte cap stays under Whisper's 224-token prompt limit,
    # including multilingual words, without loading a tokenizer at startup.
    MAX_PROMPT_BYTES = 200

    def __init__(self, path):
        self.path = Path(path)
        self._snapshot = ((), None, {}, "")
        self.load_error = None
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("Unsupported dictionary format.")
            if data.get("version") == 1:
                # Retain desired spellings from the old correction-pair format.
                pairs = data.get("entries")
                if not isinstance(pairs, list) or any(
                    not isinstance(pair, list) or len(pair) != 2 or not isinstance(pair[1], str)
                    for pair in pairs
                ):
                    raise ValueError("Invalid dictionary entries.")
                words, seen = [], set()
                for _, word in pairs:
                    if word.strip().casefold() not in seen:
                        words.append(word)
                        seen.add(word.strip().casefold())
            elif data.get("version") == 2:
                words = data.get("words")
            else:
                raise ValueError("Unsupported dictionary format.")
            self._snapshot = self._compile(words)
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as exc:
            self.load_error = str(exc)

    @property
    def words(self):
        return self._snapshot[0]

    @classmethod
    def _compile(cls, words):
        if not isinstance(words, (list, tuple)) or len(words) > cls.MAX_ENTRIES:
            raise ValueError(f"Use at most {cls.MAX_ENTRIES} words.")
        normalized, seen = [], set()
        for index, word in enumerate(words, 1):
            if not isinstance(word, str) or not word.strip():
                raise ValueError(f"Line {index}: enter a word or phrase.")
            if len(word) > cls.MAX_TERM_LENGTH or any(
                ord(c) < 32 or ord(c) == 127 or c in "\u0085\u2028\u2029" for c in word
            ):
                raise ValueError(f"Line {index}: use a single line of at most {cls.MAX_TERM_LENGTH} characters.")
            word = word.strip()
            if word.casefold() in seen:
                raise ValueError(f"Line {index}: this word is already listed.")
            seen.add(word.casefold())
            normalized.append(word)

        patterns, spellings = [], {}
        for index, word in enumerate(sorted(normalized, key=len, reverse=True)):
            name = f"word{index}"
            left = r"(?<![a-zA-Z0-9_])" if word[0].isascii() and (word[0].isalnum() or word[0] == "_") else ""
            right = r"(?![a-zA-Z0-9_])" if word[-1].isascii() and (word[-1].isalnum() or word[-1] == "_") else ""
            patterns.append(f"(?P<{name}>{left}{re.escape(word)}{right})")
            spellings[name] = word
        pattern = re.compile("|".join(patterns), re.IGNORECASE | re.ASCII) if patterns else None
        hints = []
        for word in normalized:
            if len(", ".join([*hints, word]).encode("utf-8")) <= cls.MAX_PROMPT_BYTES:
                hints.append(word)
        return tuple(normalized), pattern, spellings, ", ".join(hints)

    def save(self, words):
        snapshot = self._compile(words)
        data = json.dumps({"version": 2, "words": snapshot[0]}, ensure_ascii=False, indent=2)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent, delete=False) as output:
                temporary = Path(output.name)
                output.write(data + "\n")
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        self._snapshot = snapshot
        self.load_error = None

    def prompt(self):
        return self._snapshot[3]

    def apply(self, text):
        _, pattern, spellings, _ = self._snapshot
        if not text or pattern is None:
            return text
        return pattern.sub(lambda match: spellings[match.lastgroup], text)
