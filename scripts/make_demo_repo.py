#!/usr/bin/env python3
"""Build a synthetic repo with a gloriously bad history, then put it on trial.

    python scripts/make_demo_repo.py            # writes examples/sample-report{,.fa}.html

The history is generated deterministically (fixed random seed) and imported in one
shot with ``git fast-import``, so it takes about a second and produces the same
commit hashes every time. All people in it are fictional.
"""

from __future__ import annotations

import argparse
import os
import random
import shutil
import stat
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from commit_court.cli import main as commit_court  # noqa: E402

AUTHORS = [
    # name, email, utc offset (hours)
    ("Detective Debug", "debug@example.com", 3.5),
    ("Sgt. Semicolon", "semicolon@example.com", -8),
    ("Agent Null", "null@example.com", 1),
    ("Intern Kevin", "kevin@example.com", 0),
]

FILES = {
    "src/payments/checkout.js": 9,  # the load-bearing file
    "src/payments/refunds.js": 4,
    "src/api/server.js": 4,
    "src/utils/dates.js": 3,
    "src/legacy/do_not_touch.js": 2,
    "tests/checkout.test.js": 2,
    "config/prod.yml": 2,
    "README.md": 1,
    "docs/ARCHITECTURE.md": 1,
    "src/ui/cart.tsx": 3,
}

GOOD = [
    "Add Stripe webhook signature verification",
    "Implement partial refunds for multi-item orders",
    "Extract currency formatting into utils",
    "Add retry with exponential backoff to payment API client",
    "Document checkout state machine in ARCHITECTURE.md",
    "Add integration tests for refund flow",
    "Cache exchange rates for 10 minutes",
    "Validate cart totals on the server",
    "Upgrade test runner and fix deprecated matchers",
    "Show localized dates on receipts",
    "Add idempotency keys to checkout requests",
    "Log payment provider latency per region",
]

FIXES = [
    "Fix rounding error in currency conversion",
    "Hotfix: guard against null cart in checkout",
    'Revert "Use new tax API"',
    "Patch race condition in refund queue",
    "Fix timezone bug in receipt dates",
    "Fix double charge when user double-clicks Pay",
    "Bugfix: handle expired cards gracefully",
]

BAD = [
    "fix", "fix", "fix", "fix", "fix again", "fix", "asdf", "wip", "WIP", "wip", "final_final2",
    ".", "update", "stuff", "PLEASE WORK", "oops", "hotfix", "temp", "fixed it", "final", "asdfgh",
    "...", "changes", "ok", "test", "fix fix fix", "AAAAAAAA", "why", "lol",
]

FUNNY_BODIES = [
    "// TODO: understand this\n", "console.log('here')\n", "// it works, don't ask\n",
    "if (true) { /* trust me */ }\n", "// fixed (probably)\n", "retries = retries + 1\n",
]


def _rm_readonly(func, path, _exc):
    os.chmod(path, stat.S_IWRITE)
    func(path)


def plan_history(rng: random.Random):
    """Return a list of (local datetime, author, message, [files])."""
    start = datetime(2025, 6, 2, 9, 0)
    events = []
    day = start
    end = datetime(2026, 2, 27)
    while day <= end:
        # Holiday ghosting: nothing at all from Nov 24 to Jan 6.
        if datetime(2025, 11, 24) <= day <= datetime(2026, 1, 6):
            day += timedelta(days=1)
            continue
        crunch = datetime(2026, 1, 26) <= day <= datetime(2026, 2, 27)  # a release crunch streak
        n = rng.choice([0, 0, 1, 1, 2]) if not crunch else rng.choice([1, 2, 3])
        for _ in range(n):
            author = rng.choices(AUTHORS, weights=[4, 3, 2, 3])[0]
            late = rng.random() < (0.45 if crunch else 0.22)
            hour = rng.choice([23, 0, 1, 2, 2, 3, 4]) if late else rng.choice(range(9, 20))
            when = day.replace(hour=hour, minute=rng.randrange(60), second=rng.randrange(60))
            if hour < 5:
                when += timedelta(days=1)  # the 2 a.m. push belongs to the next calendar day
            roll = rng.random()
            if roll < 0.40 + (0.15 if late else 0):
                msg = rng.choice(BAD)
            elif roll < 0.62:
                msg = rng.choice(FIXES)
            else:
                msg = rng.choice(GOOD)
            names, weights = zip(*FILES.items())
            touched = sorted(set(rng.choices(names, weights=weights, k=rng.choice([1, 1, 2, 3]))))
            events.append((when, author, msg, touched))
        # Weekend warriors: Sgt. Semicolon loves Saturdays.
        if day.weekday() == 5 and rng.random() < 0.5:
            when = day.replace(hour=rng.choice([11, 15, 22]), minute=rng.randrange(60))
            events.append((when, AUTHORS[1], rng.choice(BAD + GOOD), ["src/payments/checkout.js"]))
        day += timedelta(days=1)
    events.sort(key=lambda e: e[0])
    return events


