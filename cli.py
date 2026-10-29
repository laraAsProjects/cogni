#!/usr/bin/env python3
"""
CLI for cogni - a thin wrapper around core.py's translate().

Examples:
    python cli.py --from German --to English "einleuchtend"
    python cli.py --from German --to English --file input.txt
    python cli.py --from German --to English --file input.txt --out output.txt
    python cli.py --from German --to English --mode text "kurzer erzwungener Satz"
    python cli.py --from German --to English --batch examples.txt
"""

import argparse

from core import translate


def run_batch(path: str, source_lang: str, target_lang: str, mode: str) -> None:
    """Run every non-empty, non-comment line in `path` as its own separate
    lookup/translation and print them one after another with a header per
    item - for eyeballing many examples at once while tuning prompts."""
    with open(path, "r", encoding="utf-8") as f:
        items = [line.strip() for line in f if line.strip() and not line.strip().startswith("#")]

    for i, item in enumerate(items, start=1):
        print(f"--- [{i}/{len(items)}] {item!r} " + "-" * max(0, 40 - len(item)))
        try:
            print(translate(item, source_lang, target_lang, mode=mode))
        except Exception as e:
            print(f"ERROR: {e}")
        print()


def main():
    parser = argparse.ArgumentParser(description="Translate or explain text with context-aware nuance.")
    parser.add_argument("text", nargs="?", help="Text to translate/explain (omit if using --file/--batch)")
    parser.add_argument("--file", help="Read input text from this file instead of the text argument")
    parser.add_argument("--batch", help="Run each line of this file as a separate example (see examples.txt)")
    parser.add_argument("--out", help="Write output to this file instead of printing to stdout (not used with --batch)")
    parser.add_argument("--from", dest="source_lang", default=None, help="Source language, e.g. German (omit to auto-identify)")
    parser.add_argument("--to", dest="target_lang", required=True, help="Target language, e.g. English")
    parser.add_argument(
        "--mode",
        choices=["auto", "expression", "text"],
        default="auto",
        help="Force expression or text mode; default auto-detects from input length",
    )
    args = parser.parse_args()

    if args.batch:
        run_batch(args.batch, args.source_lang, args.target_lang, args.mode)
        return

    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            text = f.read()
    elif args.text:
        text = args.text
    else:
        parser.error("provide text as an argument, or via --file/--batch")

    result = translate(text, args.source_lang, args.target_lang, mode=args.mode)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(result)
        print(f"Written to {args.out}")
    else:
        print(result)


if __name__ == "__main__":
    main()
