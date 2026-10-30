"""Render Stats + Verdict into one self-contained HTML case file.

Security rule: every piece of repo-derived text (commit messages, author names,
file paths, repo name) and AI output goes through ``esc()`` before it touches
the markup. The page also ships a Content-Security-Policy that forbids any
network request, so it is safe to open from disk.
"""

from __future__ import annotations

import html
import re
from datetime import datetime
from typing import List, Optional, Sequence

from commit_court import PROJECT_URL, __version__
from commit_court.analyze import LATE_NIGHT_HOURS, WEEKEND_DAYS, WEIGHTS, FileStat, Span, Stats
from commit_court.i18n import FONTS, WEEKDAYS, t
from commit_court.verdicts import Verdict

EXHIBIT_LETTERS = {
    "en": ["A", "B", "C", "D", "E", "F"],
    "fa": ["الف", "ب", "ج", "د", "هـ", "و"],
}

GRADE_COLORS = {
    "acquitted": "#5fbf7a",
    "probation": "#c9b458",
    "misdemeanor": "#e6a23c",
    "felony": "#e8703a",
    "life": "#e0443e",
    "dismissed": "#8a8f98",
}


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def rich(text: str) -> str:
    """Escape, then turn `backticks` into <code>. Safe: runs on already-escaped text."""
    return re.sub(r"`([^`]+)`", r'<code dir="ltr">\1</code>', esc(text))


def _num(n: int) -> str:
    return f"{n:,}"


def _date(d: Optional[object]) -> str:
    return d.strftime("%Y-%m-%d") if d is not None else "—"


def _ltr(text: str, cls: str = "") -> str:
    klass = f' class="{cls}"' if cls else ""
    return f'<span dir="ltr"{klass}>{esc(text)}</span>'


# --------------------------------------------------------------------------- sections


def _section(lang: str, index: int, title_key: str, sub_key: Optional[str], body: str) -> str:
    letter = EXHIBIT_LETTERS[lang][index]
    sub = f'<p class="sub">{esc(t(lang, sub_key))}</p>' if sub_key else ""
    return (
        f'<section class="card">'
        f'<div class="exhibit">{esc(t(lang, "exhibit"))} {esc(letter)}</div>'
        f'<h2>{esc(t(lang, title_key))}</h2>{sub}{body}</section>'
    )


def _empty(lang: str) -> str:
    return f'<p class="empty">{esc(t(lang, "no_evidence"))}</p>'


def _score_ring(score: int, grade: str, size: int = 132) -> str:
    r = 54
    circumference = 2 * 3.14159265 * r
    dash = circumference * max(0, min(100, score)) / 100
    color = GRADE_COLORS[grade]
    return (
        f'<svg class="ring" width="{size}" height="{size}" viewBox="0 0 132 132" role="img" '
        f'aria-label="{score}/100">'
        f'<circle cx="66" cy="66" r="{r}" fill="none" stroke="var(--line)" stroke-width="10"/>'
        f'<circle cx="66" cy="66" r="{r}" fill="none" stroke="{color}" stroke-width="10" '
        f'stroke-linecap="round" stroke-dasharray="{dash:.1f} {circumference:.1f}" '
        f'transform="rotate(-90 66 66)"/>'
        f'<text x="66" y="72" text-anchor="middle" class="ring-num" fill="var(--ink)">{score}</text>'
        f'<text x="66" y="92" text-anchor="middle" class="ring-of" fill="var(--muted)">/100</text>'
        f"</svg>"
    )


