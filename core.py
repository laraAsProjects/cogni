"""
Core translation/meaning-lookup logic for cogni.

Given text and a source/target language pair, this decides whether the
input is a short expression (a word or short phrase) or a longer passage:

  - short expression -> looks it up via a real web search (server-side
    web_search tool - Claude finds actual online dictionary entries, e.g.
    Duden for German, rather than relying only on its own training data),
    then explains the meaning(s) and how it's grammatically used in
    plain, non-technical language, in the target language.
  - longer passage -> translates it. Tries DeepL first (if configured and
    the language pair is supported - DeepL tends to produce more natural,
    reliable translations than an LLM prose-completion for straightforward
    text), falling back to Claude if DeepL isn't set up, doesn't support
    the language pair, or the request fails for any reason.

No CLI or UI code lives here - this module only knows "text in, text out",
so any interface (the CLI in cli.py today, a future web/GUI) can call the
same translate() function without this file changing.
"""

import json
import os
import threading

import requests
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

MODEL = "claude-opus-4-8"

# Persistent result cache, keyed on (mode, text, source_lang, target_lang).
# Expression-mode lookups (a web search + adaptive-thinking Claude call)
# are the expensive path - 10-120s per the timing tests that motivated
# this - and the answer for a given word/idiom doesn't change from one
# lookup to the next, so a repeat lookup (same word, same language pair)
# is pure waste. Deliberately dead simple: one JSON file, loaded once,
# rewritten on every new entry - fine for a personal tool's request
# volume, no need for a real DB/TTL/eviction policy. Not gitignored's
# `.env` company by accident - see .gitignore.
_CACHE_PATH = os.path.join(os.path.dirname(__file__), "cache.json")
_cache_lock = threading.Lock()


