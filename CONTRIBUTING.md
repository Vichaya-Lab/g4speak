# Contributing to G4Speak

Thanks for helping out. G4Speak is a small Windows voice-to-text app (Python 3.12).

## Quick start

```bat
pip install -r requirements.txt
python main.py
```

You need a free `GROQ_API_KEY` from https://console.groq.com/keys — copy
`.env.example` to `.env` and paste your key. Never commit `.env`.

## Tests

Guardrail tests run without downloading any model:

```bat
python tests/test_guards.py
```

Run them before every pull request.

## Pull requests

1. Fork, branch from `main`, keep changes focused.
2. Update `README.md` / `CHANGELOG.md` if behavior changes.
3. One logical change per PR. CI builds the exe on `v*` tags only.