def _header(stats: Stats, lang: str, generated: datetime) -> str:
    period = (
        f'{_ltr(_date(stats.first_date))} <span class="dash">–</span> {_ltr(_date(stats.last_date))}'
        if not stats.is_empty
        else "—"
    )
    tiles = [
        (t(lang, "period"), period),
        (t(lang, "commits"), _num(stats.total_commits)),
        (t(lang, "contributors"), _num(stats.contributors)),
        (t(lang, "files"), _num(stats.files_touched)),
    ]
    tiles_html = "".join(
        f'<div class="tile"><div class="k">{esc(k)}</div><div class="v">{v}</div></div>' for k, v in tiles
    )
    grade = stats.grade
    return (
        '<header class="card head">'
        f'<div class="topline"><span class="brand">⚖ {esc(t(lang, "court"))}</span>'
        f'<span class="caseno">{esc(t(lang, "case_no"))} {_ltr(stats.case_number)}</span></div>'
        f'<div class="stamp">{esc(t(lang, "confidential"))}</div>'
        '<div class="title-row"><div class="title-text">'
        f'<div class="people">{esc(t(lang, "people_v"))}</div>'
        f'<h1 dir="auto">{esc(stats.repo_name)}</h1>'
        f'<div class="filed">{esc(t(lang, "filed"))}: {_ltr(generated.strftime("%Y-%m-%d"))}</div>'
        "</div>"
        f'<div class="badge">{_score_ring(stats.score, grade)}'
        f'<div class="grade" style="color:{GRADE_COLORS[grade]}">{esc(t(lang, "grade_" + grade))}</div></div>'
        "</div>"
        f'<div class="tiles">{tiles_html}</div>'
        "</header>"
    )


def _file_table(lang: str, rows: Sequence[FileStat], value_key: str, value_of, extra_key: str, extra_of) -> str:
    if not rows:
        return _empty(lang)
    top = max(value_of(r) for r in rows) or 1
    body = []
    for i, row in enumerate(rows, 1):
        width = 100 * value_of(row) / top
        body.append(
            "<tr>"
            f'<td class="rank">{i}</td>'
            f'<td class="path"><code dir="ltr">{esc(row.path)}</code>'
            f'<div class="meter"><span style="width:{width:.1f}%"></span></div></td>'
            f'<td class="n">{_num(value_of(row))}</td>'
            f'<td class="n muted">{_num(extra_of(row))}</td>'
            "</tr>"
        )
    return (
        '<table class="files"><thead><tr>'
        f'<th class="rank">{esc(t(lang, "col_rank"))}</th><th>{esc(t(lang, "col_file"))}</th>'
        f'<th class="n">{esc(t(lang, value_key))}</th><th class="n">{esc(t(lang, extra_key))}</th>'
        f'</tr></thead><tbody>{"".join(body)}</tbody></table>'
    )


def _defendants(stats: Stats, lang: str) -> str:
    table = _file_table(
        lang, stats.defendants, "col_fixes", lambda f: f.fixes, "col_commits", lambda f: f.commits
    )
    return _section(lang, 0, "s_defendants", "s_defendants_sub", table)


def _chips(lang: str, reasons: Sequence[str]) -> str:
    return "".join(f'<span class="chip">{esc(t(lang, "reason_" + r))}</span>' for r in reasons)


def _offenders(stats: Stats, lang: str) -> str:
    if stats.bad_commits == 0:
        body = f'<p class="clean">{esc(t(lang, "bad_none"))}</p>'
        return _section(lang, 1, "s_offenders", "s_offenders_sub", body)

    pct = round(100 * stats.ratio(stats.bad_commits))
    summary = t(lang, "bad_summary", total=_num(stats.total_commits), pct=pct)
    reason_chips = "".join(
        f'<span class="chip big">{esc(t(lang, "reason_" + r))} <b>{_num(n)}</b></span>'
        for r, n in sorted(stats.bad_reasons.items(), key=lambda kv: -kv[1])
    )
    items = []
    for b in stats.worst_messages[:5]:
        count = f'<span class="count">×{_num(b.count)}</span>' if b.count > 1 else ""
        items.append(
            '<li class="rap">'
            f'<div class="quote" dir="auto">“{esc(b.subject) or "&nbsp;"}”{count}</div>'
            f'<div class="rap-meta">{_ltr(b.hash[:7], "hash")} {_ltr(_date(b.date), "muted")} '
            f"{_chips(lang, b.reasons)}</div>"
            "</li>"
        )
    body = (
        f'<p class="summary"><span class="big-num">{_num(stats.bad_commits)}</span> {esc(summary)}</p>'
        f'<div class="chips">{reason_chips}</div>'
        f'<ol class="raps">{"".join(items)}</ol>'
    )
    return _section(lang, 1, "s_offenders", "s_offenders_sub", body)


