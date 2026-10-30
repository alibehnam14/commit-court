import sys
import types

import pytest

from commit_court.analyze import Stats, analyze
from commit_court.gitlog import iter_commits
from commit_court.i18n import LANGS, STRINGS
from commit_court.verdicts import TEMPLATES, ai_verdict, parse_ai_reply, pick_crime, template_verdict


@pytest.mark.parametrize("lang", LANGS)
def test_at_least_twelve_templates_per_language(lang):
    count = sum(len(v) for k, v in TEMPLATES[lang].items() if k != "dismissed")
    assert count >= 12


def test_languages_share_crimes_and_keys():
    assert TEMPLATES["en"].keys() == TEMPLATES["fa"].keys()
    for crime in TEMPLATES["en"]:
        assert len(TEMPLATES["en"][crime]) == len(TEMPLATES["fa"][crime])
    assert STRINGS["en"].keys() == STRINGS["fa"].keys()


@pytest.mark.parametrize("lang", LANGS)
def test_every_template_formats(lang, sample_repo):
    from commit_court.verdicts import _facts

    stats = analyze(iter_commits(str(sample_repo.path)), "sample")
    facts = _facts(stats)
    for rulings in TEMPLATES[lang].values():
        for ruling in rulings:
            for part in ruling:
                part.format(**facts)  # raises KeyError on a typo'd placeholder


def test_verdict_is_deterministic(sample_repo):
    stats = analyze(iter_commits(str(sample_repo.path)), "sample")
    assert template_verdict(stats, "en") == template_verdict(stats, "en")
    v = template_verdict(stats, "en")
    assert v.headline and v.paragraph and v.sentence.startswith("Sentence:")
    assert template_verdict(stats, "fa").sentence.startswith("حکم:")


def test_crime_selection():
    stats = Stats(repo_name="x", total_commits=100, bad_commits=80)
    stats.score_parts = {"bad_messages": 0.8, "fixes": 0.0, "hotspots": 0.1, "late_night": 0.0}
    assert pick_crime(stats) == "bad_messages"
    stats.score_parts = {"bad_messages": 0.05, "fixes": 0.0, "hotspots": 0.0, "late_night": 0.0}
    stats.bad_commits = 5
    assert pick_crime(stats) == "clean"
    assert pick_crime(Stats(repo_name="empty")) == "dismissed"


def test_parse_ai_reply():
    reply = "HEADLINE: Guilty of `wip`.\nVERDICT: Lots of wip.\n**SENTENCE:** Sentence: 2 months."
    parsed = parse_ai_reply(reply)
    assert parsed == {"HEADLINE": "Guilty of `wip`.", "VERDICT": "Lots of wip.", "SENTENCE": "Sentence: 2 months."}
    assert parse_ai_reply("just some chatter") is None


def test_ai_verdict_without_sdk_falls_back(monkeypatch, sample_repo):
    stats = analyze(iter_commits(str(sample_repo.path)), "sample")
    monkeypatch.setitem(sys.modules, "anthropic", None)  # makes `import anthropic` raise ImportError
    logs = []
    assert ai_verdict(stats, log=logs.append) is None
    assert "not installed" in logs[0]


def test_ai_verdict_uses_fake_client(monkeypatch, sample_repo):
    stats = analyze(iter_commits(str(sample_repo.path)), "sample")
    calls = {}

    class FakeMessages:
        def create(self, **kwargs):
            calls.update(kwargs)
            block = types.SimpleNamespace(type="text", text="HEADLINE: H\nVERDICT: V\nSENTENCE: S")
            return types.SimpleNamespace(stop_reason="end_turn", content=[block])

    class FakeClient:
        def __init__(self, **kwargs):
            self.messages = FakeMessages()

    fake = types.ModuleType("anthropic")
    fake.Anthropic = FakeClient
    for name in ("AuthenticationError", "RateLimitError", "APIStatusError", "APIConnectionError"):
        setattr(fake, name, type(name, (Exception,), {}))
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    monkeypatch.setenv("COMMIT_COURT_MODEL", "claude-test-model")

    v = ai_verdict(stats, "en", log=lambda m: None)
    assert v is not None and v.source == "ai" and v.headline == "H"
    assert calls["model"] == "claude-test-model"
    prompt = calls["messages"][0]["content"]
    assert "app.py" not in prompt and "Test Author" not in prompt


def test_ai_verdict_api_failure_falls_back(monkeypatch, sample_repo):
    stats = analyze(iter_commits(str(sample_repo.path)), "sample")
    fake = types.ModuleType("anthropic")
    conn_err = type("APIConnectionError", (Exception,), {})

    class Boom:
        def __init__(self, **kwargs):
            self.messages = types.SimpleNamespace(create=self.create)

        def create(self, **kwargs):
            raise conn_err()

    fake.Anthropic = Boom
    fake.APIConnectionError = conn_err
    for name in ("AuthenticationError", "RateLimitError", "APIStatusError"):
        setattr(fake, name, type(name, (Exception,), {}))
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    logs = []
    assert ai_verdict(stats, log=logs.append) is None
    assert "could not reach" in logs[0]
