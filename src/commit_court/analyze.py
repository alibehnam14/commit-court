"""Turn a stream of commits into case-file statistics.

Everything here is single-pass and keeps only aggregates (per-hour counters,
per-file counters, the set of active days, a bounded set of bad-message
examples), so memory stays proportional to the number of files and days, not
the number of commits.
"""

from __future__ import annotations

import math
import re
import zlib
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, Iterable, List, Optional, Tuple

from commit_court.gitlog import Commit

BUGFIX_RE = re.compile(r"\b(fix|bug|hotfix|patch|revert|oops)", re.IGNORECASE)

# Hours (author local time) that count as "late night": 23:00 - 04:59.
LATE_NIGHT_HOURS = frozenset({23, 0, 1, 2, 3, 4})
WEEKEND_DAYS = frozenset({5, 6})  # Saturday, Sunday (datetime.weekday())

LAZY_WORDS = frozenset(
    """
    fix fixes fixed fixing bug bugs bugfix update updates updated change changes changed
    stuff things wip tmp temp test tests testing misc minor small some more again work
    working done commit save saved push oops typo cleanup refactor tweak tweaks edit edits
    final latest new code files file it this that now ok okay pls please plz try trying
    asdf idk lol wtf ugh hmm meh yolo
    اصلاح تغییرات آپدیت تست موقت
    """.split()
)

MASH_RE = re.compile(
    r"^(asdf|qwer|zxcv|hjkl|jkl|sdf|ghj|aaa+|xxx+|zzz+|lol|wtf|ugh|hmm+|blah|meh|foo|bar|baz|yolo|idk)+[0-9]*$"
)

# reason -> severity weight used to rank the worst offenders
SEVERITY: Dict[str, int] = {
    "empty": 5,
    "punctuation": 5,
    "keyboard-mash": 4,
    "final-final": 4,
    "lazy": 3,
    "all-caps": 2,
    "single-word": 1,
    "too-short": 1,
}
REASONS = tuple(SEVERITY)

_WORD_SPLIT = re.compile(r"[\W_]+", re.UNICODE)


def classify_message(message: str) -> List[str]:
    """Return the reasons a commit message is bad (empty list = acceptable)."""
    text = message.strip()
    if not text:
        return ["empty"]
    words = [w for w in _WORD_SPLIT.split(text.lower()) if w]
    if not words:
        return ["punctuation"]

    reasons: List[str] = []
    joined = "".join(words)
    if MASH_RE.match(joined) or re.fullmatch(r"(.)\1{2,}", joined):
        reasons.append("keyboard-mash")
    if len(words) <= 3 and any(w.startswith("final") for w in words):
        reasons.append("final-final")
    if len(words) <= 3 and all(w in LAZY_WORDS or w.isdigit() for w in words):
        reasons.append("lazy")
    letters = [c for c in text if c.isalpha()]
    if len(letters) >= 3 and text == text.upper() and text != text.lower():
        reasons.append("all-caps")
    if len(text.split()) == 1:
        reasons.append("single-word")
    if len(text) < 8:
        reasons.append("too-short")
    return reasons


def is_bugfix(message: str) -> bool:
    return bool(BUGFIX_RE.search(message))


@dataclass
class BadCommit:
    hash: str
    date: datetime
    subject: str
    reasons: List[str]
    count: int = 1  # how many commits share this exact (case-insensitive) message

    @property
    def severity(self) -> int:
        return sum(SEVERITY[r] for r in self.reasons)

    @property
    def infamy(self) -> float:
        """Ranking key: how bad one message is, boosted (logarithmically) by repetition."""
        return self.severity * (1 + math.log2(self.count))


@dataclass
class Span:
    days: int = 0
    start: Optional[date] = None
    end: Optional[date] = None


@dataclass
class FileStat:
    path: str
    commits: int = 0
    fixes: int = 0
    lines: int = 0