def _hour_chart(stats: Stats, lang: str) -> str:
    left, slot, bar, base, height = 34, 33, 23, 182, 160
    peak = max(stats.hours) or 1
    parts: List[str] = []
    for h in range(24):
        if h in LATE_NIGHT_HOURS:
            parts.append(f'<rect x="{left + h * slot}" y="6" width="{slot}" height="{base - 6}" class="late"/>')
    for h in range(24):
        total, bad = stats.hours[h], stats.bad_hours[h]
        x = left + h * slot + (slot - bar) / 2
        total_h = height * total / peak
        bad_h = height * bad / peak
        tip = f"{h:02d}:00 — {total} ({bad} ✗)"
        parts.append(
            f"<g><title>{esc(tip)}</title>"
            f'<rect x="{x:.1f}" y="{base - total_h:.1f}" width="{bar}" height="{total_h - bad_h:.1f}" '
            f'rx="2" class="bar-ok"/>'
            f'<rect x="{x:.1f}" y="{base - bad_h:.1f}" width="{bar}" height="{bad_h:.1f}" class="bar-bad"/></g>'
        )
        if h % 3 == 0:
            parts.append(
                f'<text x="{left + h * slot + slot / 2:.1f}" y="{base + 17}" text-anchor="middle" '
                f'class="axis">{h:02d}</text>'
            )
    parts.append(f'<line x1="{left}" y1="{base}" x2="{left + 24 * slot}" y2="{base}" class="baseline"/>')
    parts.append(f'<text x="{left - 6}" y="{base - height + 4}" text-anchor="end" class="axis">{peak}</text>')
    parts.append(f'<text x="{left - 6}" y="{base}" text-anchor="end" class="axis">0</text>')
    return (
        f'<svg dir="ltr" class="chart" viewBox="0 0 {left + 24 * slot + 8} 206" role="img" '
        f'aria-label="{esc(t(lang, "by_hour"))}">{"".join(parts)}</svg>'
    )


def _weekday_chart(stats: Stats, lang: str) -> str:
    left, slot, bar, base, height = 8, 58, 34, 150, 128
    peak = max(stats.weekdays) or 1
    names = WEEKDAYS[lang]
    parts: List[str] = []
    for d in range(7):
        n = stats.weekdays[d]
        h = height * n / peak
        x = left + d * slot + (slot - bar) / 2
        cls = "bar-weekend" if d in WEEKEND_DAYS else "bar-ok"
        parts.append(
            f"<g><title>{esc(names[d])}: {n}</title>"
            f'<rect x="{x:.1f}" y="{base - h:.1f}" width="{bar}" height="{h:.1f}" rx="2" class="{cls}"/></g>'
            f'<text x="{left + d * slot + slot / 2:.1f}" y="{base + 18}" text-anchor="middle" '
            f'class="axis">{esc(names[d])}</text>'
        )
        if n:
            parts.append(
                f'<text x="{left + d * slot + slot / 2:.1f}" y="{base - h - 5:.1f}" text-anchor="middle" '
                f'class="axis val">{n}</text>'
            )
    parts.append(f'<line x1="{left}" y1="{base}" x2="{left + 7 * slot}" y2="{base}" class="baseline"/>')
    return (
        f'<svg dir="ltr" class="chart" viewBox="0 0 {left * 2 + 7 * slot} 176" role="img" '
        f'aria-label="{esc(t(lang, "by_weekday"))}">{"".join(parts)}</svg>'
    )


