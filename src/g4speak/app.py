"""
G4Speak - Wispr Flow-inspired Desktop Voice-to-Text Overlay Application.
Copyright (c) 2026 G4Speak contributors
Licensed under the MIT License. See LICENSE.
- UI: Minimal floating capsule (shows target app icon + live waveform, lock mode indicator).
- Speech-to-Text: Pure Cloud AI via Groq Whisper Large-v3 (High Quality, 32-layer multilingual model).
- Text Refinement: Fast zero-latency instant typography & tech casing rules, with optional Groq Cloud / Local LLM.
- Typing: Direct Windows SendInput with Safe Clipboard Restore fallback.
- Hotkey:
  * Hold Ctrl+Space to speak, release to insert text.
  * Double-press Ctrl+Space (or click lock on UI) to LOCK recording (hands-free speaking without holding keys).
  * Press Ctrl+Space again (or click UI) to unlock, finish, and insert text.
  * Direct low-level Windows Hook suppresses Space while Ctrl is held so no spaces or hotkeys leak to target apps.
"""

import ctypes
from concurrent.futures import CancelledError
from ctypes import wintypes
import difflib
import io
import json
import logging
import math
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
import wave
import winreg
from pathlib import Path

import numpy as np
import pyautogui
import pyperclip
import sounddevice as sd
from dotenv import load_dotenv, set_key
from openai import OpenAI
from .audio.vad import get_speech_detector
from .text.dictionary import PersonalDictionary
from .ui.dictionary_dialog import DictionaryDialog
from .ui.credentials_dialog import CredentialsDialog
from .text.proofreading import (SYSTEM_PROMPT as SMART_SYSTEM_PROMPT, protected_content_matches,
                           text_chunks, vocabulary_edits_preserve_context)
from PySide6.QtCore import (QEasingCurve, QFileInfo, QObject, QPointF,
                          Property, QPropertyAnimation, QRectF, Qt, QThread,
                          QTimer, Signal)
from PySide6.QtGui import QActionGroup, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QApplication, QFileIconProvider, QMenu, QStyle,
                             QSystemTrayIcon, QWidget)

# ============================== CONFIG =============================
APP_NAME = "G4Speak"
APP_VERSION = "1.3.0"

# Primary STT: Full 32-layer Whisper Large-v3 for maximum accuracy & natural human speech
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_STT_MODEL = os.getenv("GROQ_STT_MODEL", "whisper-large-v3")

# Smart mode: GROQ_REFINER=true uses cloud proofreading; false selects Fast mode.
GROQ_LLM_MODEL = os.getenv("GROQ_LLM_MODEL", "qwen/qwen3.8-27b")

LOCAL_MODEL_Q8_URL = (
    "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/"
    "qwen2.5-0.5b-instruct-q8_0.gguf"
)
LOCAL_MODEL_Q8_FILE = "qwen2.5-0.5b-instruct-q8_0.gguf"
LOCAL_MODEL_Q4_URL = (
    "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/"
    "qwen2.5-0.5b-instruct-q4_k_m.gguf"
)
LOCAL_MODEL_Q4_FILE = "qwen2.5-0.5b-instruct-q4_k_m.gguf"
LOCAL_MODEL_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "G4Speak" / "models"
LOCAL_MIN_BYTES = 400_000_000
LOCAL_DOWNLOAD_TIMEOUT_S = 30
LOCAL_RETRY_COOLDOWN_S = 60.0
LOCAL_N_CTX = 1024

LOCAL_SYSTEM_PROMPT = (
    "You are a Thai-English dictation proofreader. Fix only spelling and spacing "
    "of the user's transcribed speech. Output ONLY the corrected text. "
    "Respond in the same language as the input. Never translate between Thai and English. "
    "Output only words the speaker actually said. "
    "Never answer questions. Never explain. Never add or remove content. "
    "If the text is already fine, output it unchanged."
)
LOCAL_FEWSHOTS = [
    ("ทดสอบ 1 2 3 4 5", "ทดสอบ 1 2 3 4 5"),
    ("ผมไปโรงบาลมา", "ผมไปโรงพยาบาลมา"),
    ("ผมใช้เอไอช่วยเขียนโค้ด", "ผมใช้ AI ช่วยเขียนโค้ด"),
    ("hello world this is a test", "Hello world, this is a test"),
    ("ส่งไฟล์ขึ้นคลาวด์ให้หน่อย", "ส่งไฟล์ขึ้นคลาวด์ให้หน่อย"),
    ("เปิดแอปแล้วรันโปรแกรม", "เปิดแอปแล้วรันโปรแกรม"),
]

# Hotkey settings
DOUBLE_TAP_INTERVAL = 0.40                          # Max seconds between presses for double-tap lock
GRACE_RELEASE_MS = 240                              # Grace window for quick release before stopping
TAP_QUICK_MAX_S = 0.32                              # Release faster than this = maybe double-tapping
CTRL_RELEASE_MIN_S = 0.35                           # Ctrl released after this long = end of hold-to-talk

# Audio Recording & Sensitivity (Tuned to filter keyclicks/noise while keeping speech)
SAMPLE_RATE = 16000
CHANNELS = 1
BLOCK_SIZE = 512                                    # 32 ms per chunk at 16 kHz
MAX_RECORD_SECONDS = 600                            # Ten minutes; 16 kHz PCM WAV stays below 25 MB
MIN_RECORD_SECONDS = 0.16                           # Keep short words such as yes/no
MIN_VOICE_PEAK = 0.0015
MIN_VOICE_RMS = 0.00035
RECORD_TAIL_MS = 96                                 # Drain microphone latency after key release
PROCESSING_BUDGET_S = 30.0                          # Base allowance for preparation, upload, and recognition
MAX_PROCESSING_BUDGET_S = 180.0
REFINEMENT_BUDGET_S = 6.0                           # Allow contextual proofreading with reasoning
MAX_REFINEMENT_BUDGET_S = 20.0
AUDIO_DEVICE = None                                 # None = default mic

# Floating capsule dimensions (super compact)
TYPE_DELAY_MS = 60                                  # ms delay before typing after restoring window focus
OVERLAY_BOTTOM_MARGIN = 18                          # px gap above taskbar
IDLE_SIZE = (36, 5)                                 # Apple minimal micro-capsule
ACTIVE_SIZE_NORMAL = (84, 32)                       # Compact capsule: App Icon + Waveform (+4px side padding)
ACTIVE_SIZE_LOCKED = (108, 32)                      # Wide capsule: Left Icon (30px) + Waveform (40px) + Right Lock (30px) (+4px side padding)
ANIM_MS = 200                                       # smooth Apple spring transition duration
BAR_COUNT = 7                                       # 7 slender waveform bars
FRAME_MS = 16                                       # ~60 FPS UI tick

# Common Whisper silence, noise, and video subtitle hallucinations to filter out
SILENCE_HALLUCINATIONS = {
    "ขอบคุณสำหรับการรับชม",
    "ขอบคุณที่รับชม",
    "ขอบคุณที่รับชมครับ",
    "ขอบคุณสำหรับการรับชมครับ",
    "ขอบคุณสำหรับการรับชมค่ะ",
    "อย่าลืมกดติดตาม",
    "อย่าลืมกดไลค์กดแชร์",
    "อย่าลืมกดกระดิ่ง",
    "โปรดติดตามตอนต่อไป",
    "โปรดติดตามชม",
    "โปรดติดตามตอนต่อไปนะ",
    "ติดตามชมตอนต่อไป",
    "ติดตามชม",
    "โอ้", "อืม", "ฮืม", "ฮึ่ม", "ฮึม", "ฮ่ำ", "ฮึ่มฮ่ำ", "อื้อ", "อือ",
    "เฮ้อ", "เอ่อ", "อ่า", "หืม", "ฮะ",
    "MBC 뉴스",
    "Subtitles by",
}

_SILENCE_LOWER = frozenset({
    "thanks for watching",
    "thank you for watching",
    "thank you very much for watching",
    "please subscribe",
    "dont forget to subscribe",
    "don't forget to subscribe",
    "please like and subscribe",
    "subscribe to my channel",
    "see you in the next video",
    "subtitles by",
})

# These can be real dictation; suppress only when acoustic confidence is weak.
_SHORT_SILENCE_PHRASES = frozenset({"thank you", "thanks", "ขอบคุณ", "ขอบคุณครับ", "ขอบคุณค่ะ"})

_HUM_RE = re.compile(
    r"^[\u0e2e\u0e2d\u0e2b][\u0e37\u0e36\u0e34\u0e38\u0e39\u0e30\u0e32\u0e48\u0e49\u0e4a\u0e4b\u0e21\u0e23\s\.\,\-]+$"
)


def is_silence_hallucination(text: str, strict: bool = True) -> bool:
    """True for non-speech Whisper outputs (closers, fillers, hums)."""
    clean = (text or "").strip(". \t\n!?\"'«»")
    if not clean:
        return True
    if _HUM_RE.fullmatch(clean):
        return True
    if not strict:
        return False
    if clean in SILENCE_HALLUCINATIONS:
        return True
    if clean.casefold() in _SILENCE_LOWER | _SHORT_SILENCE_PHRASES:
        return True
    return False


FUZZY_CLOSER_THRESHOLD = 0.70

_ALWAYS_DROP = frozenset({
    "subtitles by the amara.org community",
    "subtitles by amara.org community",
    "transcribed by amara.org community",
})


def is_provider_credit(text: str) -> bool:
    """True for transcription-provider credits (Amara et al)."""
    clean = (text or "").strip(". \t\n!?\"'«»").casefold()
    return clean in _ALWAYS_DROP