def build_repo(repo: Path, seed: int = 7) -> int:
    if repo.exists():
        shutil.rmtree(repo, onerror=_rm_readonly)
    repo.mkdir(parents=True)
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    def run(*args, **kwargs):
        # core.longpaths avoids MAX_PATH failures on Windows when the checkout lives deep in the tree.
        cmd = ["git", "-c", "core.longpaths=true", "-C", str(repo), *args]
        return subprocess.run(cmd, env=env, check=True, **kwargs)

    run("init", "-q")
    run("config", "core.longpaths", "true")
    run("symbolic-ref", "HEAD", "refs/heads/main")

    rng = random.Random(seed)
    contents = {path: f"// {path}\n" for path in FILES}
    stream = bytearray()

    def data(payload: bytes) -> None:
        stream.extend(b"data %d\n" % len(payload))
        stream.extend(payload + b"\n")

    events = plan_history(rng)
    for mark, (when, (name, email, offset), msg, touched) in enumerate(events, 1):
        tz = timezone(timedelta(hours=offset))
        stamp = int(when.replace(tzinfo=tz).timestamp())
        sign = "+" if offset >= 0 else "-"
        hours, minutes = divmod(int(abs(offset) * 60), 60)
        ident = f"{name} <{email}> {stamp} {sign}{hours:02d}{minutes:02d}".encode("utf-8")
        stream.extend(b"commit refs/heads/main\n")
        stream.extend(b"mark :%d\n" % mark)
        stream.extend(b"author " + ident + b"\n")
        stream.extend(b"committer " + ident + b"\n")
        data(msg.encode("utf-8"))
        if mark > 1:
            stream.extend(b"from :%d\n" % (mark - 1))
        for path in touched:
            contents[path] += rng.choice(FUNNY_BODIES)
            stream.extend(f"M 100644 inline {path}\n".encode("utf-8"))
            data(contents[path].encode("utf-8"))
        stream.extend(b"\n")

    run("fast-import", "--quiet", input=bytes(stream))
    run("reset", "-q", "--hard", "main")
    return len(events)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", default=str(ROOT / "build" / "demo" / "acme-payments"), help="where to build the fake repo")
    parser.add_argument("--out-dir", default=str(ROOT / "examples"), help="where to write the sample reports")
    parser.add_argument("--open", action="store_true", help="open the English report when done")
    args = parser.parse_args()

    repo = Path(args.repo)
    count = build_repo(repo)
    print(f"Built {repo} with {count} commits of questionable quality.\n")

    out_dir = Path(args.out_dir)
    status = commit_court([str(repo), "--out", str(out_dir / "sample-report.html"), "--no-open"])
    status |= commit_court([str(repo), "--out", str(out_dir / "sample-report.fa.html"), "--lang", "fa", "--no-open"])
    if args.open and status == 0:
        import webbrowser

        webbrowser.open((out_dir / "sample-report.html").resolve().as_uri())
    return status


if __name__ == "__main__":
    raise SystemExit(main())
