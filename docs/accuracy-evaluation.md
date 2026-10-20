# Accuracy evaluation, 2026-10-20

The changes address proofreading output budgets, incomplete answers, unwanted
translation of technical phrases, and unsupported local Thai word substitutions.
Whisper Large-v3 recognition and the hosted model weights are unchanged. This is
application tuning and regression evaluation, not model training or fine-tuning.

## Text regression corpus

The synthetic development corpus contains 24 Thai, English, mixed-language,
technical, and specialized cases, including 13 already-correct controls. These
cases informed development; this is not an independent production accuracy test.

The original code matched 23 of 24 references after presentation normalization,
with 1.70% character error rate (CER). Two cloud responses were incomplete; one
still scored as correct because fallback preserved an already-correct input.

The revised request strategy matched all references over three cloud rounds:
72/72 results, 0% CER, no worsened inputs, no service failures, and no incomplete
responses. All 39 control runs remained correct. The later local Thai replacement
guard was replayed against all 72 recorded results and accepted them unchanged;
the human-audio cases below were evaluated live again after that guard was added.
These results do not establish 100% accuracy for arbitrary dictation.

One observed failure involved a Thai phonetic spelling of Kubernetes. A short
reasoning budget exhausted the output allowance before correction completed.
Disabling reasoning initially produced a complete answer but also translated
the surrounding Thai word for cluster; validation correctly rejected that answer.
Reconsidering the original once with low reasoning effort and a bounded
1,000-token allowance restored the dictionary spelling while retaining Thai.

## Human Thai speech sample

Six distinct utterances were streamed from the pinned Google FLEURS Thai test
archive. All six selected recordings are labeled FEMALE in the source metadata;
this is a small convenience sample, not representative of Thai speakers or the
user's microphone. Source float WAV was converted to 16 kHz mono PCM16 without
changing reference text. Recognition used Whisper Large-v3 with a Thai hint.

Raw recognition contained 72 character errors across 679 normalized reference
characters: 10.60% CER. The final enhanced pipeline contained 41 errors: 6.04% CER,
with two exact references and no utterances worse than raw recognition. There
were no service failures or incomplete responses. This compares the revised
pipeline against raw recognition, not against the old enhanced pipeline.

An intermediate implementation worsened one utterance by replacing a corrupted
Thai word with a different Thai word. Its unchanged surrounding sentence passed
the overall similarity test. The final local consonant check rejects that edit
and retains the original. This avoids the observed regression, but does not
recover the intended word. Large legitimate Thai corrections can also be retained
by this conservative check unless supported by explicit vocabulary.

Four recordings still contain errors, including names and phrases not recoverable
confidently from text alone. CER compares exact spelling and therefore also
penalizes differences between Thai transliteration and Latin reference names.
Automatic language detection and a Thai hint produced the same raw transcripts
on these six clips; existing language settings were retained.

Source: [Google FLEURS](https://huggingface.co/datasets/google/fleurs), revision
`70bb2e84b976b7e960aa89f1c648e09c59f894dd`, under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

## Reproduction and local artifacts

See the evaluation commands in README. Reports normalize whitespace, case, and
ordinary sentence punctuation, while retaining numeric punctuation. They report
raw and final CER, regressions, protected-content changes, service failures, and
incomplete answers separately. Evaluation sends cases to Groq and consumes quota.

Local reports are saved under ignored `.render/`:

- `accuracy-baseline-full.json`: original code, one cloud text round.
- `accuracy-final.json`: three revised cloud text rounds and final-guard replay.
- `accuracy-audio-standard.json`: raw recognition and local formatting.
- `accuracy-audio-auto.json`: automatic-language recognition comparison.
- `accuracy-audio-final.json`: final live enhanced audio evaluation.
- `accuracy-report.html`: interactive text/audio comparison and examples.

The offline regression suite passes 81 tests, and source startup smoke testing
passes. The final portable development build is `dist/accuracy/G4Speak.exe`;
its parent directory supplies the existing API settings, and the personal
dictionary retains its existing APPDATA location. Release v1.3.1 packages these
changes for the portable application and Windows Setup.