def is_fuzzy_closer(text: str, threshold: float = FUZZY_CLOSER_THRESHOLD) -> bool:
    """True when text resembles a known YouTube-closer."""
    clean = (text or "").strip(". \t\n!?\"'«»").casefold()
    if not clean:
        return False
    return max(
        difflib.SequenceMatcher(None, clean, c).ratio() for c in _SILENCE_LOWER
    ) >= threshold


def has_repetitive_loops(text: str) -> bool:
    """Detects repetitive word loop hallucinations (e.g. 'God of God of God')."""
    words = text.split()
    if len(words) >= 4:
        # Check 1-word loop
        for i in range(len(words) - 3):
            if words[i].casefold() == words[i+1].casefold() == words[i+2].casefold() == words[i+3].casefold():
                return True
        # Check 2-word phrase loop
        if len(words) >= 6:
            for i in range(len(words) - 5):
                p1 = (words[i].casefold(), words[i+1].casefold())
                p2 = (words[i+2].casefold(), words[i+3].casefold())
                p3 = (words[i+4].casefold(), words[i+5].casefold())
                if p1 == p2 == p3:
                    return True
    return False


# App States
IDLE, RECORDING, STOPPING, PROCESSING = "idle", "recording", "stopping", "processing"

# ========================= WINDOWS API HELPERS =======================
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateMutexW.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL

KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
ULONG_PTR = ctypes.c_ulonglong

WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
LLKHF_INJECTED = 0x00000010

VK_CONTROL = 0x11
VK_LCONTROL = 0xA2
VK_RCONTROL = 0xA3
VK_SPACE = 0x20
VK_ESCAPE = 0x1B

HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_ulonglong),
    ]


user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.CallNextHookEx.restype = ctypes.c_longlong
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
user32.UnhookWindowsHookEx.restype = wintypes.BOOL


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class DUMMYUNION(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT),
    ]


class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", wintypes.DWORD),
        ("u", DUMMYUNION),
    ]


def get_foreground_window() -> int:
    return int(user32.GetForegroundWindow())


def _get_exe_from_pid(pid: int) -> str | None:
    if not pid:
        return None
    hproc = kernel32.OpenProcess(0x1000, False, pid)
    if not hproc:
        return None
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(hproc, 0, buf, ctypes.byref(size)):
            return buf.value
    finally:
        kernel32.CloseHandle(hproc)
    return None


def get_target_app_exe(hwnd: int) -> str | None:
    """Retrieves the executable path of the window currently in focus."""
    if not hwnd or not user32.IsWindow(hwnd):
        return None
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    path = _get_exe_from_pid(pid.value)

    if path and "applicationframehost.exe" in path.lower():
        child_pids = []

        def _enum_child(child_hwnd, _):
            cls_buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(child_hwnd, cls_buf, 256)
            if cls_buf.value == "Windows.UI.Core.CoreWindow":
                cpid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(child_hwnd, ctypes.byref(cpid))
                if cpid.value and cpid.value != pid.value:
                    child_pids.append(cpid.value)
                    return False
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        user32.EnumChildWindows(hwnd, WNDENUMPROC(_enum_child), 0)
        if child_pids:
            uwp_path = _get_exe_from_pid(child_pids[0])
            if uwp_path:
                return uwp_path

    return path


def is_text_target_available(hwnd: int) -> bool:
    """Checks if there is a valid window ready to receive text input."""
    if not hwnd or not user32.IsWindow(hwnd):
        return False
    if user32.IsIconic(hwnd):
        return False
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    cls = buf.value
    if cls in ("Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"):
        return False

    exe = get_target_app_exe(hwnd)
    if exe and "lockapp.exe" in exe.lower():
        return False

    return True


def switch_to_window(hwnd: int) -> bool:
    """Brings the previously focused window back to the front."""
    if not hwnd or not user32.IsWindow(hwnd):
        return False
    try:
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        cur_tid = kernel32.GetCurrentThreadId()
        fg_hwnd = user32.GetForegroundWindow()
        fg_tid = user32.GetWindowThreadProcessId(fg_hwnd, None)
        if fg_tid != cur_tid:
            user32.AttachThreadInput(cur_tid, fg_tid, True)
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
            user32.SetFocus(hwnd)
            user32.AttachThreadInput(cur_tid, fg_tid, False)
        else:
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
        return int(user32.GetForegroundWindow()) == int(hwnd)
    except Exception as exc:
        logging.warning("switch_to_window failed: %s", exc)
        return False


def insert_text_safely(text: str, target_hwnd: int):
    """
    Inserts text directly into the focused text box without destroying the user's clipboard.
    1. First tries direct Unicode SendInput (proper 40-byte 64-bit struct).
    2. If target app or policy drops SendInput, falls back to Safe Clipboard Restore:
       saves user's original clipboard -> pastes -> immediately restores original clipboard.
    """
    if not text:
        return
    if switch_to_window(target_hwnd):
        time.sleep(0.04)
    else:
        logging.warning("Focus switch unverified — typing anyway, check the target window.")
        time.sleep(0.04)

    # 1. Try SendInput Unicode directly
    if not any(ord(c) > 0xFFFF for c in text):
        try:
            inputs = []
            for char in text:
                inp_down = INPUT()
                inp_down.type = 1  # INPUT_KEYBOARD
                inp_down.u.ki.wVk = 0
                inp_down.u.ki.wScan = ord(char)
                inp_down.u.ki.dwFlags = KEYEVENTF_UNICODE

                inp_up = INPUT()
                inp_up.type = 1  # INPUT_KEYBOARD
                inp_up.u.ki.wVk = 0
                inp_up.u.ki.wScan = ord(char)
                inp_up.u.ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP

                inputs.append(inp_down)
                inputs.append(inp_up)

            n = len(inputs)
            arr = (INPUT * n)(*inputs)
            ret = user32.SendInput(n, ctypes.byref(arr[0]), ctypes.sizeof(INPUT))
            if ret == n:
                logging.info("Directly typed %d characters via SendInput (clipboard untouched).", len(text))
                return
            logging.warning("SendInput partial (%d/%d events) — falling back to clipboard.", ret, n)
        except Exception as exc:
            logging.warning("SendInput error: %s", exc)

    # 2. Fallback to Safe Clipboard Restore
    logging.info("Using Safe Clipboard Restore fallback...")
    saved_clip = None
    try:
        saved_clip = pyperclip.paste()
    except Exception:
        pass

    def _clip_seq() -> int:
        user32.GetClipboardSequenceNumber.restype = wintypes.DWORD
        return int(user32.GetClipboardSequenceNumber())

    seq_mine: int | None = None
    try:
        pyperclip.copy(text)
        time.sleep(0.02)
        seq_mine = _clip_seq()
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.06)
    finally:
        if saved_clip is not None and seq_mine is not None and _clip_seq() == seq_mine:
            try:
                pyperclip.copy(saved_clip)
                logging.info("User's original clipboard restored successfully.")
            except Exception:
                pass
        elif saved_clip is not None:
            logging.warning("Clipboard changed during paste — keeping user's new content.")


# ========================== KEY LOADERS ============================
def _app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


APP_DIR = _app_dir()


def _find_env_file() -> Path:
    candidates = [
        APP_DIR / ".env",
        APP_DIR / "dist" / ".env",
        APP_DIR.parent / ".env",
        Path.cwd() / ".env",
        Path.cwd() / "dist" / ".env",
    ]
    for c in candidates:
        if c.exists() and c.stat().st_size > 0:
            return c
    return APP_DIR / ".env"


ENV_FILE = _find_env_file()


def _asset_path(name: str) -> Path:
    """Resolves a bundled asset both from source and from a PyInstaller build."""
    bundled = Path(getattr(sys, "_MEIPASS", "")) / "assets" / name
    if bundled.exists():
        return bundled
    return APP_DIR / "assets" / name


APP_ICON = _asset_path("logo.png")
ENV_TEMPLATE = (
    "# G4Speak Configuration\n"
    "# Groq Cloud (Free API Key): https://console.groq.com/keys\n"
    "GROQ_API_KEY=\n"
    "# STT Model: 'whisper-large-v3' (recommended for best Thai speech quality)\n"
    "GROQ_STT_MODEL=whisper-large-v3\n"
    "# auto preserves Thai/English switching; th/en can be used for single-language dictation\n"
    "GROQ_STT_LANGUAGE=auto\n"
    "# Smart mode proofreads with Groq; false selects Fast mode\n"
    "GROQ_REFINER=true\n"
)


def ensure_env_file():
    if not ENV_FILE.exists():
        ENV_FILE.write_text(ENV_TEMPLATE, encoding="utf-8")


def load_env_file():
    for candidate in [
        APP_DIR / "dist" / ".env",
        APP_DIR.parent / ".env",
        APP_DIR / ".env",
        ENV_FILE,
    ]:
        if candidate.exists():
            load_dotenv(candidate, override=True)


def get_key(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name, "").strip().strip("\"'")
        if value:
            return value
    return None


def load_groq_key() -> str | None:
    return get_key("GROQ_API_KEY")


# ========================== AUTOSTART ==============================
AUTOSTART_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def is_autostart_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_KEY) as key:
            winreg.QueryValueEx(key, APP_NAME)
            return True
    except OSError:
        return False


def set_autostart(enabled: bool):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, f'"{sys.executable}"')
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass


def audio_to_wav_file(audio: np.ndarray, sample_rate: int = 16000) -> tuple:
    """Converts a numpy float32 audio array into an in-memory 16-bit WAV file tuple for OpenAI client."""
    int_data = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(int_data.tobytes())
    buf.seek(0)
    return ("speech.wav", buf.read(), "audio/wav")