@dataclass
class Stats:
    repo_name: str
    total_commits: int = 0
    contributors: int = 0
    first_date: Optional[datetime] = None
    last_date: Optional[datetime] = None
    fix_commits: int = 0
    bad_commits: int = 0
    bad_reasons: Dict[str, int] = field(default_factory=dict)
    worst_messages: List[BadCommit] = field(default_factory=list)
    hours: List[int] = field(default_factory=lambda: [0] * 24)
    bad_hours: List[int] = field(default_factory=lambda: [0] * 24)
    weekdays: List[int] = field(default_factory=lambda: [0] * 7)
    late_night_commits: int = 0
    weekend_commits: int = 0
    streak: Span = field(default_factory=Span)
    gap: Span = field(default_factory=Span)
    defendants: List[FileStat] = field(default_factory=list)
    hotspots: List[FileStat] = field(default_factory=list)
    files_touched: int = 0
    concentration: float = 0.0  # share of changes landing in the busiest 10% of files
    score: int = 100
    score_parts: Dict[str, float] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return self.total_commits == 0

    def ratio(self, n: int) -> float:
        return n / self.total_commits if self.total_commits else 0.0

    @property
    def worst_bad_hour(self) -> Optional[int]:
        if not any(self.bad_hours):
            return None
        return max(range(24), key=lambda h: (self.bad_hours[h], -h))

    @property
    def case_number(self) -> str:
        seed = f"{self.repo_name}|{self.first_date}|{self.total_commits}"
        year = (self.last_date or datetime.now()).year
        return f"CC-{year}-{zlib.crc32(seed.encode('utf-8')) % 100000:05d}"

    @property
    def grade(self) -> str:
        if self.is_empty:
            return "dismissed"
        if self.score >= 90:
            return "acquitted"
        if self.score >= 75:
            return "probation"
        if self.score >= 55:
            return "misdemeanor"
        if self.score >= 35:
            return "felony"
        return "life"


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


# Maximum points each factor can cost. Documented in README.md ("Score formula").
WEIGHTS = {"bad_messages": 35, "fixes": 25, "hotspots": 20, "late_night": 20}


def compute_score(
    total: int, bad: int, fixes: int, late: int, concentration: float
) -> Tuple[int, Dict[str, float]]:
    """Return (score 0-100, penalty fraction 0-1 per factor)."""
    if total <= 0:
        return 100, {k: 0.0 for k in WEIGHTS}
    parts = {
        "bad_messages": _clamp(bad / total),
        "fixes": _clamp((fixes / total - 0.15) / 0.50),
        "hotspots": _clamp(concentration),
        "late_night": _clamp((late / total) / 0.30),
    }
    penalty = sum(WEIGHTS[k] * v for k, v in parts.items())
    return int(round(_clamp(100 - penalty, 0, 100))), parts


def _concentration(touches: List[int]) -> float:
    """Excess share of changes in the busiest 10% of files, 0 = uniform, 1 = all in one."""
    n = len(touches)
    total = sum(touches)
    if n <= 1 or total == 0:
        return 0.0
    k = max(1, math.ceil(n * 0.10))
    baseline = k / n
    share = sum(sorted(touches, reverse=True)[:k]) / total
    return _clamp((share - baseline) / (1 - baseline))


def _spans(days: Iterable[date]) -> Tuple[Span, Span]:
    ordered = sorted(set(days))
    if not ordered:
        return Span(), Span()
    best = Span(1, ordered[0], ordered[0])
    gap = Span()
    run_start = ordered[0]
    for prev, cur in zip(ordered, ordered[1:]):
        delta = (cur - prev).days
        if delta == 1:
            length = (cur - run_start).days + 1
            if length > best.days:
                best = Span(length, run_start, cur)
        else:
            run_start = cur
            if delta - 1 > gap.days:
                gap = Span(delta - 1, prev, cur)
    return best, gap


MAX_TRACKED_MESSAGES = 5000


