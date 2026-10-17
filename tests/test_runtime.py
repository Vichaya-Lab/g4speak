"""Recording lifecycle and native overlay regression checks (Windows)."""
import os
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import main
import numpy as np


class RegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = main.QApplication.instance() or main.QApplication([])

    def test_recording_sessions_discard_idle_cancel_and_stale_audio(self):
        recorder = main.RecorderThread()
        results = []
        recorder.recorded.connect(lambda audio, session: results.append((audio, session)))
        block = np.full((main.BLOCK_SIZE, 1), 0.1, dtype=np.float32)
        recorder._capture(block, len(block), None, None)
        self.assertEqual(recorder._chunks, [])
        recorder.begin(1)
        recorder._capture(block, len(block), None, None)
        recorder.stop(discard=True)
        self.assertEqual(results, [])
        recorder.begin(2)
        recorder._capture(block, len(block), None, None)
        recorder.stop()
        self.assertEqual(results[0][1], 2)
        np.testing.assert_array_equal(results[0][0], block[:, 0])
        recorder._capture(block, len(block), None, None)
        self.assertEqual(recorder._chunks, [])

    def test_maximum_duration_submits_once(self):
        recorder = main.RecorderThread()
        results = []
        recorder.recorded.connect(lambda audio, session: results.append(audio))
        with patch.object(main, 'MAX_RECORD_SECONDS', main.BLOCK_SIZE / main.SAMPLE_RATE):
            recorder.begin(1)
            block = np.ones((main.BLOCK_SIZE, 1), dtype=np.float32)
            recorder._capture(block, len(block), None, None)
            recorder._capture(block, len(block), None, None)
        self.assertEqual(len(results), 1)
        self.assertEqual(len(results[0]), main.BLOCK_SIZE)

    def test_stream_is_reused_between_sessions(self):
        recorder = main.RecorderThread()
        results = []
        recorder.recorded.connect(lambda audio, session: results.append(session))
        block = np.ones((main.BLOCK_SIZE, 1), dtype=np.float32)

        class Stream:
            latency = 0.032
            def start(self):
                for session in (1, 2):
                    recorder.begin(session)
                    recorder._capture(block, len(block), None, None)
                    recorder.stop()
                recorder.shutdown()
            def close(self):
                pass

        with patch.object(main.sd, 'InputStream', return_value=Stream()) as factory:
            recorder.run()
        self.assertEqual(factory.call_count, 1)
        self.assertEqual(results, [1, 2])

    def test_device_open_falls_back_and_closes_stream(self):
        recorder = main.RecorderThread()
        from unittest.mock import MagicMock
        broken, working = MagicMock(), MagicMock()
        broken.start.side_effect = RuntimeError('unsupported low latency')
        working.latency = 0.1
        working.start.side_effect = recorder.shutdown
        with patch.object(main.sd, 'InputStream', side_effect=[broken, working]) as factory:
            recorder.run()
        self.assertEqual([call.kwargs['latency'] for call in factory.call_args_list], ['low', None])
        broken.close.assert_called_once()
        working.close.assert_called_once()

    def test_overlay_recovers_hidden_idle_without_focus(self):
        overlay = main.Overlay()
        foreground = main.get_foreground_window()
        try:
            overlay.hide()
            overlay._keep_on_top()
            self.app.processEvents()
            self.assertTrue(overlay.isVisible())
            self.assertEqual(main.get_foreground_window(), foreground)
            main.user32.GetWindowLongW.argtypes = [main.wintypes.HWND, main.ctypes.c_int]
            style = main.user32.GetWindowLongW(main.wintypes.HWND(int(overlay.winId())), -20)
            self.assertTrue(style & 0x8)  # WS_EX_TOPMOST
        finally:
            overlay.close()


if __name__ == '__main__':
    unittest.main()