def format_spacing(text: str) -> str:
    """
    Cleans up Thai-English typography spacing.
    - Ensures clean single space between Thai words and English/numbers.
    - Cleans up multi-space artifacts.
    """
    if not text:
        return ""
    text = re.sub(r"([\u0e01-\u0e5b])([A-Za-z0-9])", r"\1 \2", text)
    text = re.sub(r"([A-Za-z0-9])([\u0e01-\u0e5b])", r"\1 \2", text)
    text = strip_thai_punct(text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def strip_thai_punct(text: str) -> str:
    """Removes '.' and ',' touching Thai script (Thai writing uses neither)."""
    def _is_th(c: str) -> bool:
        return "\u0e00" <= c <= "\u0e7f"

    def _is_al(c: str) -> bool:
        return c.isascii() and c.isalnum()

    def _repl(m: re.Match) -> str:
        s = m.string
        i = m.start() - 1
        while i >= 0 and s[i] in " \t":
            i -= 1
        left = s[i] if i >= 0 else ""
        j = m.end()
        while j < len(s) and s[j] in " \t":
            j += 1
        right = s[j] if j < len(s) else ""
        if left and right and _is_al(left) and _is_al(right):
            return m.group(0)
        if (left and _is_th(left)) or (right and _is_th(right)):
            return ""
        return m.group(0)

    return re.sub(r"[.,]+", _repl, text)


TECH_CASING_MAP = {
    "ai": "AI",
    "api": "API",
    "html": "HTML",
    "css": "CSS",
    "js": "JS",
    "ui": "UI",
    "ux": "UX",
    "id": "ID",
    "url": "URL",
    "http": "HTTP",
    "https": "HTTPS",
    "sql": "SQL",
    "git": "Git",
    "github": "GitHub",
    "python": "Python",
    "windows": "Windows",
    "groq": "Groq",
    "gemini": "Gemini",
    "claude": "Claude",
    "g4speak": "G4Speak",
    "mp4": "MP4",
    "wav": "WAV",
    "whisper": "Whisper",
    "drop shadow": "Drop Shadow",
    "motion graphics": "Motion Graphics",
    "motion graphic": "Motion Graphic",
    "vs code": "VS Code",
    "vscode": "VS Code",
}

_TECH_PATTERNS = [
    (re.compile(rf"(?<![\w\u0e00-\u0e7f]){re.escape(k)}(?![\w\u0e00-\u0e7f])", re.IGNORECASE), v)
    for k, v in TECH_CASING_MAP.items()
]


def format_tech_casing(text: str) -> str:
    """Instantly fixes casing for technical terms and brands without calling any LLM."""
    if not text:
        return ""
    for pattern, replacement in _TECH_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


_POLITE_TAIL = re.compile(r"\s*(ครับ|ค่ะ|คะ|นะคะ|นะครับ)\s*$")


def prepare_speech_audio(audio: np.ndarray) -> np.ndarray:
    """Require neural speech detection before amplifying or uploading audio."""
    audio = np.nan_to_num(np.asarray(audio, dtype=np.float32).reshape(-1)).copy()
    if len(audio) < MIN_RECORD_SECONDS * SAMPLE_RATE:
        return np.zeros(0, dtype=np.float32)
    audio -= np.median(audio)  # Remove microphone DC offset before energy checks
    frame_size = 320  # 20 ms, independent of the device callback block size
    padded = np.pad(audio, (0, (-len(audio)) % frame_size))
    levels = np.sqrt(np.mean(padded.reshape(-1, frame_size) ** 2, axis=1))
    active = np.flatnonzero(levels >= MIN_VOICE_RMS)
    if len(active) < 3 or float(np.max(np.abs(audio))) < MIN_VOICE_PEAK:
        return np.zeros(0, dtype=np.float32)
    # Detect speech at the original level. Amplifying mic hiss before detection
    # caused silent recordings to turn into plausible Whisper transcripts.
    detector = get_speech_detector(_asset_path('silero_vad_v6.onnx'))
    bounds = detector.speech_bounds(audio)
    if bounds is None:
        logging.info("No speech detected by Silero VAD; skipping cloud transcription.")
        return np.zeros(0, dtype=np.float32)
    audio = audio[bounds[0]:bounds[1]]
    peak = float(np.max(np.abs(audio)))
    active_rms = float(np.sqrt(np.mean(levels[active] ** 2)))
    gain = max(1.0, min(2.0, 0.025 / max(active_rms, 1e-9), 0.95 / max(peak, 1e-9)))
    logging.info("Speech accepted: %.2fs, peak=%.4f, active_rms=%.5f, gain=%.2f", len(audio) / SAMPLE_RATE, peak, active_rms, gain)
    return np.clip(audio * gain, -1.0, 1.0)


def processing_budget(audio_seconds):
    """Longer recordings need more upload and recognition time."""
    return min(MAX_PROCESSING_BUDGET_S, PROCESSING_BUDGET_S + max(0.0, audio_seconds) * 0.25)


def smart_mode_enabled():
    return os.getenv("GROQ_REFINER", "false").lower() in ("true", "1")


def refinement_budget(text):
    return min(MAX_REFINEMENT_BUDGET_S, REFINEMENT_BUDGET_S + len(text) / 800.0)


def user_error_message(details):
    text = details.casefold()
    if any(word in text for word in ('api_key', 'api key', 'unauthorized', 'authentication', '401')):
        return "Please check your Groq API key in API Credentials."
    if any(word in text for word in ('429', 'rate limit', 'quota')):
        return "The transcription service is temporarily at capacity. Please try again shortly."
    if any(word in text for word in ('timeout', 'timed out')):
        return "Transcription took longer than expected. Please try again."
    if any(word in text for word in ('microphone', 'portaudio', 'input device')):
        return "Your microphone is unavailable. Check its connection and Windows microphone permissions."
    if any(word in text for word in ('vad', 'speech detector', 'onnx')):
        return "Speech detection is unavailable. Please restart G4Speak."
    if any(word in text for word in ('save', 'permission', 'startup', 'sign-in')):
        return "Your settings could not be saved. Please check folder permissions and try again."
    if any(word in text for word in ('connection', 'network', 'connect')):
        return "The transcription service could not be reached. Please check your internet connection."
    return "Transcription could not be completed. Please try again."


def call_before_deadline(callback, deadline, cancelled=None):
    """Bound caller latency even when a network operation stalls between reads.

    Late results stay inside this call and can never be typed in another session.
    Network requests also have transport timeouts and retries disabled.
    """
    remaining = deadline - time.monotonic()
    if cancelled is not None and cancelled.is_set():
        raise CancelledError()
    if remaining <= 0:
        raise TimeoutError("Speech recognition timed out waiting for a result. Please try again; you do not need to record longer.")
    complete = threading.Event()
    result = []
    errors = []

    def invoke():
        try:
            result.append(callback())
        except Exception as exc:
            errors.append(exc)
        finally:
            complete.set()

    threading.Thread(target=invoke, daemon=True, name="dictation-request").start()
    while not complete.is_set():
        if cancelled is not None and cancelled.is_set():
            raise CancelledError()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Speech recognition timed out waiting for a result. Please try again; you do not need to record longer.")
        complete.wait(min(remaining, 0.05))
    if cancelled is not None and cancelled.is_set():
        raise CancelledError()
    if time.monotonic() > deadline:
        raise TimeoutError("Speech recognition timed out waiting for a result. Please try again; you do not need to record longer.")
    if errors:
        raise errors[0]
    return result[0]


# ===================== CLOUD SPEECH-TO-TEXT ENGINE ====================
class SpeechToTextEngine:
    """High Quality Cloud Speech-to-Text via Groq Whisper Large-v3."""

    def __init__(self):
        self._groq_client = None
        self._model = GROQ_STT_MODEL
        self.reload_keys()

    def reload_keys(self):
        groq_key = load_groq_key()
        self._model = os.getenv("GROQ_STT_MODEL", "whisper-large-v3")
        self._language = os.getenv("GROQ_STT_LANGUAGE", "auto").strip().lower()
        if self._language not in ("auto", "th", "en"):
            logging.warning("Unknown STT language; using automatic detection.")
            self._language = "auto"
        if groq_key:
            self._groq_client = OpenAI(
                base_url=GROQ_BASE_URL,
                api_key=groq_key,
                timeout=PROCESSING_BUDGET_S,
                max_retries=0,
            )
            logging.info("Groq Cloud Whisper (%s) ready (High Quality Mode).", self._model)
        else:
            self._groq_client = None
            logging.warning(
                "GROQ_API_KEY not found in .env (get a free key at https://console.groq.com/keys)."
            )

    @property
    def is_ready(self) -> bool:
        return self._groq_client is not None

    def transcribe(self, audio: np.ndarray, *, timeout=None, vocabulary="") -> tuple[str, float, float]:
        if self._groq_client is None:
            raise RuntimeError("GROQ_API_KEY not found. Right-click tray icon and choose Edit API Keys")

        file_tuple = audio_to_wav_file(audio)
        model_to_use = self._model
        options = {"language": self._language} if self._language != "auto" else {}
        options["timeout"] = timeout if timeout is not None else processing_budget(len(audio) / SAMPLE_RATE)
        if vocabulary:
            options["prompt"] = vocabulary

        try:
            t0 = time.perf_counter()
            # Only user-supplied vocabulary goes into the spelling hint, never generic instructions.
            res = self._groq_client.audio.transcriptions.create(
                model=model_to_use,
                file=file_tuple,
                temperature=0.0,
                response_format="verbose_json",
                **options,
            )
        except Exception as exc:
            logging.error("Groq Cloud STT call error: %s", exc)
            raise RuntimeError(f"Groq Cloud STT error: {exc}")

        text = (res.text or "").strip()
        dt = time.perf_counter() - t0
        dur = len(audio) / float(SAMPLE_RATE)

        # Non-speech acoustic rejection (humming, throat clearing, mic hiss)
        segments = getattr(res, "segments", []) or []
        if not segments:
            logging.warning("STT response has no segment confidence metadata; not typing unverified text.")
            return "", 1.0, -99.0
        avg_no_speech = 0.0
        avg_logprob = 0.0
        if segments:
            def value(segment, key, default=0.0):
                return segment.get(key, default) if isinstance(segment, dict) else getattr(segment, key, default)

            # Filter individual silence segments; a noisy tail must not erase real speech.
            kept = [s for s in segments if not (
                value(s, "no_speech_prob", 1.0) is None
                or value(s, "avg_logprob", -99.0) is None
                or value(s, "no_speech_prob", 1.0) >= 0.6
                or value(s, "avg_logprob", -99.0) < -1.0
                or value(s, "compression_ratio") > 2.4
            )]
            if not kept:
                logging.info(
                    "Ignored transcript containing only low-confidence silence segments: '%s'",
                    text,
                )
                return "", 1.0, -99.0
            if len(kept) != len(segments) and all(value(s, "text", "").strip() for s in kept):
                text = " ".join(value(s, "text", "").strip() for s in kept)
            weights = [max(0.02, value(s, "end") - value(s, "start")) for s in kept]
            avg_no_speech = sum(value(s, "no_speech_prob") * w for s, w in zip(kept, weights)) / sum(weights)
            avg_logprob = sum(value(s, "avg_logprob") * w for s, w in zip(kept, weights)) / sum(weights)

        clean = text.strip(". \t\n!?\"'«»")
        if not clean:
            return "", 1.0, -99.0

        if has_repetitive_loops(text):
            logging.info("Ignored repetitive loop hallucination: '%s'", text)
            return "", 1.0, -99.0

        logging.info("Groq Whisper %s STT (%.2fs, %.1fs audio, no_speech=%.2f, logprob=%.2f): %s",
                     model_to_use, dt, dur, avg_no_speech, avg_logprob, text)
        return text, avg_no_speech, avg_logprob


# ============================ TEXT REFINER ============================
class TextRefiner:
    """
    High-quality Thai-English text refinement.
    - Fast Mode: Instant typography & tech casing rules.
    - Smart Mode: Contextual cloud proofreading via Groq (GROQ_REFINER=true).
    - Local Mode: Optional offline llama.cpp model (LOCAL_REFINER=true).
    """

    def __init__(self, groq_client_getter=None, dictionary=None, on_unavailable=None):
        self._llm = None
        self._retry_after = 0.0
        self._guard = threading.Lock()
        self._groq_getter = groq_client_getter
        self._dictionary = dictionary
        self._on_unavailable = on_unavailable
        self._cloud_retry_after = 0.0

    def reload_keys(self):
        logging.info("Text refiner ready (%s).", self.status())

    def status(self) -> str:
        if smart_mode_enabled():
            return "Enhanced transcription"
        if os.getenv("LOCAL_REFINER", "false").lower() in ("true", "1"):
            return "Local model loaded" if self._llm else "Local model pending"
        return "Standard transcription"

    def _cloud_refine(self, text, client, deadline, cancelled=None):
        if time.monotonic() < self._cloud_retry_after:
            return text
        words = self._dictionary.words if self._dictionary is not None else ()
        results = []
        chunks = text_chunks(text)
        for index, chunk in enumerate(chunks):
            if cancelled is not None and cancelled.is_set():
                raise CancelledError()
            raw = chunk.strip()
            if not raw or deadline - time.monotonic() <= 0.15:
                results.append(chunk)
                continue
            # Prioritize words mentioned here, then other user vocabulary that fits.
            ordered = sorted(words, key=lambda word: word.casefold() not in raw.casefold())
            vocabulary, size = [], 0
            for word in ordered:
                word_size = len(word.encode('utf-8')) + 4
                if size + word_size <= 4000:
                    vocabulary.append(word)
                    size += word_size
            model = os.getenv('GROQ_LLM_MODEL', GROQ_LLM_MODEL)
            options = {'reasoning_effort': 'low'} if model.startswith('qwen/qwen3.8') else {}
            try:
                response = client.with_options(timeout=max(0.05, deadline - time.monotonic()), max_retries=0).chat.completions.create(
                    model=model,
                    messages=[
                        {'role': 'system', 'content': SMART_SYSTEM_PROMPT},
                        {'role': 'user', 'content': json.dumps({'transcript': raw, 'vocabulary': vocabulary}, ensure_ascii=False)},
                    ],
                    temperature=0.0,
                    # Some Groq accounts allow only 1,000 output tokens/minute.
                    # Oversized reservations are rejected even for short transcripts.
                    max_tokens=min(1000, max(256, len(raw) * 3 + 256)),
                    **options,
                )
                choice = response.choices[0]
                if cancelled is not None and cancelled.is_set():
                    raise CancelledError()
                output = (choice.message.content or '').strip()
                output = format_tech_casing(format_spacing(output))
                if choice.finish_reason == 'stop' and self._is_valid_correction(raw, output, vocabulary=words):
                    output = self._strip_unspoken_polite(raw, output)
                    leading = chunk[:len(chunk) - len(chunk.lstrip())]
                    trailing = chunk[len(chunk.rstrip()):]
                    results.append(leading + output + trailing)
                else:
                    logging.info('Smart proofreading rejected an incomplete or unsafe correction.')
                    results.append(chunk)
            except CancelledError:
                raise
            except Exception as exc:
                logging.info('Smart proofreading unavailable; keeping transcript: %s', exc)
                if getattr(exc, 'status_code', None) == 429:
                    self._cloud_retry_after = time.monotonic() + 60
                if self._on_unavailable is not None and not (cancelled is not None and cancelled.is_set()):
                    self._on_unavailable()
                results.extend(chunks[index:])
                break
        return ''.join(results)

    def _have_usable_model(self) -> Path | None:
        for name in (LOCAL_MODEL_Q8_FILE, LOCAL_MODEL_Q4_FILE):
            p = LOCAL_MODEL_DIR / name
            try:
                if p.exists() and p.stat().st_size >= LOCAL_MIN_BYTES:
                    return p
            except OSError:
                pass
        return None

    def _ensure_loaded(self) -> bool:
        if self._llm is not None:
            return True
        if time.monotonic() < self._retry_after:
            return False
        try:
            from llama_cpp import Llama
        except ImportError:
            self._retry_after = time.monotonic() + LOCAL_RETRY_COOLDOWN_S
            return False
        model_path = self._have_usable_model()
        if model_path is None:
            self._retry_after = time.monotonic() + LOCAL_RETRY_COOLDOWN_S
            return False
        try:
            n_threads = max(2, (os.cpu_count() or 4) - 1)
            self._llm = Llama(
                model_path=str(model_path),
                n_ctx=LOCAL_N_CTX,
                n_threads=n_threads,
                n_batch=256,
                verbose=False,
            )
            logging.info("Local refiner loaded (%s, threads=%d).", model_path.name, n_threads)
            return True
        except Exception as exc:
            logging.warning("Local refiner load failed: %s", exc)
            self._retry_after = time.monotonic() + LOCAL_RETRY_COOLDOWN_S
            return False

    def refine(self, raw: str, deadline: float | None = None, cancelled=None) -> str:
        if cancelled is not None and cancelled.is_set():
            raise CancelledError()
        if not raw:
            return ""

        # 1. Instant typography & tech term casing cleanup (preserves actual spoken words)
        text = format_spacing(raw)
        text = format_tech_casing(text)

        # 2. Optional: Cloud LLM refinement via Groq (only if enabled via GROQ_REFINER=true)
        if smart_mode_enabled() and self._groq_getter:
            client = self._groq_getter()
            if client is not None:
                limit = deadline if deadline is not None else time.monotonic() + refinement_budget(text)
                return self._cloud_refine(text, client, limit, cancelled)

        # 3. Optional: Local llama.cpp refinement (only if enabled via LOCAL_REFINER=true)
        # Local model loading/inference cannot be interrupted within a short deadline.
        if deadline is None and os.getenv("LOCAL_REFINER", "false").lower() in ("true", "1") and self._ensure_loaded():
            try:
                t0 = time.perf_counter()
                max_tok = max(48, min(160, int(len(raw) * 0.8)))
                messages = [{"role": "system", "content": LOCAL_SYSTEM_PROMPT}]
                for user_msg, asst_msg in LOCAL_FEWSHOTS:
                    messages.append({"role": "user", "content": user_msg})
                    messages.append({"role": "assistant", "content": asst_msg})
                messages.append({"role": "user", "content": raw})
                with self._guard:
                    res = self._llm.create_chat_completion(
                        messages=messages,
                        temperature=0.0,
                        max_tokens=max_tok,
                        repeat_penalty=1.0,
                        stop=["\n"],
                    )
                local_text = (res["choices"][0]["message"]["content"] or "").strip().strip("\"'«»`")
                local_text = format_spacing(local_text)
                local_text = format_tech_casing(local_text)
                dt = time.perf_counter() - t0
                if self._is_valid_correction(raw, local_text):
                    logging.info("Local refiner refined (%.2fs): '%s' -> '%s'", dt, raw, local_text)
                    return self._strip_unspoken_polite(raw, local_text)
            except Exception as exc:
                logging.warning("Local refine failed: %s", exc)

        return text

    @staticmethod
    def _strip_unspoken_polite(raw: str, text: str) -> str:
        """Removes trailing polite particles the refiner added but the speaker never said."""
        if text and not _POLITE_TAIL.search(raw):
            stripped = _POLITE_TAIL.sub("", text).strip()
            if stripped and stripped != text:
                logging.info("Stripped unspoken polite particle: '%s' -> '%s'", text, stripped)
                return format_spacing(stripped)
        return text

    @staticmethod
    def _is_valid_correction(raw: str, out: str, vocabulary=()) -> bool:
        """Reject answers/explanations/translations: a correction must resemble the input."""
        if not out:
            return False
        if "\n" in out:
            return False
        if any(marker in out.casefold() for marker in ('<think', '```', 'transcript:', 'corrected text:')):
            return False
        if not protected_content_matches(raw, out):
            return False
        ratio = len(out) / max(1, len(raw))
        if not 0.5 <= ratio <= 1.6:
            return False
        def _thai_dom(s: str) -> bool | None:
            th = sum(1 for c in s if "\u0e00" <= c <= "\u0e7f")
            lat = sum(1 for c in s if c.isascii() and c.isalpha())
            if th + lat < 4:
                return None
            return th / (th + lat) > 0.6
        # Explicit vocabulary can replace a phonetic Thai spelling with a Latin name.
        # It must still retain surrounding context and all protected content.
        vocabulary_fix = vocabulary_edits_preserve_context(raw, out, vocabulary)
        raw_dom, out_dom = _thai_dom(raw), _thai_dom(out)
        if raw_dom is not None and out_dom is not None and raw_dom != out_dom:
            if not vocabulary_fix:
                return False
        if difflib.SequenceMatcher(None, raw, out).ratio() < 0.6:
            if not vocabulary_fix:
                return False
        return True


# ========================== AUDIO RECORDER =========================
def rms_to_level(rms: float) -> float:
    """Ultra-responsive audio sensitivity curve to make quiet whispers visibly animate."""
    db = 20.0 * math.log10(max(rms, 1e-6))
    norm = min(1.0, max(0.0, (db + 64.0) / 44.0))
    return math.pow(norm, 0.5)


class RecorderThread(QThread):
    """Keep the device warm; discard all samples outside explicit recording sessions."""
    level = Signal(float)
    recorded = Signal(object, int)
    failed = Signal(str, int)

    def __init__(self):
        super().__init__()
        self._shutdown = threading.Event()
        self._lock = threading.Lock()
        self._session = None
        self._chunks = []
        self._total = 0

    def begin(self, session):
        with self._lock:
            self._chunks = []
            self._total = 0
            self._session = session

    def stop(self, discard=False, expected_session=None):
        with self._lock:
            if expected_session is not None and self._session != expected_session:
                return
            session, chunks = self._session, self._chunks
            self._session = None
            self._chunks = []
            self._total = 0
        if session is not None and not discard:
            audio = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)
            self.recorded.emit(audio, session)

    def shutdown(self):
        self.stop(discard=True)
        self._shutdown.set()

    def _capture(self, data, frames, timing, status):
        with self._lock:
            if self._session is None:
                return
            mono = data[:, 0].copy()
            remaining = int(MAX_RECORD_SECONDS * SAMPLE_RATE) - self._total
            mono = mono[:remaining]
            self._chunks.append(mono)
            self._total += len(mono)
            self.level.emit(rms_to_level(float(np.sqrt(np.mean(mono * mono)))))
            complete = self._total >= MAX_RECORD_SECONDS * SAMPLE_RATE
            session = self._session
        if complete:
            self.stop(expected_session=session)

    def run(self):
        while not self._shutdown.is_set():
            try:
                stream = None
                for latency in ("low", None):
                    try:
                        stream = sd.InputStream(
                            samplerate=SAMPLE_RATE, channels=CHANNELS, dtype="float32",
                            blocksize=BLOCK_SIZE, device=AUDIO_DEVICE, latency=latency,
                            callback=self._capture,
                        )
                        stream.start()
                        break
                    except Exception:
                        if stream is not None:
                            stream.close()
                            stream = None
                        if latency is None:
                            raise
                logging.info("Microphone ready (input latency %.3fs).", stream.latency)
                try:
                    while not self._shutdown.wait(0.25):
                        if not stream.active:
                            raise RuntimeError("Microphone disconnected")
                finally:
                    stream.close()
            except Exception as exc:
                logging.warning("Microphone unavailable; reconnecting: %s", exc)
                with self._lock:
                    session = self._session
                self.stop(discard=True, expected_session=session)
                if session is not None:
                    self.failed.emit(f"Microphone error: {exc}", session)
                self._shutdown.wait(1.0)


