import re
from datetime import datetime
from html.parser import HTMLParser

import pytest

from commit_court.analyze import analyze
from commit_court.gitlog import iter_commits
from commit_court.i18n import LANGS
from commit_court.render import render_report, rich
from commit_court.verdicts import Verdict, template_verdict

VOID = {"meta", "br", "hr", "img", "input", "link", "source", "wbr", "area", "base", "col", "embed", "track"}
SVG_SELF_CLOSING_OK = {"rect", "circle", "line", "path"}


class StrictChecker(HTMLParser):
    """Fails on mismatched/unclosed tags so we catch broken markup, not just crashes."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.errors = []
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        if tag not in VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.tags.append(tag)
        if tag not in VOID and tag not in SVG_SELF_CLOSING_OK:
            self.errors.append(f"unexpected self-closing <{tag}/>")

    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(f"unexpected </{tag}>, open: {self.stack[-3:]}")
            return
        self.stack.pop()


def check_html(doc: str) -> StrictChecker:
    checker = StrictChecker()
    checker.feed(doc)
    checker.close()
    assert not checker.errors, checker.errors[:5]
    assert not checker.stack, f"unclosed: {checker.stack}"
    return checker


@pytest.fixture(scope="module")
def stats(sample_repo):
    return analyze(iter_commits(str(sample_repo.path)), "sample <repo> & co")


@pytest.mark.parametrize("lang", LANGS)
def test_report_renders_and_is_well_formed(stats, lang):
    doc = render_report(stats, template_verdict(stats, lang), lang=lang, generated=datetime(2026, 1, 2, 3, 4))
    checker = check_html(doc)
    assert doc.startswith("<!DOCTYPE html>")
    assert checker.tags.count("script") == 1  # only our own inline script
    assert checker.tags.count("svg") >= 3  # two rings + hour + weekday charts
    for title in ("The Defendants", "Serial Offenders", "Time of Crime", "Churn Hotspots") if lang == "en" else ():
        assert title in doc
    assert "copy-btn" in doc and "share-text" in doc


def test_persian_report_is_rtl(stats):
    doc = render_report(stats, template_verdict(stats, "fa"), lang="fa")
    assert '<html lang="fa" dir="rtl">' in doc
    assert "Vazirmatn" in doc and "Tahoma" in doc
    assert "متهمان" in doc and "رأی دادگاه" in doc
    assert "@font-face" not in doc


def test_no_external_requests(stats):
    doc = render_report(stats, template_verdict(stats, "en"))
    assert "default-src 'none'" in doc
    assert not re.search(r'(src|href)="(https?:)?//(?!github\.com)', doc)
    assert "@import" not in doc and "url(" not in doc


def test_repo_text_is_escaped(stats):
    doc = render_report(stats, template_verdict(stats, "en"))
    assert "<script>alert" not in doc
    assert "&lt;script&gt;alert(&#x27;pwned&#x27;)&lt;/script&gt;" in doc or "&lt;script&gt;alert" in doc
    assert "sample &lt;repo&gt; &amp; co" in doc
    assert "tom&amp;jerry&#x27;s.txt" in doc


def test_malicious_ai_verdict_is_escaped(stats):
    evil = Verdict(
        crime="bad_messages",
        headline='Guilty <img src=x onerror=alert(1)> of `<b>x</b>`',
        paragraph="</p><script>steal()</script>",
        sentence='" onmouseover="alert(1)',
        source="ai",
    )
    doc = render_report(stats, evil, ai_used=True)
    check_html(doc)
    assert "<img" not in doc
    assert "<script>steal" not in doc
    assert "<code dir=\"ltr\">&lt;b&gt;x&lt;/b&gt;</code>" in doc
    assert "Only aggregated stats" in doc


def test_rich_only_wraps_backticks():
    assert rich("a `b` <c>") == 'a <code dir="ltr">b</code> &lt;c&gt;'


def test_empty_repo_renders():
    empty = analyze(iter([]), "nothing-here")
    for lang in LANGS:
        doc = render_report(empty, template_verdict(empty, lang), lang=lang)
        check_html(doc)
    assert "Case dismissed" in render_report(empty, template_verdict(empty, "en"))