def _time(stats: Stats, lang: str) -> str:
    if stats.is_empty:
        return _section(lang, 2, "s_time", "s_time_sub", _empty(lang))
    worst = stats.worst_bad_hour
    worst_html = (
        f'<div class="stat-v">{_ltr(f"{worst:02d}:00–{worst:02d}:59")}</div>'
        f'<div class="stat-k">{_num(stats.bad_hours[worst])} ✗</div>'
        if worst is not None
        else f'<div class="stat-v small">{esc(t(lang, "worst_hour_none"))}</div>'
    )
    late_pct = round(100 * stats.ratio(stats.late_night_commits))
    legend = (
        '<div class="legend">'
        f'<span><i class="sw ok"></i>{esc(t(lang, "legend_ok"))}</span>'
        f'<span><i class="sw bad"></i>{esc(t(lang, "legend_bad"))}</span>'
        f'<span><i class="sw late"></i>{esc(t(lang, "legend_late"))}</span>'
        "</div>"
    )
    body = (
        f'<h3>{esc(t(lang, "by_hour"))}</h3>{_hour_chart(stats, lang)}{legend}'
        '<div class="split">'
        f'<div><h3>{esc(t(lang, "by_weekday"))}</h3>{_weekday_chart(stats, lang)}</div>'
        '<div class="stats-col">'
        f'<div class="stat"><div class="stat-k">{esc(t(lang, "worst_hour"))}</div>{worst_html}</div>'
        f'<div class="stat"><div class="stat-k">{esc(t(lang, "late_ratio"))}</div>'
        f'<div class="stat-v">{late_pct}%</div>'
        f'<div class="stat-k">{_num(stats.late_night_commits)} / {_num(stats.total_commits)}</div></div>'
        "</div></div>"
    )
    return _section(lang, 2, "s_time", "s_time_sub", body)


def _span_tile(lang: str, key: str, span: Span, empty_key: str) -> str:
    if span.days == 0 or span.start is None:
        value = f'<div class="stat-v small">{esc(t(lang, empty_key))}</div>'
        dates = ""
    else:
        value = f'<div class="stat-v huge">{_num(span.days)} <small>{esc(t(lang, "days_unit"))}</small></div>'
        dates = f'<div class="stat-k">{_ltr(_date(span.start))} – {_ltr(_date(span.end))}</div>'
    return f'<div class="stat tile-{key}"><div class="stat-k">{esc(t(lang, key))}</div>{value}{dates}</div>'


def _streaks(stats: Stats, lang: str) -> str:
    if stats.is_empty:
        return _section(lang, 3, "s_streaks", "s_streaks_sub", _empty(lang))
    body = (
        '<div class="split even">'
        f'{_span_tile(lang, "streak", stats.streak, "no_evidence")}'
        f'{_span_tile(lang, "gap", stats.gap, "no_gap")}'
        "</div>"
    )
    return _section(lang, 3, "s_streaks", "s_streaks_sub", body)


def _churn(stats: Stats, lang: str) -> str:
    table = _file_table(
        lang, stats.hotspots, "col_commits", lambda f: f.commits, "col_lines", lambda f: f.lines
    )
    return _section(lang, 4, "s_churn", "s_churn_sub", table)


def share_text(stats: Stats, verdict: Verdict, lang: str) -> str:
    return t(lang, "share", repo=stats.repo_name, score=stats.score, headline=verdict.headline, sentence=verdict.sentence)