class ProcessingThread(QThread):
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, audio: np.ndarray, stt: SpeechToTextEngine, refiner: TextRefiner, target_hwnd: int = 0, dictionary=None):
        super().__init__()
        self._audio = audio
        self._stt = stt
        self._refiner = refiner
        self._target_hwnd = target_hwnd
        self._dictionary = dictionary
        self._cancelled = threading.Event()

    def cancel(self):
        self._cancelled.set()

    def run(self):
        deadline = time.monotonic() + processing_budget(len(self._audio) / SAMPLE_RATE)
        try:
            if not self._stt.is_ready:
                self.failed.emit("GROQ_API_KEY not found. Open Edit API Keys from the tray menu.")
                return

            if self._target_hwnd and not is_text_target_available(self._target_hwnd):
                logging.info("Target window no longer available before STT. Dropping silently.")
                self.done.emit("")
                return

            def recognize():
                audio = prepare_speech_audio(self._audio)
                if self._cancelled.is_set():
                    raise CancelledError()
                if not len(audio):
                    return "", 1.0, -99.0
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Speech recognition timed out. Please try again.")
                vocabulary = self._dictionary.prompt() if self._dictionary is not None else ""
                return self._stt.transcribe(audio, timeout=remaining, vocabulary=vocabulary)

            raw, no_speech, logprob = call_before_deadline(recognize, deadline, self._cancelled)
            if not raw or not raw.strip():
                logging.info("STT returned empty text. Skipping refiner & finishing silently.")
                self.done.emit("")
                return

            # Either weak acoustic signal makes common hallucination phrases suspect.
            acoustic_doubt = no_speech > 0.2 or logprob < -0.6

            def _is_hallucination(text: str) -> bool:
                if is_provider_credit(text):
                    return True
                if is_silence_hallucination(text, strict=False):
                    return True
                if not acoustic_doubt:
                    return False
                if is_silence_hallucination(text, strict=True):
                    return True
                return is_fuzzy_closer(text)

            if _is_hallucination(raw):
                logging.info("Ignored silence/noise hallucination: '%s'. Skipping.", raw)
                self.done.emit("")
                return

            if self._target_hwnd and not is_text_target_available(self._target_hwnd):
                logging.info("Target window lost before refine call. Dropping silently.")
                self.done.emit("")
                return

            # Always retain a usable transcript if optional proofreading runs out of time.
            final_text = format_tech_casing(format_spacing(raw))
            if deadline - time.monotonic() > 0.05:
                try:
                    refine_deadline = min(deadline, time.monotonic() + refinement_budget(raw))
                    final_text = call_before_deadline(lambda: self._refiner.refine(raw, deadline=refine_deadline, cancelled=self._cancelled), refine_deadline, self._cancelled)
                except CancelledError:
                    raise
                except Exception as exc:
                    logging.info("Using original transcript; optional refinement skipped: %s", exc)
            if _is_hallucination(final_text):
                self.done.emit("")
                return
            if self._dictionary is not None:
                final_text = format_spacing(self._dictionary.apply(final_text))
            if not self._cancelled.is_set():
                self.done.emit(final_text)
        except CancelledError:
            logging.info("Speech processing cancelled; late results discarded.")
        except Exception as exc:
            logging.warning("Processing failed: %s", exc)
            self.failed.emit(str(exc))


