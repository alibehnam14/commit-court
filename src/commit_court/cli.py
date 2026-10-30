"""Command-line entry point: ``commit-court [path] [options]``."""

from __future__ import annotations

import argparse
import os
import sys
import webbrowser
from pathlib import Path
from typing import List, Optional

from commit_court import __version__
from commit_court.analyze import analyze, ai_payload
from commit_court.gitlog import GitError, iter_commits, repo_root
from commit_court.i18n import LANGS
from commit_court.render import render_report
from commit_court.verdicts import DEFAULT_MODEL, ai_verdict, template_verdict

DEFAULT_OUT = "commit-court-report.html"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="commit-court",
        description="Put a git repository on trial and write a courtroom-style HTML case file.",
    )
    p.add_argument("path", nargs="?", default=".", help="path to the git repository (default: .)")
    p.add_argument("--out", metavar="FILE", default=DEFAULT_OUT, help=f"output HTML file (default: {DEFAULT_OUT})")
    p.add_argument("--since", metavar="DATE", help="only consider commits after DATE (anything git log --since accepts)")
    p.add_argument("--author", metavar="NAME", help="only consider commits by authors matching NAME")
    p.add_argument("--lang", choices=LANGS, default="en", help="report language (default: en)")
    p.add_argument(
        "--ai",
        action="store_true",
        help="ask Claude for the verdict (needs ANTHROPIC_API_KEY and commit-court[ai]); sends only aggregated "
        "stats and up to 10 commit messages",
    )
    p.add_argument("--no-ai", action="store_true", help="force the built-in template verdict (overrides --ai)")
    p.add_argument("--include-merges", action="store_true", help="include merge commits (excluded by default)")
    p.add_argument("--no-open", action="store_true", help="do not open the report in a browser")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def _err(msg: str) -> None:
    print(f"commit-court: {msg}", file=sys.stderr)


def _privacy_notice(payload: dict, model: str) -> None:
    print("")
    print("  [AI] Privacy notice")
    print(f"  The verdict will be written by Claude ({model}) via the Anthropic API.")
    print("  Sent: aggregated statistics only (counts and ratios) plus up to")
    print(f"  {len(payload['sample_bad_commit_messages'])} commit message(s):")
    for item in payload["sample_bad_commit_messages"]:
        print(f"    - {item['message']!r}")
    print("  NOT sent: source code, diffs, file paths, author names, emails, repo name.")
    print("")


def main(argv: Optional[List[str]] = None) -> int:
    # Never crash on a console that can't print Persian or emoji.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass

    args = build_parser().parse_args(argv)
    for name in ("since", "author"):
        value = getattr(args, name)
        if value is not None and value.startswith("-"):
            _err(f"--{name} value must not start with '-'.")
            return 2

    try:
        root = repo_root(args.path)
        commits = iter_commits(root, since=args.since, author=args.author, include_merges=args.include_merges)
        stats = analyze(commits, repo_name=Path(root).name or root)
    except GitError as exc:
        _err(str(exc))
        return 2
    except KeyboardInterrupt:
        _err("interrupted.")
        return 130

    if stats.is_empty:
        print("No commits found (empty repository or filters matched nothing). The case will be dismissed.")

    verdict = None
    use_ai = args.ai and not args.no_ai
    if use_ai:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("AI verdict skipped: ANTHROPIC_API_KEY is not set. Using a template verdict.")
        elif stats.is_empty:
            print("AI verdict skipped: nothing to judge.")
        else:
            model = os.environ.get("COMMIT_COURT_MODEL") or DEFAULT_MODEL
            _privacy_notice(ai_payload(stats), model)
            verdict = ai_verdict(stats, lang=args.lang, model=model)
    ai_used = verdict is not None
    if verdict is None:
        verdict = template_verdict(stats, args.lang)

    html_text = render_report(stats, verdict, lang=args.lang, ai_used=ai_used)
    out = Path(args.out)
    try:
        if out.parent and not out.parent.exists():
            out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(html_text)
    except OSError as exc:
        _err(f"could not write {out}: {exc}")
        return 1

    print(f"Case {stats.case_number}: {stats.repo_name}")
    print(f"  Commits reviewed : {stats.total_commits}")
    print(f"  Health score     : {stats.score}/100 ({stats.grade})")
    print(f"  Verdict          : {verdict.headline}")
    print(f"  Report written   : {out.resolve()}")

    if not args.no_open:
        try:
            webbrowser.open(out.resolve().as_uri())
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
