"""Fetch a small, reproducible Thai FLEURS sample without downloading its full archive.

Google FLEURS, CC BY 4.0: https://huggingface.co/datasets/google/fleurs
Only the first distinct utterances in the pinned test archive are selected.
The original float WAVs are converted to PCM16; text is unchanged.
"""
import argparse
import io
import json
from pathlib import Path
import struct
import tarfile
import urllib.request
import wave

import numpy as np


REVISION = '70bb2e84b976b7e960aa89f1c648e09c59f894dd'
BASE = f'https://huggingface.co/datasets/google/fleurs/resolve/{REVISION}/data/th_th/'


def pcm16_wav(data):
    """Decode the source IEEE float WAV without an optional audio library."""
    if data[:4] != b'RIFF' or data[8:12] != b'WAVE':
        raise ValueError('Expected RIFF WAV')
    position, fmt, samples = 12, None, None
    while position + 8 <= len(data):
        name, size = struct.unpack_from('<4sI', data, position)
        position += 8
        chunk = data[position:position + size]
        if len(chunk) != size:
            raise ValueError('Incomplete WAV chunk')
        if name == b'fmt ':
            fmt = struct.unpack_from('<HHIIHH', chunk)
        elif name == b'data':
            samples = chunk
        position += size + size % 2
    if fmt is None or samples is None or fmt[1] != 1 or fmt[2] != 16000:
        raise ValueError('Expected 16 kHz mono audio')
    if (fmt[0], fmt[5]) == (3, 32):
        values = np.frombuffer(samples, dtype='<f4')
        samples = (np.clip(np.nan_to_num(values), -1, 1) * 32767).astype('<i2').tobytes()
    elif (fmt[0], fmt[5]) != (1, 16):
        raise ValueError('Unsupported source WAV format')
    output = io.BytesIO()
    with wave.open(output, 'wb') as target:
        target.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        target.writeframes(samples)
    return output.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--count', type=int, choices=range(1, 21), default=6)
    parser.add_argument('--output', type=Path, default=Path('.render/fleurs'))
    args = parser.parse_args()
    with urllib.request.urlopen(BASE + 'test.tsv', timeout=30) as response:
        lines = response.read().decode('utf-8').splitlines()
    metadata = {fields[1]: fields for fields in (line.split('\t') for line in lines)}
    args.output.mkdir(parents=True, exist_ok=True)
    cases, seen = [], set()
    # Stream and stop after the selected clips; never extract archive paths.
    with urllib.request.urlopen(BASE + 'audio/test.tar.gz', timeout=30) as response:
        with tarfile.open(fileobj=response, mode='r|gz') as archive:
            for member in archive:
                name = member.name.rsplit('/', 1)[-1]
                if not member.isfile() or name not in metadata:
                    continue
                fields = metadata[name]
                if fields[0] in seen:
                    continue
                if member.size > 8_000_000:
                    raise ValueError('Unexpectedly large audio entry')
                converted = pcm16_wav(archive.extractfile(member).read())
                (args.output / name).write_bytes(converted)
                seen.add(fields[0])
                cases.append({
                    'id': 'fleurs-th-' + fields[0], 'category': 'thai_audio',
                    'audio': name, 'reference': fields[2], 'language': 'th',
                    'source': f'google/fleurs@{REVISION}/th_th/test/{name}',
                    'speaker_gender': fields[6],
                })
                print(f"Downloaded {len(cases)}/{args.count}: {name}", flush=True)
                if len(cases) == args.count:
                    break
    if len(cases) != args.count:
        raise ValueError('Archive did not contain enough distinct utterances')
    manifest = {
        'description': 'Google FLEURS Thai test speech, CC BY 4.0. Small deterministic sample; not representative of personal dictation. Float WAV converted to PCM16; reference text unchanged.',
        'source': 'https://huggingface.co/datasets/google/fleurs',
        'license': 'https://creativecommons.org/licenses/by/4.0/',
        'revision': REVISION, 'cases': cases,
    }
    (args.output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