def _verdict(stats: Stats, verdict: Verdict, lang: str) -> str:
    grade = stats.grade
    factors = []
    for key, weight in WEIGHTS.items():
        frac = stats.score_parts.get(key, 0.0)
        lost = weight * frac
        factors.append(
            '<div class="factor">'
            f'<div class="f-name">{esc(t(lang, "f_" + key))}</div>'
            f'<div class="meter red"><span style="width:{100 * frac:.1f}%"></span></div>'
            f'<div class="f-val" dir="ltr">−{lost:.0f} / {weight}</div>'
            "</div>"
        )
    source = t(lang, "verdict_ai" if verdict.source == "ai" else "verdict_template")
    return (
        '<section class="card verdict">'
        f'<div class="exhibit">{esc(t(lang, "s_verdict"))}</div>'
        '<div class="verdict-top">'
        f'<div class="badge">{_score_ring(stats.score, grade, 150)}'
        f'<div class="grade stamp-grade" style="color:{GRADE_COLORS[grade]};border-color:{GRADE_COLORS[grade]}">'
        f'{esc(t(lang, "grade_" + grade))}</div></div>'
        f'<div class="verdict-text"><h2 class="headline" dir="auto">{rich(verdict.headline)}</h2>'
        f'<p class="paragraph" dir="auto">{rich(verdict.paragraph)}</p>'
        f'<p class="sentence" dir="auto">{rich(verdict.sentence)}</p></div>'
        "</div>"
        f'<h3>{esc(t(lang, "breakdown"))} · {esc(t(lang, "score"))} {stats.score}/100</h3>'
        f'<div class="factors">{"".join(factors)}</div>'
        '<div class="share">'
        f'<button id="copy-btn" type="button" data-ok="{esc(t(lang, "copied"))}" '
        f'data-fail="{esc(t(lang, "copy_failed"))}">{esc(t(lang, "copy"))}</button>'
        '<span id="copy-status" role="status" aria-live="polite"></span>'
        f'<textarea id="share-text" readonly hidden dir="auto">{esc(share_text(stats, verdict, lang))}</textarea>'
        f'<p class="source">{esc(source)}</p>'
        "</div>"
        "</section>"
    )


def _footer(lang: str, generated: datetime, ai_used: bool) -> str:
    privacy = t(lang, "privacy_ai" if ai_used else "privacy")
    return (
        '<footer class="foot">'
        f'<div>{esc(t(lang, "generated"))}: {_ltr(generated.strftime("%Y-%m-%d %H:%M"))}</div>'
        f'<div>{esc(t(lang, "generated_by"))} <a href="{esc(PROJECT_URL)}" rel="noopener noreferrer">'
        f'commit-court</a> {_ltr("v" + __version__)}</div>'
        f'<div class="muted">{esc(privacy)}</div>'
        "</footer>"
    )


# --------------------------------------------------------------------------- page