def analyze(commits: Iterable[Commit], repo_name: str, top_n: int = 10) -> Stats:
    stats = Stats(repo_name=repo_name)
    authors = set()
    days = set()
    files: Dict[str, FileStat] = {}
    bad_by_text: Dict[str, BadCommit] = {}
    reasons: Counter = Counter()

    for c in commits:
        stats.total_commits += 1
        authors.add(c.author)
        if stats.first_date is None or c.date < stats.first_date:
            stats.first_date = c.date
        if stats.last_date is None or c.date > stats.last_date:
            stats.last_date = c.date
        days.add(c.date.date())

        hour = c.date.hour
        stats.hours[hour] += 1
        stats.weekdays[c.date.weekday()] += 1
        if hour in LATE_NIGHT_HOURS:
            stats.late_night_commits += 1
        if c.date.weekday() in WEEKEND_DAYS:
            stats.weekend_commits += 1

        fix = is_bugfix(c.subject)
        if fix:
            stats.fix_commits += 1

        why = classify_message(c.subject)
        if why:
            stats.bad_commits += 1
            stats.bad_hours[hour] += 1
            reasons.update(why)
            key = c.subject.strip().lower()
            existing = bad_by_text.get(key)
            if existing is not None:
                existing.count += 1
            elif len(bad_by_text) < MAX_TRACKED_MESSAGES:
                # Commits arrive newest-first, so the first sighting is the latest one.
                bad_by_text[key] = BadCommit(c.hash, c.date, c.subject, why)

        for change in c.files:
            fs = files.get(change.path)
            if fs is None:
                fs = files[change.path] = FileStat(change.path)
            fs.commits += 1
            fs.lines += change.added + change.deleted
            if fix:
                fs.fixes += 1

    stats.contributors = len(authors)
    stats.bad_reasons = {r: reasons[r] for r in REASONS if reasons[r]}
    stats.worst_messages = sorted(
        bad_by_text.values(), key=lambda b: (b.infamy, b.date), reverse=True
    )[:top_n]
    stats.streak, stats.gap = _spans(days)

    all_files = list(files.values())
    stats.files_touched = len(all_files)
    stats.defendants = sorted(
        (f for f in all_files if f.fixes), key=lambda f: (-f.fixes, -f.commits, f.path)
    )[:top_n]
    stats.hotspots = sorted(all_files, key=lambda f: (-f.commits, -f.lines, f.path))[:top_n]
    stats.concentration = _concentration([f.commits for f in all_files])

    stats.score, stats.score_parts = compute_score(
        stats.total_commits,
        stats.bad_commits,
        stats.fix_commits,
        stats.late_night_commits,
        stats.concentration,
    )
    return stats


def ai_payload(stats: Stats, max_messages: int = 10) -> dict:
    """The ONLY data ever sent to the AI judge: aggregates plus a few commit subjects.

    No code, diffs, file paths, author names or repository name are included.
    """
    span_days = (stats.last_date - stats.first_date).days + 1 if stats.first_date and stats.last_date else 0
    return {
        "total_commits": stats.total_commits,
        "contributors": stats.contributors,
        "history_span_days": span_days,
        "health_score": stats.score,
        "bad_message_ratio": round(stats.ratio(stats.bad_commits), 3),
        "bad_message_reasons": stats.bad_reasons,
        "fix_commit_ratio": round(stats.ratio(stats.fix_commits), 3),
        "late_night_ratio": round(stats.ratio(stats.late_night_commits), 3),
        "weekend_ratio": round(stats.ratio(stats.weekend_commits), 3),
        "hotspot_concentration": round(stats.concentration, 3),
        "longest_streak_days": stats.streak.days,
        "longest_silence_days": stats.gap.days,
        "worst_hour_for_bad_commits": stats.worst_bad_hour,
        "sample_bad_commit_messages": [
            {"message": b.subject[:120], "times": b.count} for b in stats.worst_messages[:max_messages]
        ],
    }
