"""Check evaluation scoring independently of optional cloud services."""
import importlib.util
from pathlib import Path
import unittest


spec = importlib.util.spec_from_file_location('evaluate_accuracy', Path(__file__).resolve().parents[1] / 'scripts/evaluate-accuracy.py')
evaluation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluation)


class AccuracyScoringTests(unittest.TestCase):
    def test_scores_ignore_presentation_but_preserve_numeric_differences(self):
        self.assertEqual(evaluation.normalized('Hello, world!'), evaluation.normalized('hello world'))
        self.assertEqual(evaluation.normalized('ใช้ Python ทำงาน'), evaluation.normalized('ใช้Pythonทำงาน'))
        for left, right in [('0.75', '075'), ('2,500', '2500'), ('21/10/2026', '21/11/2026'), ('10:30', '1030')]:
            self.assertNotEqual(evaluation.normalized(left), evaluation.normalized(right))

    def test_weighted_cer_does_not_hide_fallback_and_regressions(self):
        rows = [
            dict(category='technical', reference_chars=10, raw_errors=4, final_errors=0,
                 exact=True, failures=[], incomplete_responses=0, seconds=1, protected_content_preserved=True),
            dict(category='control', reference_chars=30, raw_errors=0, final_errors=2,
                 exact=False, failures=['unavailable'], incomplete_responses=1, seconds=3, protected_content_preserved=False),
        ]
        all_results = evaluation.summarize(rows)['all']
        self.assertEqual(all_results['raw_cer'], .1)
        self.assertEqual(all_results['final_cer'], .05)
        self.assertEqual(all_results['exact'], 1)
        self.assertEqual(all_results['worsened'], 1)
        self.assertEqual(all_results['service_failures'], 1)
        self.assertEqual(all_results['incomplete_responses'], 1)
        self.assertEqual(all_results['protected_changes'], 1)


if __name__ == '__main__':
    unittest.main()