CSS = """
:root{--bg:#09090d;--paper:#121219;--card:#17171f;--ink:#ece6d8;--muted:#9a9488;--line:#2b2a33;
--gold:#d4a645;--red:#e0443e;--amber:#d9a441;--late:rgba(120,110,255,.10);--weekend:#8f7bd8;
--serif:Georgia,"Times New Roman",Times,serif;--mono:ui-monospace,"Cascadia Code","SFMono-Regular",Consolas,"Liberation Mono",Menlo,monospace;
--sans:__SANS__;color-scheme:dark}
*{box-sizing:border-box}
html{background:var(--bg)}
body{margin:0;background:radial-gradient(ellipse at top,#1a1822 0%,var(--bg) 60%) fixed;color:var(--ink);
font-family:var(--sans);line-height:1.55;-webkit-font-smoothing:antialiased;padding:32px 16px 48px}
.sheet{width:100%;max-width:900px;margin:0 auto;display:flex;flex-direction:column;gap:18px}
.card{position:relative;background:linear-gradient(180deg,#1a1a23,var(--card));border:1px solid var(--line);
border-radius:14px;padding:26px 30px;box-shadow:0 10px 30px rgba(0,0,0,.35)}
h1,h2,h3{margin:0;font-weight:700}
h2{font-family:var(--heading);font-size:26px;letter-spacing:.2px}
h3{font-size:13px;text-transform:uppercase;letter-spacing:1.6px;color:var(--muted);margin:18px 0 10px;font-weight:600}
.sub{color:var(--muted);margin:4px 0 16px;font-size:14.5px}
.exhibit{font-size:12px;letter-spacing:2.4px;text-transform:uppercase;color:var(--gold);font-weight:700;margin-bottom:6px}
code{font-family:var(--mono);font-size:.9em;background:rgba(212,166,69,.10);color:#f0d38a;padding:1px 6px;border-radius:5px;
border:1px solid rgba(212,166,69,.18);word-break:break-all}
.muted{color:var(--muted)}
.empty,.clean{color:var(--muted);font-style:italic;margin:6px 0 0}
/* header */
.head{padding-top:20px;overflow:hidden;border-top:3px solid var(--gold)}
.topline{display:flex;justify-content:space-between;gap:12px;font-size:12px;letter-spacing:2px;text-transform:uppercase;
color:var(--muted);border-bottom:1px dashed var(--line);padding-bottom:12px}
.brand{color:var(--gold);font-weight:700}
.caseno span{font-family:var(--mono);color:var(--ink);letter-spacing:1px}
.stamp{position:absolute;top:58px;inset-inline-end:180px;transform:rotate(-12deg);border:3px solid var(--red);color:var(--red);
font-weight:800;letter-spacing:4px;text-transform:uppercase;padding:4px 12px;font-size:15px;opacity:.55;border-radius:4px;pointer-events:none}
.title-row{display:flex;align-items:center;justify-content:space-between;gap:20px;margin:18px 0 20px}
.people{font-family:var(--heading);font-style:italic;color:var(--muted);font-size:18px}
h1{font-family:var(--heading);font-size:44px;line-height:1.1;word-break:break-word}
.filed{color:var(--muted);font-size:13px;margin-top:6px}
.badge{display:flex;flex-direction:column;align-items:center;gap:6px;flex:none}
.ring-num{font-size:38px;font-weight:800;font-family:var(--sans)}
.ring-of{font-size:13px}
.grade{font-weight:800;text-transform:uppercase;letter-spacing:2px;font-size:13px;text-align:center}
.tiles{display:grid;grid-template-columns:1.6fr 1fr 1fr 1fr;gap:10px}
.tile{background:rgba(255,255,255,.025);border:1px solid var(--line);border-radius:10px;padding:10px 14px}
.tile .k{font-size:11px;text-transform:uppercase;letter-spacing:1.4px;color:var(--muted)}
.tile .v{font-size:20px;font-weight:700;margin-top:2px;white-space:nowrap}
.tile .v span{font-family:var(--mono);font-size:15px}
.dash{color:var(--muted)}
/* tables */
table.files{width:100%;border-collapse:collapse;font-size:14.5px}
.files th{font-size:11px;text-transform:uppercase;letter-spacing:1.3px;color:var(--muted);text-align:start;font-weight:600;
padding:0 8px 8px;border-bottom:1px solid var(--line)}
.files td{padding:9px 8px;border-bottom:1px solid rgba(255,255,255,.04);vertical-align:top}
.files .n{text-align:end;white-space:nowrap;font-variant-numeric:tabular-nums;width:1%}
.files td.n{font-weight:700}
.files .rank{width:1%;color:var(--gold);font-weight:700;text-align:center}
.files tr:first-child td.rank{color:var(--red)}
.meter{height:4px;background:rgba(255,255,255,.05);border-radius:4px;margin-top:6px;overflow:hidden}
.meter span{display:block;height:100%;background:linear-gradient(90deg,var(--gold),#f0c674);border-radius:4px}
.meter.red span{background:linear-gradient(90deg,#b8322d,var(--red))}
/* offenders */
.summary{margin:0 0 12px;font-size:16px}
.big-num{font-size:34px;font-weight:800;color:var(--red);margin-inline-end:6px;font-family:var(--heading)}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:14px}
.chip{display:inline-block;font-size:11.5px;padding:2px 9px;border-radius:999px;border:1px solid rgba(224,68,62,.35);
color:#f2a19d;background:rgba(224,68,62,.08);white-space:nowrap}
.chip.big{font-size:13px;padding:4px 11px}
.chip b{color:var(--ink);margin-inline-start:4px}
.raps{list-style:none;margin:0;padding:0;display:grid;gap:10px;counter-reset:rap}
.rap{counter-increment:rap;position:relative;background:rgba(0,0,0,.25);border:1px solid var(--line);border-inline-start:3px solid var(--red);
border-radius:8px;padding:12px 16px}
.quote{font-family:var(--mono);font-size:19px;font-weight:700;word-break:break-word}
.count{font-family:var(--sans);font-size:13px;font-weight:700;color:var(--bg);background:var(--gold);border-radius:6px;padding:1px 7px;margin-inline-start:10px;vertical-align:middle}
.rap-meta{margin-top:6px;font-size:12.5px;display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.hash{font-family:var(--mono);color:var(--gold)}
/* charts */
.chart{width:100%;height:auto;display:block;direction:ltr}
.chart .axis{fill:var(--muted);font-size:11px;font-family:var(--sans)}
.chart .axis.val{fill:var(--ink);font-weight:700}
.chart .bar-ok{fill:var(--amber)}
.chart .bar-bad{fill:var(--red)}
.chart .bar-weekend{fill:var(--weekend)}
.chart .late{fill:var(--late)}
.chart .baseline{stroke:var(--line);stroke-width:1}
.legend{display:flex;flex-wrap:wrap;gap:16px;font-size:12px;color:var(--muted);margin-top:6px}
.sw{display:inline-block;width:10px;height:10px;border-radius:2px;margin-inline-end:6px;vertical-align:-1px}
.sw.ok{background:var(--amber)}.sw.bad{background:var(--red)}.sw.late{background:rgba(120,110,255,.35)}
.split{display:grid;grid-template-columns:1.5fr 1fr;gap:22px;align-items:start}
.split.even{grid-template-columns:1fr 1fr;gap:14px}
.stats-col{display:grid;gap:12px;margin-top:18px}
.stat{background:rgba(255,255,255,.025);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.stat-k{font-size:11.5px;text-transform:uppercase;letter-spacing:1.3px;color:var(--muted)}
.stat-v{font-size:26px;font-weight:800;margin:2px 0}
.stat-v span{font-family:var(--mono);font-size:22px}
.stat-v.small{font-size:15px;font-weight:600;color:var(--muted)}
.stat-v.huge{font-size:46px;font-family:var(--heading);line-height:1.1}
.stat-v.huge small{font-size:16px;color:var(--muted);font-family:var(--sans);font-weight:600}
.tile-streak{border-top:3px solid var(--gold)}.tile-gap{border-top:3px solid #6b7280}
/* verdict */
.verdict{border:1px solid rgba(212,166,69,.45);background:radial-gradient(ellipse at top left,rgba(212,166,69,.10),transparent 55%),
linear-gradient(180deg,#1c1b22,#15151c);padding:30px}
.verdict-top{display:flex;gap:28px;align-items:center;margin-top:6px}
.stamp-grade{border:2px solid;padding:3px 10px;border-radius:4px;transform:rotate(-4deg)}
.headline{font-family:var(--heading);font-size:28px;line-height:1.25}
.paragraph{margin:10px 0;color:#d8d2c4;font-size:15.5px}
.sentence{margin:12px 0 0;font-weight:700;color:var(--gold);font-size:16.5px;border-inline-start:3px solid var(--gold);padding-inline-start:12px}
.factors{display:grid;grid-template-columns:1fr 1fr;gap:10px 26px}
.factor{display:grid;grid-template-columns:1fr auto;align-items:center;gap:2px 10px;font-size:13.5px}
.factor .meter{grid-column:1/-1;margin-top:0;height:6px}
.f-val{font-family:var(--mono);color:var(--muted);font-size:12.5px}
.share{margin-top:22px;display:flex;flex-wrap:wrap;align-items:center;gap:12px}
#copy-btn{font:inherit;font-weight:700;font-size:14px;color:var(--bg);background:var(--gold);border:0;border-radius:9px;padding:10px 18px;cursor:pointer}
#copy-btn:hover{filter:brightness(1.08)}#copy-btn:focus-visible{outline:2px solid var(--ink);outline-offset:2px}
#copy-status{color:var(--gold);font-size:13px;font-weight:600}
#share-text{width:100%;min-height:70px;background:#0e0e13;color:var(--ink);border:1px solid var(--line);border-radius:8px;padding:10px;font:inherit;font-size:13px}
.source{width:100%;margin:0;font-size:12px;color:var(--muted)}
/* footer */
.foot{text-align:center;color:var(--muted);font-size:12.5px;display:grid;gap:4px;padding-top:6px}
.foot a{color:var(--gold);text-decoration:none;font-weight:700}.foot a:hover{text-decoration:underline}
[dir=rtl] .people,[dir=rtl] h2,[dir=rtl] h1{letter-spacing:0}
[dir=rtl] .exhibit,[dir=rtl] h3,[dir=rtl] .stat-k,[dir=rtl] .tile .k,[dir=rtl] .files th,[dir=rtl] .topline,[dir=rtl] .grade{letter-spacing:0;text-transform:none}
@media (max-width:720px){
body{padding:16px 16px 32px}.card{padding:20px 18px}
h1{font-size:32px}.title-row{flex-direction:column;align-items:flex-start}
.stamp{top:52px;inset-inline-end:16px;font-size:12px}
.tiles{grid-template-columns:1fr 1fr}.split,.split.even,.factors{grid-template-columns:1fr}
.verdict-top{flex-direction:column;align-items:flex-start}.headline{font-size:23px}
.files .rank{display:none}.quote{font-size:16px}
}
@media print{body{background:var(--bg)}.card{box-shadow:none;break-inside:avoid}#copy-btn,#copy-status{display:none}}
"""