# ==================== MINIMAL FLOATING CAPSULE OVERLAY ====================
class Overlay(QWidget):
    lock_clicked = Signal()
    finish_clicked = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self._mode = IDLE
        self._is_locked = False
        self._progress = 0.0
        self._lock_factor = 0.0
        self._level = 0.0
        self._bars = [0.0] * BAR_COUNT

        self._app_icon = None
        self._icon_cache = {}
        self._icon_provider = QFileIconProvider()
        self._logo_pm = None

        center = (BAR_COUNT - 1) / 2.0
        self._weights = [1.0 - 0.48 * (abs(i - center) / center) ** 1.2 for i in range(BAR_COUNT)]

        self._apply_geometry()

        self._anim = QPropertyAnimation(self, b"progress", self)
        self._anim.setDuration(ANIM_MS)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._lock_anim = QPropertyAnimation(self, b"lockFactor", self)
        self._lock_anim.setDuration(300)
        self._lock_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(FRAME_MS)

        # Windows can occasionally demote a Qt topmost tool window after display
        # changes or another app recreates its own topmost window. Reassert the
        # native topmost state without activating the overlay or stealing focus.
        self._topmost_timer = QTimer(self)
        self._topmost_timer.timeout.connect(self._keep_on_top)
        self._topmost_timer.start(750)

        self.show()
        self._keep_on_top()

    def _keep_on_top(self):
        self._apply_geometry()
        if not self.isVisible():
            self.show()
        if sys.platform == "win32" and self.winId():
            SWP_NOSIZE = 0x0001
            SWP_NOMOVE = 0x0002
            SWP_NOACTIVATE = 0x0010
            SWP_SHOWWINDOW = 0x0040
            HWND_TOPMOST = -1
            user32.SetWindowPos(
                wintypes.HWND(int(self.winId())), wintypes.HWND(HWND_TOPMOST),
                0, 0, 0, 0,
                SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE | SWP_SHOWWINDOW,
            )

    @Property(float)
    def progress(self):
        return self._progress

    @progress.setter
    def progress(self, value):
        self._progress = float(value)
        self._apply_geometry()

    @Property(float)
    def lockFactor(self):
        return self._lock_factor

    @lockFactor.setter
    def lockFactor(self, value):
        self._lock_factor = float(value)
        self._apply_geometry()

    def _apply_geometry(self):
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        self._center_x = geo.center().x()
        self._bottom_y = geo.bottom() - OVERLAY_BOTTOM_MARGIN
        p = self._progress
        lf = self._lock_factor
        w_normal = IDLE_SIZE[0] + (ACTIVE_SIZE_NORMAL[0] - IDLE_SIZE[0]) * p
        w_locked = IDLE_SIZE[0] + (ACTIVE_SIZE_LOCKED[0] - IDLE_SIZE[0]) * p
        w = round(w_normal + (w_locked - w_normal) * lf)
        h = round(IDLE_SIZE[1] + (ACTIVE_SIZE_NORMAL[1] - IDLE_SIZE[1]) * p)
        self.setGeometry(self._center_x - w // 2, self._bottom_y - h, w, h)
        self.update()

    def _animate_to(self, target: float):
        self._anim.stop()
        self._anim.setStartValue(self._progress)
        self._anim.setEndValue(target)
        self._anim.start()

    def _update_app_icon(self, hwnd: int):
        if not hwnd:
            self._app_icon = None
            return
        exe = get_target_app_exe(hwnd)
        if not exe:
            self._app_icon = None
            return
        if exe in self._icon_cache:
            self._app_icon = self._icon_cache[exe]
            return
        try:
            info = QFileInfo(exe)
            if info.exists():
                icon = self._icon_provider.icon(info)
                pm = icon.pixmap(32, 32)
                if not pm.isNull():
                    self._app_icon = pm
                    self._icon_cache[exe] = pm
                    return
        except Exception as exc:
            logging.debug("Icon extract error: %s", exc)
        self._app_icon = None

    def start_listening(self, target_hwnd: int = 0, is_locked: bool = False):
        self._mode = RECORDING
        self._is_locked = is_locked
        self._lock_anim.stop()
        self._lock_factor = 1.0 if is_locked else 0.0
        self._update_app_icon(target_hwnd)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_tooltip()
        self._apply_geometry()
        self._animate_to(1.0)
        self._keep_on_top()

    def set_locked(self, is_locked: bool):
        self._is_locked = is_locked
        self._update_tooltip()
        self._lock_anim.stop()
        self._lock_anim.setStartValue(self._lock_factor)
        self._lock_anim.setEndValue(1.0 if is_locked else 0.0)
        self._lock_anim.start()

    def _update_tooltip(self):
        if self._is_locked:
            self.setToolTip("G4Speak lock mode (speak hands-free without holding keys)\nClick or press Ctrl+Space to submit")
        elif self._mode == RECORDING:
            self.setToolTip("G4Speak listening...\nPress Ctrl+Space twice or click the capsule to lock")
        else:
            self.setToolTip("")

    def start_processing(self):
        self._mode = PROCESSING
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.unsetCursor()
        self.setToolTip("Processing...")
        self._apply_geometry()
        self._animate_to(1.0)
        self._keep_on_top()

    def set_idle(self):
        self._mode = IDLE
        self._is_locked = False
        self._level = 0.0
        self._lock_anim.stop()
        self._lock_anim.setStartValue(self._lock_factor)
        self._lock_anim.setEndValue(0.0)
        self._lock_anim.start()
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.unsetCursor()
        self.setToolTip("")
        self._apply_geometry()
        self._animate_to(0.0)

    def set_level(self, level: float):
        self._level = level

    def mousePressEvent(self, event):
        if self._mode == RECORDING:
            if self._is_locked:
                self.finish_clicked.emit()
            else:
                self.lock_clicked.emit()
        event.accept()

    def _tick(self):
        if self._mode == IDLE and self._progress <= 0.01:
            self._level = 0.0
            return
        now = time.monotonic()
        for i in range(BAR_COUNT):
            if self._mode == RECORDING:
                travel_wave1 = math.sin(now * 13.0 - i * 0.95)
                travel_wave2 = math.cos(now * 7.5 + i * 1.30)
                ripple = 0.58 + 0.30 * travel_wave1 + 0.16 * travel_wave2

                if self._level > 0.025:
                    amp_drive = 0.32 + 0.68 * self._level
                    target = amp_drive * self._weights[i] * ripple
                else:
                    idle_ripple = 0.14 + 0.07 * math.sin(now * 6.5 - i * 0.8)
                    target = idle_ripple * self._weights[i]
            elif self._mode == PROCESSING:
                target = (0.42 + 0.28 * math.sin(now * 8.5 - i * 0.65)) * self._weights[i]
            else:
                target = 0.0

            target = min(1.0, max(0.06, target)) if self._mode in (RECORDING, PROCESSING) else 0.0
            rate = 0.58 if target > self._bars[i] else 0.28
            self._bars[i] += (target - self._bars[i]) * rate
        self.update()

    def _draw_minimal_apple_lock(self, painter: QPainter, cx: float, cy: float):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        lock_color = QColor(245, 245, 245, 255)
        shackle_outer_w = 8.4
        shackle_x0 = cx - shackle_outer_w / 2.0
        shackle_x1 = cx + shackle_outer_w / 2.0
        leg_top = cy - 6.5
        leg_bottom = cy + 1.5

        path = QPainterPath()
        path.moveTo(shackle_x0, leg_bottom)
        path.lineTo(shackle_x0, leg_top + shackle_outer_w / 2.0)
        path.arcTo(
            QRectF(shackle_x0, leg_top, shackle_outer_w, shackle_outer_w),
            180, -180,
        )
        path.lineTo(shackle_x1, leg_bottom)

        shackle_pen = QPen(lock_color, 1.9)
        shackle_pen.setCapStyle(Qt.PenCapStyle.SquareCap)
        shackle_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(shackle_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

        body_w = 12.0
        body_h = 8.0
        body_rect = QRectF(cx - body_w / 2.0, cy - 0.5, body_w, body_h)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(lock_color)
        painter.drawRoundedRect(body_rect, 2.8, 2.8)

        painter.restore()

    def _logo_pixmap(self):
        if self._logo_pm is None:
            try:
                if APP_ICON.exists():
                    self._logo_pm = QPixmap(str(APP_ICON)).scaled(
                        128, 128,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
            except Exception as exc:
                logging.debug("Logo pixmap load error: %s", exc)
                self._logo_pm = QPixmap()
        if self._logo_pm is not None and not self._logo_pm.isNull():
            return self._logo_pm
        return None

    def _draw_vector_mic(self, painter: QPainter, cx: float, cy: float):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        capsule_w = 4.8
        capsule_h = 8.2
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(240, 240, 240, 220))
        painter.drawRoundedRect(
            QRectF(cx - capsule_w / 2.0, cy - capsule_h / 2.0 - 1.2, capsule_w, capsule_h),
            capsule_w / 2.0,
            capsule_w / 2.0,
        )

        cup_w = 8.2
        cup_h = 6.4
        cup_x = cx - cup_w / 2.0
        cup_y = cy - 3.0

        path = QPainterPath()
        path.moveTo(cup_x, cup_y)
        path.lineTo(cup_x, cup_y + cup_h / 2.0)
        path.arcTo(QRectF(cup_x, cup_y, cup_w, cup_h), 180, -180)
        path.lineTo(cup_x + cup_w, cup_y)

        cup_pen = QPen(QColor(240, 240, 240, 220), 1.25)
        cup_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(cup_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

        painter.drawLine(QPointF(cx, cup_y + cup_h), QPointF(cx, cup_y + cup_h + 2.2))
        painter.drawLine(QPointF(cx - 2.8, cup_y + cup_h + 2.2), QPointF(cx + 2.8, cup_y + cup_h + 2.2))

        painter.restore()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = rect.height() / 2.0
        cy = rect.center().y()

        border_alpha = int(140 + 75 * self._progress)
        painter.setPen(QPen(QColor(255, 255, 255, border_alpha), 0.85))
        painter.setBrush(QColor(10, 10, 10))
        painter.drawRoundedRect(rect, radius, radius)

        content_alpha = min(1.0, max(0.0, (self._progress - 0.20) / 0.80))
        if content_alpha > 0.01:
            painter.setOpacity(content_alpha)

            lf = self._lock_factor
            content_w = 76.0 + (100.0 - 76.0) * lf
            origin_x = (rect.width() - content_w) / 2.0

            icon_cx = origin_x + 15.0
            icon_size = 16.0
            icon_x = icon_cx - icon_size / 2.0
            icon_y = cy - icon_size / 2.0

            slot_pm = self._app_icon if self._app_icon is not None else self._logo_pixmap()
            if slot_pm is not None and not slot_pm.isNull():
                painter.save()
                clip_path = QPainterPath()
                clip_path.addRoundedRect(QRectF(icon_x, icon_y, icon_size, icon_size), 3.5, 3.5)
                painter.setClipPath(clip_path)
                painter.drawPixmap(
                    QRectF(icon_x, icon_y, icon_size, icon_size),
                    slot_pm,
                    QRectF(slot_pm.rect()),
                )
                painter.restore()
            else:
                self._draw_vector_mic(painter, icon_cx, cy)

            div_left_x = origin_x + 30.0
            painter.setPen(QPen(QColor(255, 255, 255, 45), 0.75))
            painter.drawLine(
                QPointF(div_left_x, cy - 6.0),
                QPointF(div_left_x, cy + 6.0),
            )

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 255, 255, 245))

            bar_w = 2.2
            gap = 2.0
            total_wave_w = BAR_COUNT * bar_w + (BAR_COUNT - 1) * gap
            wave_x = div_left_x + (40.0 - total_wave_w) / 2.0
            max_h = rect.height() * 0.56

            for amp in self._bars:
                h = max(2.6, amp * max_h)
                bar_rect = QRectF(wave_x, cy - h / 2.0, bar_w, h)
                painter.drawRoundedRect(bar_rect, bar_w / 2.0, bar_w / 2.0)
                wave_x += bar_w + gap

            if lf > 0.01:
                painter.setOpacity(content_alpha * min(1.0, lf * 1.2))
                div_right_x = origin_x + 70.0
                painter.setPen(QPen(QColor(255, 255, 255, 45), 0.75))
                painter.drawLine(
                    QPointF(div_right_x, cy - 6.0),
                    QPointF(div_right_x, cy + 6.0),
                )

                lock_cx = origin_x + 85.0
                self._draw_minimal_apple_lock(painter, lock_cx, cy)
                painter.setOpacity(content_alpha)

            painter.setOpacity(1.0)

        painter.end()


# ================== LOW-LEVEL NATIVE WINDOWS HOTKEY HOOK ==================
class LowLevelHotkeyHook(QObject):
    space_down = Signal()
    space_up = Signal()
    ctrl_up = Signal()
    escape_pressed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread = None
        self._thread_id = None
        self._hook = None
        self._hook_proc_ref = None

        self._ctrl_down = False
        self._space_suppressed = False
        self._space_is_held = False
        self._app_active = False

    def set_app_active(self, active: bool):
        self._app_active = active

    def start(self):
        ready = threading.Event()
        self._thread = threading.Thread(target=self._run_hook_thread, args=(ready,), daemon=True)
        self._thread.start()
        ready.wait(timeout=2.0)

    def stop(self):
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, 0x0012, 0, 0)

    def _run_hook_thread(self, ready: threading.Event):
        self._thread_id = kernel32.GetCurrentThreadId()

        def _proc(nCode, wParam, lParam):
            if nCode < 0:
                return user32.CallNextHookEx(None, nCode, wParam, lParam)

            kb = KBDLLHOOKSTRUCT.from_address(lParam)

            if kb.flags & LLKHF_INJECTED:
                return user32.CallNextHookEx(None, nCode, wParam, lParam)

            is_down = wParam in (WM_KEYDOWN, WM_SYSKEYDOWN)
            is_up = wParam in (WM_KEYUP, WM_SYSKEYUP)

            if kb.vkCode in (VK_CONTROL, VK_LCONTROL, VK_RCONTROL):
                self._ctrl_down = is_down
                if is_up:
                    self.ctrl_up.emit()

            ctrl_active = self._ctrl_down or bool(
                user32.GetAsyncKeyState(VK_CONTROL) & 0x8000
                or user32.GetAsyncKeyState(VK_LCONTROL) & 0x8000
                or user32.GetAsyncKeyState(VK_RCONTROL) & 0x8000
            )

            if kb.vkCode == VK_SPACE:
                if ctrl_active or self._space_suppressed:
                    if is_down:
                        self._space_suppressed = True
                        if not self._space_is_held:
                            self._space_is_held = True
                            self.space_down.emit()
                        return 1
                    elif is_up:
                        self._space_suppressed = False
                        self._space_is_held = False
                        self.space_up.emit()
                        return 1

            if kb.vkCode == VK_ESCAPE and is_down:
                if self._app_active:
                    self.escape_pressed.emit()
                    return 1

            return user32.CallNextHookEx(None, nCode, wParam, lParam)

        self._hook_proc_ref = HOOKPROC(_proc)
        self._hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._hook_proc_ref, None, 0)
        if not self._hook:
            logging.error("Failed to install WH_KEYBOARD_LL hook. Error code: %s", kernel32.GetLastError())
        else:
            logging.info("WH_KEYBOARD_LL hook installed successfully.")

        ready.set()

        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        if self._hook:
            user32.UnhookWindowsHookEx(self._hook)
            self._hook = None
        logging.info("WH_KEYBOARD_LL hook uninstalled cleanly.")