def _load_cache() -> dict:
    try:
        with open(_CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


_cache = _load_cache()


def _cache_key(mode: str, text: str, source_lang: str | None, target_lang: str) -> str:
    return json.dumps([mode, text.strip().lower(), (source_lang or "").strip().lower(), target_lang.strip().lower()])


def _cache_get(mode: str, text: str, source_lang: str | None, target_lang: str) -> str | None:
    return _cache.get(_cache_key(mode, text, source_lang, target_lang))


def _cache_set(mode: str, text: str, source_lang: str | None, target_lang: str, result: str) -> None:
    key = _cache_key(mode, text, source_lang, target_lang)
    with _cache_lock:
        _cache[key] = result
        try:
            with open(_CACHE_PATH, "w", encoding="utf-8") as f:
                json.dump(_cache, f, ensure_ascii=False, indent=2)
        except OSError:
            pass  # cache is a pure speed optimization - never let a write failure break a lookup

# Inputs with this many words or fewer, and no sentence-ending punctuation
# before the last character, are treated as "expression" mode; everything
# else is "text" mode. A plain word-count rule instead of asking the model
# to decide - deterministic and easy to read/tune, at the cost of missing
# edge cases (e.g. a 6-word idiom would be treated as full text). Override
# with mode="expression"/"text" when the guess is wrong for a given input.
EXPRESSION_WORD_LIMIT = 5

# DeepL's supported languages (as of their public docs), mapped from a
# lowercased plain-English name to DeepL's language code. Not exhaustive
# of "all kinds of languages" - if a language isn't in here (or DEEPL_API_KEY
# isn't set), text mode just uses Claude directly instead. Source-side,
# DeepL doesn't distinguish English/Portuguese variants (EN, PT); target
# side it does (EN-US vs EN-GB, PT-PT vs PT-BR) - default to the variants
# below, override in the dict if you specifically need the other one.
DEEPL_LANGUAGE_CODES = {
    "arabic": "AR", "bulgarian": "BG", "czech": "CS", "danish": "DA",
    "german": "DE", "greek": "EL", "english": "EN-US", "spanish": "ES",
    "estonian": "ET", "finnish": "FI", "french": "FR", "hungarian": "HU",
    "indonesian": "ID", "italian": "IT", "japanese": "JA", "korean": "KO",
    "lithuanian": "LT", "latvian": "LV", "norwegian": "NB",
    "norwegian bokmal": "NB", "norwegian bokmål": "NB", "dutch": "NL",
    "polish": "PL", "portuguese": "PT-PT", "romanian": "RO", "russian": "RU",
    "slovak": "SK", "slovenian": "SL", "swedish": "SV", "turkish": "TR",
    "ukrainian": "UK", "chinese": "ZH",
}

# Reverse of the above (DeepL code -> display name), keyed by the bare
# code with any regional variant stripped (DeepL's `detected_source_
# language` in a translation response is always bare, e.g. "EN"/"PT",
# never "EN-US"/"PT-PT") - used to show what DeepL itself detected the
# source as, instead of silently discarding that field. `setdefault`
# keeps the first (canonical) name per code, so e.g. "NB" displays as
# "Norwegian" rather than "Norwegian Bokmal"/"Norwegian Bokmål".
DEEPL_CODE_TO_NAME: dict[str, str] = {}
for _name, _code in DEEPL_LANGUAGE_CODES.items():
    DEEPL_CODE_TO_NAME.setdefault(_code.split("-")[0], _name.title())
del _name, _code


def detect_mode(text: str) -> str:
    """Guess whether `text` is a short expression or a longer passage."""
    stripped = text.strip()
    word_count = len(stripped.split())
    # Ignore a single trailing punctuation mark (e.g. "really?" is still a
    # short expression) but treat punctuation earlier in the text as a
    # sign of multiple sentences / real prose.
    body = stripped[:-1] if stripped and stripped[-1] in ".!?" else stripped
    has_sentence_punctuation = any(p in body for p in ".!?")
    if word_count <= EXPRESSION_WORD_LIMIT and not has_sentence_punctuation:
        return "expression"
    return "text"


def _expression_prompt(text: str, source_lang: str | None, target_lang: str) -> str:
    if source_lang:
        source_line = f"Source language: {source_lang} (already known - just echo it back in the Language line below, no need to verify it)."
        search_instruction = f"this word/expression in a reputable online dictionary for {source_lang} (e.g. Duden for German, a standard bilingual or monolingual dictionary for other languages)"
        lang_line_instruction = f'Start your response with exactly this line, nothing before it: "Language: {source_lang}"'
    else:
        source_line = "Source language: not given - identify it yourself."
        search_instruction = "this word/expression - it may be from a lesser-known or minority language, so search broadly rather than assuming"
        lang_line_instruction = 'First identify what language this word/expression is in - it may be obscure, so search broadly rather than assuming. If it\'s used with a similar meaning across more than one language or dialect (e.g. a casual greeting shared by Dutch and Swiss German), pick the most likely one for the Language line below, but say so explicitly in the Meaning section instead of silently picking just one - don\'t let a genuinely cross-language word look like it only belongs to whichever one you happened to name first. Start your response with exactly this line, nothing before it: "Language: <the language you identified>"'

    return f"""You are helping someone understand a word or short expression - the way a knowledgeable friend would explain it over coffee, not the way a dictionary or grammar textbook would. Keep the whole thing tight - this is a quick lookup, not an essay.

{source_line}
Explain in: {target_lang}
Expression: "{text}"

{lang_line_instruction}
If "{text}" looks like a likely misspelling of a real word/expression (not just an unusual-but-valid spelling, informal shorthand, or dialect variant), silently search for and explain the corrected form - always do this automatically, never ask back or refuse to answer because of it. Whenever what you end up explaining differs at all from the literal input, say so in {target_lang}, in one short line right after the Language line, wrapped in single asterisks (italics) and nothing else on that line, e.g. *(als „sprechen" interpretiert)* for German - the UI parses this exact single-asterisk-italic format to show it separately, so don't use double asterisks (bold) for it, that's reserved for the headline below. Include this note every time any correction happened, regardless of how small the difference was, don't judge whether it's worth mentioning; skip the note entirely when the input was already correct as typed. Use the corrected form (not the original typo) as the basis for the headline and everything else below.
Then a blank line, then the rest of your answer below - follow this exact structure and these exact heading names, in this order:

1. Optional headline: if there's one clear, prevalent translation into {target_lang}, add a single bold line: **{{expression}} → {{translation}}**. If it has several distinct senses with no one best translation, skip this line entirely - the per-meaning translations below cover it instead.
2. A "##" heading that's the word for "Meaning" *translated into {target_lang}* (e.g. "## Bedeutung" for German) - or, only if there are genuinely multiple distinct senses (don't split hairs to invent extra ones), that same translated word followed by a number per sense ("## Bedeutung 1", "## Bedeutung 2", ...). 1-3 sentences each, in plain {target_lang}, no grammar-book jargon. If this is an idiom/figurative expression, fold the literal and figurative sense into this same short explanation (e.g. "Literally X - figuratively means Y") rather than a separate section. Do not add tone/register/formality notes (formal vs informal, spoken vs written, etc.) - leave that out entirely.
3. A "##" heading that's the word for "Example" translated into {target_lang} (e.g. "## Beispiel") - one short natural example sentence per meaning (just one if there's a single meaning), each with its translation into {target_lang}.
4. A single short line linking to the actual page you found this on, as a markdown link with the real URL from your search, e.g. *[Duden](https://www.duden.de/rechtschreibung/...)* - not a made-up or guessed URL. If you truly don't have a real URL to point to, fall back to just naming the source in italics with no link.
5. A heading that's *always exactly the literal English text* "## Details" - never translate this one specifically, regardless of {target_lang} (it's an internal marker the app uses to find where to split the page, not something a reader ever actually sees - it gets cut out before display). This section is hidden behind a toggle in the UI, so it's fine to include the textbook-style facts left out above, but keep it just as tight. In this order, each as its own "###" heading, translated into {target_lang} (not bold text, so it renders as a proper subheading in the UI):
   - The word for "Grammar" translated into {target_lang} (e.g. "### Grammatik") - ONLY include this if "{text}" is a single inflectable word (a noun or a verb) - omit entirely for idioms, phrases, or anything multi-word. For a noun: gender and plural as a short line - no table needed for just two facts. For a verb: put the basic forms (at minimum infinitive, present, past - add more only if genuinely essential for this language, e.g. a perfect/participle form) in a small two-column markdown table with real headers - the words for "Tense" and "Form" translated into {target_lang}, never blank - one form per row, using whichever person/number is the natural citation form for that language (e.g. 1st person singular, or the bare stem if that's how dictionaries in this language cite it) - keep the forms in the table only, don't also restate them in prose below it. If there's a genuinely useful extra note that doesn't fit the table (an irregularity, a case quirk), add it as 1-2 short lines below the table. Skip whatever doesn't apply to this language.
   - The word for "Usage" translated into {target_lang} (e.g. "### Verwendung") - one or two sentences on how it's actually used, concrete patterns ("you say ... when ..., or ... when ...") rather than bare terminology.

Two special inline markers, used only where genuinely applicable (don't force either in) - the UI turns these into clickable links that re-run a lookup, so only use them where you'd actually want the reader to be able to click through:
- If this word/expression also exists with a similar meaning in another specific language or dialect, wrap just that language's name the first time you mention it: {{{{lang:LanguageName}}}} (e.g. {{{{lang:Swiss German}}}}) - clicking looks the same word up in that language instead.
- If you mention this is a grammatical form of a different, genuinely separate dictionary headword (e.g. "the present tense of snakke", "the plural of Kind") and that headword is worth looking up on its own, wrap just that headword the first time you mention it: {{{{word:headword}}}} (e.g. {{{{word:snakke}}}}) - clicking looks that word up directly. Don't use this for forms only listed in the Grammar table - just for one mentioned in running prose.

Silently search the web for {search_instruction}, to ground your answer in a real entry rather than just your own recollection - but don't overdo it: one search is usually enough to find a solid source, search again only if that result is genuinely inconclusive, and stop after at most two searches even then. Don't keep re-searching an informal/slang word just to double-check a meaning you're already confident about. If you call web_search from code, its result comes back as a single JSON-encoded string, not a list of dicts - parse it with json.loads() first rather than guessing at its shape by trial and error. Do not narrate that you are about to search, or describe your process at all.

Respond in {target_lang} throughout, including the section heading words themselves (except the Language line, which names the source language, and the literal "## Details" heading, which must stay exactly that in English - see point 5). Output only what's specified above, in that order, nothing else - no other preamble, no closing remarks."""


def _text_prompt(text: str, source_lang: str | None, target_lang: str) -> str:
    if source_lang:
        source_desc = source_lang
        lang_line_instruction = f'Start your response with exactly this line, nothing before it: "Language: {source_lang}"'
    else:
        source_desc = "whatever language it's written in - identify it yourself"
        lang_line_instruction = 'First identify what language the text is written in - it may mix languages or be obscure, so don\'t just assume. Start your response with exactly this line, nothing before it: "Language: <the language you identified>"'

    return f"""You are a professional translator. Translate the following text from {source_desc} to {target_lang}.

{lang_line_instruction}
Then a blank line, then the translation itself. Preserve the original meaning, tone, and register (formal/informal) as closely as natural {target_lang} allows. Output only the Language line and then the translation - no other commentary, notes, or preamble.

Text to translate:
\"\"\"
{text}
\"\"\""""


def _claude_call(prompt: str, use_web_search: bool) -> str:
    client = Anthropic()
    kwargs = dict(
        model=MODEL,
        max_tokens=4096,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": prompt}],
    )
    if use_web_search:
        kwargs["tools"] = [{"type": "web_search_20260209", "name": "web_search"}]

    with client.messages.stream(**kwargs) as stream:
        final_message = stream.get_final_message()

    content = final_message.content
    # With web search, Claude sometimes emits a short "let me look that up"
    # text block before the actual search/tool-use blocks, despite being
    # told not to. Belt-and-suspenders beyond the prompt instruction: only
    # keep text blocks after the last non-text block (i.e. after the
    # search happened), so any such preamble never reaches the output.
    last_tool_index = max((i for i, b in enumerate(content) if b.type != "text"), default=-1)
    return "".join(block.text for i, block in enumerate(content) if block.type == "text" and i > last_tool_index)


def _stream_claude_call(prompt: str, use_web_search: bool):
    """Generator version of _claude_call: yields progress/text events
    instead of blocking until the whole answer is ready. Needed because a
    web-search-grounded expression lookup can take 30-90s+ with zero
    output in the meantime - long enough to trip Cloudflare tunnel
    timeouts (524) and, worse, to just look broken/stuck to a user with
    no feedback at all. Yields dicts:
      {"type": "status", "message": ...}  - e.g. while searching
      {"type": "delta", "text": ...}       - a chunk of the actual answer
    """
    client = Anthropic()
    kwargs = dict(
        model=MODEL,
        max_tokens=4096,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": prompt}],
    )
    if use_web_search:
        kwargs["tools"] = [{"type": "web_search_20260209", "name": "web_search"}]

    # Same "belt and suspenders" as _claude_call: hold back text that
    # arrives before the first non-text block, since it might be a stray
    # "let me look that up" preamble despite being told not to narrate.
    # Unlike _claude_call (which sees the whole response at once and can
    # just check "did any non-text block ever appear?"), this has to
    # decide in real time - so it buffers that leading text instead of
    # dropping it outright. If a non-text block *does* show up later,
    # the buffered text was indeed a preamble - discard it. If the
    # response ends without any non-text block ever appearing (e.g.
    # Claude judges a well-known word doesn't need a search and answers
    # directly), the buffered text *is* the entire real answer - flush it.
    # Getting this wrong previously meant a no-search answer (content is
    # just a single text block, nothing else) was silently swallowed in
    # full: `past_preamble` never flipped True, so every delta was
    # dropped and the UI showed nothing at all.
    resolved = not use_web_search
    pending: list[str] = []

    with client.messages.stream(**kwargs) as stream:
        for event in stream:
            if event.type == "content_block_start":
                block_type = event.content_block.type
                if not resolved and block_type != "text":
                    pending = []  # confirmed preamble - discard
                    resolved = True
                if block_type == "server_tool_use":
                    yield {"type": "status", "message": "Searching the web…"}
                elif block_type == "thinking":
                    yield {"type": "status", "message": "Thinking…"}
            elif event.type == "content_block_delta" and event.delta.type == "text_delta":
                if resolved:
                    yield {"type": "delta", "text": event.delta.text}
                else:
                    pending.append(event.delta.text)

    if pending:
        yield {"type": "delta", "text": "".join(pending)}


def _extract_language_event(events):
    """Wraps an expression-mode event stream: pulls the mandatory leading
    "Language: X" line (see _expression_prompt) out of the first delta
    text and re-emits it as its own {"type": "language", "name": X}
    event instead of markdown body text - lets the UI show it as a badge
    next to the mode badge rather than as the first line of the answer.
    Applied identically whether the text is freshly streamed or replayed
    from cache (see stream_translate) - the raw cached text still starts
    with the same "Language: X" line, so this stays a stateless pass over
    whatever raw text it's given rather than something baked in once at
    generation time."""
    line_buf = ""
    extracted = False
    for event in events:
        if extracted or event["type"] != "delta":
            yield event
            continue
        line_buf += event["text"]
        if "\n" not in line_buf:
            continue  # keep buffering until the whole first line has arrived
        first_line, rest = line_buf.split("\n", 1)
        yield {"type": "language", "name": first_line.removeprefix("Language:").strip()}
        extracted = True
        rest = rest.lstrip("\n")  # drop the blank line separating it from the body
        if rest:
            yield {"type": "delta", "text": rest}


def _tee_accumulate(events, sink: list):
    """Passes events through unchanged while also collecting delta text
    into `sink` - used to cache the raw (pre-extraction) answer text
    while still streaming the extracted version to the caller."""
    for event in events:
        if event["type"] == "delta":
            sink.append(event["text"])
        yield event


def stream_translate(text: str, source_lang: str | None, target_lang: str, mode: str = "auto"):
    """
    Generator version of translate() - same routing logic (see translate()
    for the reasoning), but yields progress as it happens instead of
    returning the whole result at once. Always ends with a
    {"type": "done", "mode_used": ...} event.
    """
    if mode == "auto":
        mode = detect_mode(text)
    elif mode not in ("expression", "text"):
        raise ValueError(f"Unknown mode: {mode!r} (expected 'auto', 'expression', or 'text')")

    if mode == "expression":
        # Expression-mode answers (a dictionary sense/grammar/usage
        # explanation for a given word+language pair) don't change from
        # one lookup to the next, and this is the expensive path (a web
        # search + adaptive-thinking Claude call - 10-120s measured live).
        # A repeat lookup of the same word/idiom into the same language
        # is pure waste without this - see _cache_get/_cache_set.
        cached = _cache_get(mode, text, source_lang, target_lang)
        if cached is not None:
            yield from _extract_language_event([{"type": "delta", "text": cached}])
            yield {"type": "done", "mode_used": mode, "cached": True}
            return

        prompt = _expression_prompt(text, source_lang, target_lang)
        accumulated: list[str] = []
        raw_events = _tee_accumulate(_stream_claude_call(prompt, use_web_search=True), accumulated)
        for event in _extract_language_event(raw_events):
            yield event
        # Cache the raw (pre-extraction) text, Language line included, so
        # a future cache hit can run it through _extract_language_event
        # again and still produce a correct language badge.
        _cache_set(mode, text, source_lang, target_lang, "".join(accumulated))
        yield {"type": "done", "mode_used": mode}
        return

    # mode == "text": DeepL first (if usable - it's fast, no need to
    # stream it), Claude as fallback (streamed, since that path can be
    # slow like expression mode).
    deepl_result = _deepl_translate(text, source_lang, target_lang)
    if deepl_result is not None:
        deepl_text, deepl_lang = deepl_result
        yield {"type": "language", "name": deepl_lang}
        yield {"type": "delta", "text": deepl_text}
        yield {"type": "done", "mode_used": mode}
        return

    prompt = _text_prompt(text, source_lang, target_lang)
    yield from _extract_language_event(_stream_claude_call(prompt, use_web_search=False))
    yield {"type": "done", "mode_used": mode}


def _deepl_translate(text: str, source_lang: str | None, target_lang: str) -> tuple[str, str] | None:
    """Try DeepL for a plain text translation. Returns None if not usable
    (no API key, unsupported language, or the request fails) so the
    caller can fall back to Claude - never raises. Otherwise returns
    (translated_text, detected_source_language_name) - DeepL's response
    always includes detected_source_language (even when source_lang was
    given, though then it's just echoing that back rather than a real
    detection), previously read and silently discarded."""
    api_key = os.environ.get("DEEPL_API_KEY")
    if not api_key:
        return None

    target_code = DEEPL_LANGUAGE_CODES.get(target_lang.strip().lower())
    if not target_code:
        return None

    # DeepL wants the bare language for source (no EN-US/PT-PT split).
    # source_lang is optional in DeepL's own API - if we don't have one,
    # just omit it and let DeepL auto-detect, rather than giving up.
    data = {"text": text, "target_lang": target_code}
    if source_lang:
        source_code = DEEPL_LANGUAGE_CODES.get(source_lang.strip().lower())
        if not source_code:
            return None
        data["source_lang"] = source_code.split("-")[0]

    # Free-tier keys end in ":fx" and use a different host than paid keys.
    host = "api-free.deepl.com" if api_key.endswith(":fx") else "api.deepl.com"

    try:
        response = requests.post(
            f"https://{host}/v2/translate",
            headers={"Authorization": f"DeepL-Auth-Key {api_key}"},
            data=data,
            timeout=15,
        )
        response.raise_for_status()
        translation = response.json()["translations"][0]
        detected_code = translation.get("detected_source_language", "")
        detected_name = DEEPL_CODE_TO_NAME.get(detected_code.split("-")[0], detected_code) if detected_code else (source_lang or "")
        return translation["text"], detected_name
    except (requests.RequestException, KeyError, IndexError, ValueError):
        return None


def translate(text: str, source_lang: str | None, target_lang: str, mode: str = "auto") -> str:
    """
    Translate or explain `text` from source_lang to target_lang.

    source_lang: pass None (or "") to have the source language identified
    automatically instead of specifying it.
    mode: "auto" (default - picks via detect_mode), "expression", or "text".
    """
    if mode == "auto":
        mode = detect_mode(text)
    elif mode not in ("expression", "text"):
        raise ValueError(f"Unknown mode: {mode!r} (expected 'auto', 'expression', or 'text')")

    if mode == "expression":
        # See the matching comment in stream_translate() - same cache.
        cached = _cache_get(mode, text, source_lang, target_lang)
        if cached is not None:
            return cached
        prompt = _expression_prompt(text, source_lang, target_lang)
        result = _claude_call(prompt, use_web_search=True)
        _cache_set(mode, text, source_lang, target_lang, result)
        return result

    # mode == "text": DeepL first (if usable), Claude as fallback.
    deepl_result = _deepl_translate(text, source_lang, target_lang)
    if deepl_result is not None:
        deepl_text, deepl_lang = deepl_result
        return f"Language: {deepl_lang}\n\n{deepl_text}"

    prompt = _text_prompt(text, source_lang, target_lang)
    return _claude_call(prompt, use_web_search=False)
