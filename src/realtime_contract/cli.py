"""Command-line entry point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TextIO

from .render import render_json, render_markdown, render_sarif, render_text
from .validator import validate_stream


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="realtime-contract",
        description="Check an OpenAI Realtime API JSONL/WebSocket event transcript offline.",
    )
    subparsers = parser.add_subparsers(dest="command")
    check = subparsers.add_parser("check", help="validate a transcript (use '-' for stdin)")
    check.add_argument(
        "input", nargs="?", default="-", help="JSONL transcript path, or '-' for stdin"
    )
    check.add_argument(
        "--format",
        choices=("text", "json", "markdown", "sarif"),
        default="text",
        help="report format (default: text)",
    )
    check.add_argument(
        "--output", metavar="PATH", help="write the report to a file instead of stdout"
    )
    check.add_argument(
        "--strict-unknown",
        action="store_true",
        help="treat event types outside the checked profile as errors",
    )
    check.add_argument(
        "--fail-on-warning",
        action="store_true",
        help="return exit code 1 when warnings are present",
    )
    check.add_argument(
        "--include-content",
        action="store_true",
        help=(
            "include reconstructed text/transcripts in JSON reports (may contain sensitive data)"
        ),
    )
    return parser


def _open_input(path: str) -> tuple[TextIO, bool]:
    if path == "-":
        return sys.stdin, False
    return Path(path).open("r", encoding="utf-8"), True


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command != "check":
        parser.print_help()
        return 2
    try:
        stream, should_close = _open_input(args.input)
    except OSError as exc:
        print(f"realtime-contract: cannot read {args.input}: {exc}", file=sys.stderr)
        return 2
    try:
        report = validate_stream(
            stream,
            strict_unknown=args.strict_unknown,
            include_content=args.include_content,
        )
    finally:
        if should_close:
            stream.close()
    if args.format == "json":
        rendered = render_json(report)
    elif args.format == "markdown":
        rendered = render_markdown(report)
    elif args.format == "sarif":
        rendered = render_sarif(report, uri=args.input if args.input != "-" else "stdin.jsonl")
    else:
        rendered = render_text(report)
    if args.output:
        try:
            Path(args.output).write_text(rendered, encoding="utf-8")
        except OSError as exc:
            print(f"realtime-contract: cannot write {args.output}: {exc}", file=sys.stderr)
            return 2
    else:
        sys.stdout.write(rendered)
    if report.errors or (args.fail_on_warning and report.warnings):
        return 1
    return 0