# =========================== APP CONTROLLER ===========================
class G4SpeakApp(QObject):
    proofreading_unavailable = Signal()

    def __init__(self, app: QApplication):
        super().__init__()
        self._app = app
        self.state = IDLE
        self.is_locked = False
        self._last_press_time = 0.0

        self.stt = SpeechToTextEngine()
        try:
            get_speech_detector(_asset_path('silero_vad_v6.onnx'))
        except Exception as exc:
            # Never fall back to energy-only detection if the speech model is unavailable.
            logging.error("Speech detector unavailable: %s", exc)
        self.dictionary = PersonalDictionary(
            Path(os.environ.get("APPDATA", str(Path.home()))) / "G4Speak" / "dictionary.json"
        )
        self._last_proofreading_notice = -60.0
        self.proofreading_unavailable.connect(self._notify_proofreading_unavailable)
        self.refiner = TextRefiner(groq_client_getter=lambda: self.stt._groq_client, dictionary=self.dictionary,
                                  on_unavailable=self.proofreading_unavailable.emit)
        self._dictionary_dialog = None
        self._credentials_dialog = None
        self.overlay = Overlay()
        self._record_id = 0
        self._recorder = RecorderThread()
        self._recorder.level.connect(self.overlay.set_level)
        self._recorder.recorded.connect(self._on_recorded)
        self._recorder.failed.connect(self._on_recording_failure)
        self._recorder.start()
        self._worker = None
        self._prev_hwnd = 0
        self._proc_id = 0

        self._grace_timer = QTimer(self)
        self._grace_timer.setSingleShot(True)
        self._grace_timer.timeout.connect(self._on_grace_timeout)

        self._setup_tray()

        self.overlay.lock_clicked.connect(self._lock_recording)
        self.overlay.finish_clicked.connect(self._stop_recording)

        self.hook = LowLevelHotkeyHook(self)
        self.hook.space_down.connect(self._on_space_down)
        self.hook.space_up.connect(self._on_space_up)
        self.hook.ctrl_up.connect(self._on_ctrl_up)
        self.hook.escape_pressed.connect(self._cancel_recording)
        self.hook.start()

    def _setup_tray(self):
        icon = QIcon(str(APP_ICON)) if APP_ICON.exists() else self._app.style().standardIcon(
            QStyle.StandardPixmap.SP_MediaVolume
        )
        self.tray = QSystemTrayIcon(icon, self._app)
        self.tray.setToolTip(f"{APP_NAME} {APP_VERSION}\nHold Ctrl+Space to dictate")
        menu = QMenu()
        menu.addAction("API Credentials...").triggered.connect(self._edit_keys)
        menu.addAction("Reload Settings").triggered.connect(self._reload_keys)
        menu.addAction("Personal Dictionary...").triggered.connect(self._edit_dictionary)
        mode_menu = menu.addMenu("Transcription Mode")
        self._mode_group = QActionGroup(self)
        self._mode_group.setExclusive(True)
        for mode, label in (("smart", "Enhanced"), ("fast", "Standard")):
            action = mode_menu.addAction(label)
            action.setCheckable(True)
            action.setData(mode)
            action.setChecked((mode == "smart") == smart_mode_enabled())
            self._mode_group.addAction(action)
        self._mode_group.triggered.connect(self._set_dictation_mode)
        language_menu = menu.addMenu("Recognition Language")
        self._language_group = QActionGroup(self)
        self._language_group.setExclusive(True)
        for language, label in (("auto", "Automatic"), ("th", "Thai"), ("en", "English")):
            action = language_menu.addAction(label)
            action.setCheckable(True)
            action.setData(language)
            action.setChecked(self.stt._language == language)
            self._language_group.addAction(action)
        self._language_group.triggered.connect(self._set_dictation_language)
        menu.addSeparator()
        self._autostart_action = menu.addAction("Launch at Sign-in")
        self._autostart_action.setCheckable(True)
        self._autostart_action.setChecked(is_autostart_enabled())
        self._autostart_action.setEnabled(bool(getattr(sys, "frozen", False)))
        self._autostart_action.triggered.connect(self._toggle_autostart)
        menu.addSeparator()
        quit_action = menu.addAction("Exit G4Speak")
        quit_action.triggered.connect(self._quit)
        self.tray.setContextMenu(menu)
        self.tray.show()

    def _quit(self):
        self._proc_id += 1
        if self._recorder is not None:
            try:
                self._recorder.shutdown()
                self._recorder.wait()
            except Exception:
                pass
        if self._worker is not None:
            try:
                self._worker.cancel()
                self._wait(self._worker)
            except Exception:
                pass
        self.hook.stop()
        self._app.quit()

    def _notify_error(self, msg: str):
        logging.error(msg)
        self.tray.showMessage(APP_NAME, user_error_message(msg), QSystemTrayIcon.MessageIcon.Warning, 5000)

    def _notify_proofreading_unavailable(self):
        now = time.monotonic()
        if now - self._last_proofreading_notice < 60:
            return
        self._last_proofreading_notice = now
        self.tray.showMessage(APP_NAME,
            "Enhanced proofreading is temporarily unavailable. Your original transcription has been preserved.",
            QSystemTrayIcon.MessageIcon.Information, 5000)

    def _edit_keys(self):
        if self._credentials_dialog is None:
            self._credentials_dialog = CredentialsDialog(load_groq_key() or "", self._save_api_key)
            self._credentials_dialog.finished.connect(self._credentials_closed)
        self._credentials_dialog.show()
        self._credentials_dialog.raise_()
        self._credentials_dialog.activateWindow()

    def _save_api_key(self, key):
        ensure_env_file()
        set_key(str(ENV_FILE), "GROQ_API_KEY", key)
        self._reload_keys()

    def _credentials_closed(self, result):
        dialog = self._credentials_dialog
        self._credentials_dialog = None
        if dialog is not None:
            dialog.deleteLater()

    def _edit_dictionary(self):
        if self._dictionary_dialog is None:
            self._dictionary_dialog = DictionaryDialog(self.dictionary)
            self._dictionary_dialog.finished.connect(self._dictionary_closed)
        self._dictionary_dialog.show()
        self._dictionary_dialog.raise_()
        self._dictionary_dialog.activateWindow()

    def _dictionary_closed(self, result):
        dialog = self._dictionary_dialog
        self._dictionary_dialog = None
        if dialog is not None:
            dialog.deleteLater()

    def _reload_keys(self):
        load_env_file()
        self.stt.reload_keys()
        self.refiner.reload_keys()
        for action in self._mode_group.actions():
            action.setChecked((action.data() == "smart") == smart_mode_enabled())
        for action in self._language_group.actions():
            action.setChecked(action.data() == self.stt._language)
        self.tray.showMessage(
            APP_NAME,
            "Your settings have been updated." if self.stt.is_ready else "Add your Groq API key to begin transcription.",
            QSystemTrayIcon.MessageIcon.Information,
            3500,
        )

    def _set_dictation_mode(self, action):
        try:
            ensure_env_file()
            set_key(str(ENV_FILE), "GROQ_REFINER", "true" if action.data() == "smart" else "false")
            self._reload_keys()
        except OSError as exc:
            for item in self._mode_group.actions():
                item.setChecked((item.data() == "smart") == smart_mode_enabled())
            self._notify_error(f"Could not save dictation mode: {exc}")

    def _set_dictation_language(self, action):
        try:
            ensure_env_file()
            set_key(str(ENV_FILE), "GROQ_STT_LANGUAGE", action.data())
            self._reload_keys()
        except OSError as exc:
            self._notify_error(f"Could not save dictation language: {exc}")

    def _toggle_autostart(self, checked: bool):
        try:
            set_autostart(checked)
        except OSError as exc:
            self._notify_error(f"Run at Startup failed: {exc}")
            self._autostart_action.setChecked(is_autostart_enabled())

    @staticmethod
    def _wait(thread):
        if thread is not None and thread.isRunning():
            thread.wait(3000)

    def _on_space_down(self):
        now = time.monotonic()

        if self.is_locked:
            logging.info("Ctrl+Space pressed while locked -> Finish recording & send text")
            self._stop_recording()
            return

        if self._grace_timer.isActive():
            self._grace_timer.stop()
            logging.info("Double-tap detected (during grace window) -> LOCKED mode!")
            self._lock_recording()
            return

        if (now - self._last_press_time <= DOUBLE_TAP_INTERVAL) and self.state == RECORDING:
            logging.info("Double-tap detected (rapid press) -> LOCKED mode!")
            self._lock_recording()
            return

        self._last_press_time = now
        if self.state == IDLE:
            self._start_recording()

    def _on_space_up(self):
        if self.is_locked:
            return

        if self.state != RECORDING:
            return

        elapsed = time.monotonic() - self._last_press_time
        if elapsed < TAP_QUICK_MAX_S:
            self._grace_timer.start(GRACE_RELEASE_MS)
        else:
            self._stop_recording()

    def _on_ctrl_up(self):
        if self.is_locked:
            return

        if self.state == RECORDING and not self._grace_timer.isActive():
            elapsed = time.monotonic() - self._last_press_time
            if elapsed >= CTRL_RELEASE_MIN_S:
                self._stop_recording()

    def _on_grace_timeout(self):
        if self.state == RECORDING and not self.is_locked:
            logging.info("Grace timer expired: Stopping recording (single short tap)")
            self._stop_recording()

    def _lock_recording(self):
        self.is_locked = True
        self.overlay.set_locked(True)
        logging.info("Lock mode active: Hands-free recording...")

    def _start_recording(self):
        self._prev_hwnd = get_foreground_window()
        self.state = RECORDING
        self.is_locked = False
        self.hook.set_app_active(True)
        self._record_id += 1
        self._recorder.begin(self._record_id)
        self.overlay.start_listening(self._prev_hwnd, is_locked=False)
        logging.info("Recording started (target HWND: %s)...", self._prev_hwnd)

    def _stop_recording(self):
        if self.state != RECORDING:
            return
        self.state = STOPPING
        self._grace_timer.stop()
        self.is_locked = False
        self.overlay.set_locked(False)
        if self._recorder is not None:
            session = self._record_id
            QTimer.singleShot(RECORD_TAIL_MS, lambda: self._recorder.stop(expected_session=session))
            logging.info("Draining microphone tail, then processing speech...")

    def _cancel_recording(self):
        logging.info("Recording cancelled by user.")
        self._proc_id += 1
        if self._worker is not None:
            self._worker.cancel()
        self._grace_timer.stop()
        if self._recorder is not None:
            self._recorder.stop(discard=True)
        self._finish_idle()

    def _on_recording_failure(self, msg, session):
        if session == self._record_id and self.state in (RECORDING, STOPPING):
            self._notify_error(msg)
            self._finish_idle()

    def _on_recorded(self, audio, session):
        if session != self._record_id or self.state not in (RECORDING, STOPPING):
            logging.info("Stale audio dropped (already idle/cancelled).")
            return
        target_hwnd = self._prev_hwnd
        if not is_text_target_available(target_hwnd):
            cur_fg = get_foreground_window()
            if cur_fg != int(self.overlay.winId()) and is_text_target_available(cur_fg):
                self._prev_hwnd = cur_fg
                target_hwnd = cur_fg

        if not is_text_target_available(target_hwnd):
            logging.info("No text target window found. Skipping API calls & releasing.")
            self._finish_idle()
            return

        self.state = PROCESSING
        self.overlay.start_processing()
        self._wait(self._worker)
        self._proc_id += 1
        pid = self._proc_id
        self._worker = ProcessingThread(audio, self.stt, self.refiner, target_hwnd=target_hwnd, dictionary=self.dictionary)
        self._worker.done.connect(lambda t, _pid=pid: self._on_done(t, _pid))
        self._worker.failed.connect(lambda m, _pid=pid: self._on_failure(m, _pid))
        self._worker.start()

    def _on_done(self, text: str, pid: int):
        if pid != self._proc_id:
            logging.info("Stale result dropped (cancelled run).")
            return
        fg = get_foreground_window()
        target = self._prev_hwnd
        if fg != int(self.overlay.winId()) and is_text_target_available(fg):
            target = fg
        if text and is_text_target_available(target):
            insert_text_safely(text, target)
        else:
            logging.info("No speech or text target unavailable. Dropping silently.")
        self._finish_idle()

    def _on_failure(self, msg: str, pid: int):
        if pid != self._proc_id:
            return
        self._notify_error(msg)
        self._finish_idle()

    def _finish_idle(self):
        self.state = IDLE
        self.is_locked = False
        self.hook.set_app_active(False)
        self.overlay.set_idle()