JS = """
(function(){
  var btn=document.getElementById('copy-btn'),src=document.getElementById('share-text'),out=document.getElementById('copy-status');
  if(!btn||!src)return;
  function legacy(text){
    var ta=document.createElement('textarea');ta.value=text;ta.setAttribute('readonly','');
    ta.style.position='fixed';ta.style.opacity='0';document.body.appendChild(ta);ta.select();
    var ok=false;try{ok=document.execCommand('copy');}catch(e){}
    document.body.removeChild(ta);return ok;
  }
  function done(ok){
    out.textContent=ok?btn.getAttribute('data-ok'):btn.getAttribute('data-fail');
    if(!ok){src.hidden=false;src.focus();src.select();}
  }
  btn.addEventListener('click',function(){
    var text=src.value;
    if(navigator.clipboard&&navigator.clipboard.writeText){
      navigator.clipboard.writeText(text).then(function(){done(true);},function(){done(legacy(text));});
    }else{done(legacy(text));}
  });
})();
"""

CSP = "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'"


def render_report(
    stats: Stats,
    verdict: Verdict,
    lang: str = "en",
    generated: Optional[datetime] = None,
    ai_used: bool = False,
) -> str:
    generated = generated or datetime.now()
    direction = t(lang, "dir")
    heading_font = "var(--serif)" if lang == "en" else "var(--sans)"
    css = CSS.replace("__SANS__", FONTS.get(lang, FONTS["en"])) + f":root{{--heading:{heading_font}}}"
    title = f'{t(lang, "court")} — {stats.repo_name}'
    body = "".join(
        [
            _header(stats, lang, generated),
            _defendants(stats, lang),
            _offenders(stats, lang),
            _time(stats, lang),
            _streaks(stats, lang),
            _churn(stats, lang),
            _verdict(stats, verdict, lang),
            _footer(lang, generated, ai_used),
        ]
    )
    return (
        "<!DOCTYPE html>\n"
        f'<html lang="{esc(lang)}" dir="{esc(direction)}">\n<head>\n<meta charset="utf-8">\n'
        f'<meta http-equiv="Content-Security-Policy" content="{CSP}">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<meta name="color-scheme" content="dark">\n'
        f'<meta name="generator" content="commit-court {esc(__version__)}">\n'
        f"<title>{esc(title)}</title>\n<style>{css}</style>\n</head>\n<body>\n"
        f'<main class="sheet">{body}</main>\n'
        f"<script>{JS}</script>\n</body>\n</html>\n"
    )
