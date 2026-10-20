"""Opt-in live accuracy evaluation; never records a microphone or types text.

Text cases exercise proofreading only. Audio cases use speech detection, Groq
recognition, and proofreading. Supply 16 kHz mono PCM16 WAVs, verified references,
and optional vocabulary/language per case. Reports contain the supplied texts.
"""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import re
import sys
import tempfile
import time
from types import SimpleNamespace
import unicodedata
import wave


def normalized(text):
    # Ignore prose spacing/case/punctuation, retaining decimal/identifier symbols.
    text = unicodedata.normalize('NFC', text).casefold()
    text = re.sub(r'[\s。！？，、“”"\u2018\u2019]+', '', text)
    return re.sub(r'(?<!\d)[,!?;:]|[,!?;:](?!\d)|\.(?!\w)', '', text)


def edit_distance(left, right):
    previous = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        current = [i]
        for j, b in enumerate(right, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (a != b)))
        previous = current
    return previous[-1]


def summarize(rows):
    result = {}
    groups = defaultdict(list)
    for row in rows:
        groups['all'].append(row)
        groups[row['category']].append(row)
    for category, entries in groups.items():
        total = sum(row['reference_chars'] for row in entries)
        result[category] = {
            'runs': len(entries),
            'exact': sum(row['exact'] for row in entries),
            'raw_cer': sum(row['raw_errors'] for row in entries) / max(1, total),
            'final_cer': sum(row['final_errors'] for row in entries) / max(1, total),
            'worsened': sum(row['final_errors'] > row['raw_errors'] for row in entries),
            'service_failures': sum(bool(row['failures']) for row in entries),
            'incomplete_responses': sum(row['incomplete_responses'] for row in entries),
            'protected_changes': sum(not row['protected_content_preserved'] for row in entries),
            'mean_seconds': sum(row['seconds'] for row in entries) / len(entries),
        }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=Path('tests/fixtures/accuracy.json'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source-root', type=Path, default=Path(__file__).resolve().parents[1] / 'src',
                        help='Optional source tree for comparison with an earlier version')
    parser.add_argument('--repeats', type=int, choices=range(1, 6), default=1)
    parser.add_argument('--delay', type=float, default=0, help='Seconds between cases; useful for account limits')
    parser.add_argument('--standard', action='store_true', help='Skip cloud proofreading to measure recognition/formatting alone')
    parser.add_argument('--only', nargs='+', help='Run only these case IDs')
    args = parser.parse_args()
    if args.delay < 0:
        parser.error('--delay must be nonnegative')
    data = json.loads(args.manifest.read_text(encoding='utf-8'))
    cases = data['cases']
    if args.only:
        cases = [case for case in cases if case['id'] in args.only]
        if set(args.only) - {case['id'] for case in cases}:
            parser.error('Unknown case ID in --only')
    if not cases or len({case['id'] for case in cases}) != len(cases):
        parser.error('Manifest must contain cases with unique IDs')
    for case in cases:
        if not isinstance(case.get('reference'), str) or not case['reference'].strip():
            parser.error('Each case needs a nonempty verified reference')
        if ('audio' in case) == ('transcript' in case):
            parser.error('Each case needs exactly one of audio or transcript')
        if case.get('language', 'auto') not in ('auto', 'th', 'en'):
            parser.error('Language must be auto, th, or en')

    sys.path.insert(0, str(args.source_root.resolve()))
    import numpy as np
    from g4speak import app
    from g4speak.text.dictionary import PersonalDictionary

    app.load_env_file()
    key = app.load_groq_key()
    if not key:
        parser.error('Configure a Groq API key before running live evaluation')
    client = app.OpenAI(base_url=app.GROQ_BASE_URL, api_key=key, timeout=30, max_retries=0)
    rows = []
    report = {
        'manifest': str(args.manifest), 'repeats': args.repeats,
        'stt_model': app.os.getenv('GROQ_STT_MODEL', app.GROQ_STT_MODEL),
        'refiner_model': app.os.getenv('GROQ_LLM_MODEL', app.GROQ_LLM_MODEL),
        'description': data.get('description', ''), 'rows': rows,
        'source_root': str(args.source_root.resolve()),
        'transcription_mode': 'standard' if args.standard else 'enhanced',
    }
    # Capture finish reasons as well as failures: fallback must not look like a
    # successful unchanged answer when the service did not finish the request.
    class ObservedClient:
        def __init__(self, inner, requests, failures):
            self.inner = inner
            self.requests = requests
            self.failures = failures
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

        def with_options(self, **options):
            return ObservedClient(self.inner.with_options(**options), self.requests, self.failures)

        def create(self, **options):
            request = {'finish_reason': None}
            self.requests.append(request)
            try:
                response = self.inner.chat.completions.create(**options)
            except Exception as exc:
                self.failures.append({'type': type(exc).__name__, 'status': getattr(exc, 'status_code', None)})
                raise
            request['finish_reason'] = response.choices[0].finish_reason
            return response

    def save():
        report['summary'] = summarize(rows)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    # Select the mode for this process only; persisted user settings are untouched.
    with tempfile.TemporaryDirectory() as directory:
        app.os.environ['GROQ_REFINER'] = 'false' if args.standard else 'true'
        app.os.environ['LOCAL_REFINER'] = 'false'
        for repeat in range(args.repeats):
            for case in cases:
                failures = []
                requests = []
                observed_client = ObservedClient(client, requests, failures)
                dictionary = PersonalDictionary(Path(directory) / 'dictionary.json')
                dictionary.save(case.get('vocabulary', []))
                refiner = app.TextRefiner(groq_client_getter=lambda: observed_client, dictionary=dictionary,
                                          on_unavailable=lambda log=failures: log.append('proofreading_unavailable'))
                start = time.monotonic()
                raw, final = case.get('transcript', ''), ''
                try:
                    if 'audio' in case:
                        path = args.manifest.resolve().parent / case['audio']
                        with wave.open(str(path), 'rb') as source:
                            if (source.getnchannels(), source.getframerate(), source.getsampwidth()) != (1, 16000, 2):
                                raise ValueError('Audio must be 16 kHz mono PCM16 WAV')
                            audio = np.frombuffer(source.readframes(source.getnframes()), dtype='<i2').astype(np.float32) / 32768
                        if len(audio) > app.MAX_RECORD_SECONDS * app.SAMPLE_RATE:
                            raise ValueError('Audio exceeds the recording limit')
                        stt = app.SpeechToTextEngine()
                        stt._groq_client = client
                        stt._language = case.get('language', 'auto')
                        recognized = []
                        def transcribe(*positional, **options):
                            result = stt.transcribe(*positional, **options)
                            recognized.append(result[0])
                            return result
                        # Exercise the actual worker, including VAD, acoustic guards,
                        # deadlines, and dictionary fallback. Its done signal does
                        # not type anything: typing belongs to the GUI controller.
                        worker = app.ProcessingThread(audio, SimpleNamespace(is_ready=True, transcribe=transcribe),
                                                      refiner, dictionary=dictionary)
                        outputs = []
                        worker.done.connect(outputs.append)
                        worker.failed.connect(lambda _, log=failures: log.append('audio_processing_failed'))
                        worker.run()
                        raw = recognized[0] if recognized else ''
                        final = outputs[0] if outputs else ''
                    else:
                        final = refiner.refine(raw)
                        final = app.format_spacing(dictionary.apply(final))
                except Exception as exc:
                    # Store only the exception type/status, never credentials or request headers.
                    failures.append({'type': type(exc).__name__, 'status': getattr(exc, 'status_code', None)})
                reference = normalized(case['reference'])
                row = {
                    'id': case['id'], 'category': case.get('category', 'unspecified'), 'repeat': repeat + 1,
                    'mode': 'audio' if 'audio' in case else 'text',
                    'raw': raw, 'final': final, 'reference': case['reference'],
                    'reference_chars': len(reference),
                    'raw_errors': edit_distance(normalized(raw), reference),
                    'final_errors': edit_distance(normalized(final), reference),
                    'exact': normalized(final) == reference, 'failures': failures,
                    'protected_content_preserved': app.protected_content_matches(raw, final),
                    'incomplete_responses': sum(r['finish_reason'] is not None and r['finish_reason'] != 'stop' for r in requests),
                    'seconds': round(time.monotonic() - start, 3),
                }
                rows.append(row)
                save()
                print(json.dumps({k: row[k] for k in ('id', 'repeat', 'exact', 'raw_errors', 'final_errors', 'failures', 'incomplete_responses')}, ensure_ascii=True), flush=True)
                if failures:
                    print('Stopped after a service/input failure; partial results saved.', flush=True)
                    return 2
                if args.delay and len(rows) < len(cases) * args.repeats:
                    time.sleep(args.delay)
    print(json.dumps(report['summary'], indent=2), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