def main():
    # Installer checks the same mutex before updating or uninstalling the app.
    mutex = kernel32.CreateMutexW(None, False, r"Local\G4Speak.App")
    if not mutex:
        raise ctypes.WinError()
    if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        kernel32.CloseHandle(mutex)
        return
    try:
        run_application()
    finally:
        kernel32.CloseHandle(mutex)


def run_application():
    if sys.platform == "win32":
        os.environ.setdefault("QT_QPA_PLATFORM", "windows:dpiawareness=1")
    ensure_env_file()
    load_env_file()
    log_dir = Path(os.environ.get("APPDATA", str(Path.home()))) / "G4Speak" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.StreamHandler(sys.stderr),
            logging.FileHandler(log_dir / "g4speak.log", encoding="utf-8"),
        ],
    )
    logging.info("%s v%s starting...", APP_NAME, APP_VERSION)

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    if APP_ICON.exists():
        app.setWindowIcon(QIcon(str(APP_ICON)))
    app.setQuitOnLastWindowClosed(False)

    controller = G4SpeakApp(app)
    app.aboutToQuit.connect(controller.hook.stop)
    sys.exit(app.exec())


def smoke_test():
    import tempfile
        # Validate the installed bundle without opening a microphone, loading keys,
        # writing user settings, installing hooks, or calling a remote service.
    assert APP_VERSION
    assert APP_ICON.is_file()
    get_speech_detector(_asset_path('silero_vad_v6.onnx'))
    app = QApplication.instance() or QApplication([sys.argv[0]])
    with tempfile.TemporaryDirectory() as directory:
        dictionary = PersonalDictionary(Path(directory) / 'dictionary.json')
        dialog = DictionaryDialog(dictionary)
        dialog.close()
        credentials = CredentialsDialog('', lambda key: None)
        credentials.close()
