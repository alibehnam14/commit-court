import random
from datetime import date

import pytest

from commit_court.analyze import _spans, ai_payload, analyze, classify_message, compute_score, is_bugfix
from commit_court.gitlog import iter_commits


@pytest.mark.parametrize(
    "message",
    ["fix", "asdf", "wip", "WIP", "final_final2", ".", "...", "update", "stuff", "FIXED IT", "  ", "aaaa", "x", "fix bug"],
)
def test_bad_messages_detected(message):
    assert classify_message(message), message


@pytest.mark.parametrize(
    "message",
    [
        "Add retry with exponential backoff to the HTTP client",
        "fix: handle empty config file without crashing",
        "Refactor auth middleware into its own module",
        "Update README with install instructions",
        "Документация: добавить раздел о установке",
        "افزودن صفحه‌ی ورود کاربران",
    ],
)
def test_good_messages_pass(message):
    assert classify_message(message) == [], message


def test_reasons_are_specific():
    assert "keyboard-mash" in classify_message("asdf")
    assert "final-final" in classify_message("final_final2")
    assert "punctuation" in classify_message(".")
    assert "all-caps" in classify_message("PLEASE WORK NOW")
    assert "empty" in classify_message("")
    assert "lazy" in classify_message("wip")


def test_bugfix_regex():
    assert is_bugfix("Fix crash on startup")
    assert is_bugfix("Revert \"Add thing\"")
    assert is_bugfix("hotfix for prod")
    assert is_bugfix("oops")
    assert not is_bugfix("Add prefix option")
    assert not is_bugfix("Improve debugger docs")


def test_hour_histogram_and_late_night(sample_repo):
    stats = analyze(iter_commits(str(sample_repo.path)), "sample")
    assert stats.total_commits == 8
    assert sum(stats.hours) == 8
    assert stats.hours[2] == 2  # "fix" at 02:15 and "asdf" at 02:45
    assert stats.hours[10] == 1
    assert stats.bad_hours[2] == 2
    assert stats.worst_bad_hour == 2
    assert stats.late_night_commits == 3  # 02:15, 02:45, 23:30
    assert sum(stats.weekdays) == 8


def test_bad_commits_and_examples(sample_repo):
    stats = analyze(iter_commits(str(sample_repo.path)), "sample")
    subjects = {b.subject for b in stats.worst_messages}
    assert {"fix", "asdf", "WIP"} <= subjects
    # The <script> message has no spaces, so it counts as a one-word message too.
    assert stats.bad_commits == 4
    assert stats.worst_messages[0].subject == "asdf"  # keyboard mash is the most severe


def test_defendants_and_hotspots(sample_repo):
    stats = analyze(iter_commits(str(sample_repo.path)), "sample")
    assert stats.defendants[0].path == "app.py"
    assert stats.defendants[0].fixes == 2  # "fix" and "Fix crash..."
    assert stats.hotspots[0].path == "app.py"
    assert stats.hotspots[0].commits == 4


def test_streaks_from_repo(sample_repo):
    stats = analyze(iter_commits(str(sample_repo.path)), "sample")
    assert stats.streak.days == 5  # March 1-5
    assert stats.streak.start == date(2024, 3, 1)
    assert stats.gap.days == 9  # March 6-14 silent
    assert (stats.gap.start, stats.gap.end) == (date(2024, 3, 5), date(2024, 3, 15))


def test_spans_edge_cases():
    streak, gap = _spans([])
    assert streak.days == 0 and gap.days == 0
    streak, gap = _spans([date(2024, 1, 1)])
    assert streak.days == 1 and gap.days == 0
    streak, gap = _spans([date(2024, 1, 1), date(2024, 1, 1), date(2024, 1, 2)])
    assert streak.days == 2


def test_score_bounds_random():
    rng = random.Random(1234)
    for _ in range(2000):
        total = rng.randint(0, 500)
        bad = rng.randint(0, total)
        fixes = rng.randint(0, total)
        late = rng.randint(0, total)
        score, parts = compute_score(total, bad, fixes, late, rng.random())
        assert 0 <= score <= 100
        assert all(0.0 <= v <= 1.0 for v in parts.values())


def test_score_extremes():
    assert compute_score(0, 0, 0, 0, 0.0)[0] == 100
    assert compute_score(100, 0, 10, 0, 0.0)[0] == 100
    assert compute_score(100, 100, 100, 100, 1.0)[0] == 0


def test_empty_history():
    stats = analyze(iter([]), "empty")
    assert stats.is_empty
    assert stats.score == 100
    assert stats.grade == "dismissed"
    assert stats.worst_bad_hour is None


def test_ai_payload_has_no_paths_or_names(sample_repo):
    stats = analyze(iter_commits(str(sample_repo.path)), "secret-repo-name")
    payload = ai_payload(stats)
    flat = repr(payload)
    assert "secret-repo-name" not in flat
    assert "app.py" not in flat
    assert "Test Author" not in flat
    assert len(payload["sample_bad_commit_messages"]) <= 10
