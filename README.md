# cogni

**A translation tool that explains, not just translates.**

Look up a single word or idiom and cogni explains it the way a bilingual
friend would: what it means, how it is used, an example sentence, and the
best translation, based on a real online dictionary entry found via web
search. Paste a longer passage and it gives you a fluent translation
instead.

Built as a personal language-learning tool with Python, FastAPI and
the Claude API (developed with AI-assisted tooling).

## Features

- **Two modes, picked automatically.** Short input (a word or expression)
  is explained; longer input is translated. You can also choose the mode
  yourself.
- **Grounded explanations.** For words and idioms, a server-side web search
  finds an actual dictionary entry (e.g. Duden for German) instead of
  relying only on the model's training data, and links the source.
- **Answers in your language.** Meanings, examples, grammar notes and even
  section headings are written in the target language.
- **Grammar and usage on demand.** Noun gender and plural, verb forms and
  typical usage patterns are tucked into an expandable section.
- **Clickable cross-references.** Jump to a related headword (e.g. from
  "snakker" to the infinitive "snakke") or to the same word in a related
  language.
- **Typo-tolerant.** Likely misspellings are corrected automatically and
  the correction is shown.
- **Natural full-text translation.** Uses DeepL when configured and the
  language pair is supported, otherwise Claude.
- **Any language.** Pick from a list or type any language; leave the source
  on auto-detect for less common ones.
- **Streaming web UI.** Results appear as they are written, with live
  progress (e.g. "Searching the web…"). Repeated lookups come from a local
  cache.

## Quick start

Requires Python 3.10+ and an [Anthropic API key](https://console.anthropic.com/).

```sh
git clone https://github.com/laraAsProjects/cogni.git
cd cogni
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then add your ANTHROPIC_API_KEY (DEEPL_API_KEY is optional)
```

**Web UI**

```sh
uvicorn server:app --reload
```

Then open http://127.0.0.1:8000.

**Command line**

```sh
# Explain a word or idiom
python cli.py --from German --to English "einleuchtend"
python cli.py --from German --to English --mode expression "auf dem Holzweg sein"

# Translate a passage
python cli.py --from German --to English "Der Termin wurde kurzfristig verschoben."

# Let it detect the source language
python cli.py --to English "Boazovazzi"
```

## How it works

```
cogni/
├── core.py        # all logic: mode detection, prompts, web search, DeepL/Claude, caching
├── cli.py         # thin command-line wrapper around core.py
├── server.py      # thin FastAPI wrapper: one streaming endpoint + the static UI
├── static/        # plain HTML/CSS/JS frontend, no build step
├── test_core.py   # regression tests (run against the real API)
└── ROADMAP.md     # possible next steps
```

`core.py` only knows "text in, text out". The CLI and the web server are
both thin wrappers around the same `translate()` function, so the web UI
was added without changing the core logic.

## Tests

```sh
pip install -r requirements-dev.txt
python -m pytest test_core.py -v
```

Tests are added whenever a real bug is fixed. They call the real API, so
they are deliberately few.

## Status

A working personal project, run locally. It is not hardened for public
hosting: there is only an optional shared access key, no per-user
authentication or rate limiting. Ideas for next steps are in
[ROADMAP.md](ROADMAP.md).
