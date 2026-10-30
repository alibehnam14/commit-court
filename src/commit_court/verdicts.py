"""The judge: built-in template verdicts, plus an optional Claude-written one.

Template verdicts are picked deterministically: the stats decide the primary
"crime", and a checksum of the stats picks one of that crime's rulings, so the
same repo always gets the same verdict.
"""

from __future__ import annotations

import json
import os
import re
import zlib
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

from commit_court.analyze import WEIGHTS, Stats, ai_payload

DEFAULT_MODEL = "claude-haiku-5-5"

# Each ruling is (headline, paragraph, sentence). Placeholders are filled from _facts().
Ruling = Tuple[str, str, str]

TEMPLATES: Dict[str, Dict[str, List[Ruling]]] = {
    "en": {
        "bad_messages": [
            (
                "Guilty of chronic `{top_bad}` commits.",
                "The court reviewed {total} commits and found {bad} of them ({bad_pct}%) to be messages no "
                "future maintainer could love. Exhibit A, `{top_bad}`, appears {top_bad_count} times. The "
                "defendant clearly believes git log is a diary written in a language only they speak. The "
                "jury needed a single word to decide, which seems fitting.",
                "Sentence: {months} months of writing proper commit messages, under supervision.",
            ),
            (
                "Guilty of commit-message vandalism.",
                "Witnesses describe a history littered with `{top_bad}`, keyboard mashes and one-word "
                "confessions. {bad} of {total} commits offer the reader nothing but vibes. git blame has "
                "been placed in witness protection for its own safety.",
                "Sentence: {hours} hours of community service rewriting the changelog by hand.",
            ),
        ],
        "fixes": [
            (
                "Guilty of fixing the fixes.",
                "{fix_pct}% of all commits in this case are fixes, patches, reverts or oopses. The "
                "favourite crime scene is `{top_file}`, revisited {top_file_fixes} times: an arsonist "
                "volunteering at the fire department. The court admires the persistence, if not the aim.",
                "Sentence: {months} months of writing the test before the hotfix.",
            ),
            (
                "Guilty of operating an unlicensed bug farm.",
                "Bugs were not merely found here; they were cultivated. With {fix_pct}% of commits spent "
                "cleaning up after earlier commits, this repository is less a codebase and more a "
                "crime-scene cleaning service. `{top_file}` has requested a restraining order.",
                "Sentence: {months} months of probation and mandatory code review for every patch.",
            ),
        ],
        "hotspots": [
            (
                "Guilty of building a load-bearing file.",
                "The evidence points to `{top_file}`, a single file carrying the weight of the entire "
                "operation. {hot_pct}% of all changes pile onto the busiest tenth of the codebase. When "
                "this file sneezes, production catches a cold.",
                "Sentence: {months} months of hard labour splitting `{top_file}` into modules.",
            ),
            (
                "Guilty of hoarding changes in `{top_file}`.",
                "Every road in this repository leads to `{top_file}`. The rest of the code gathers dust "
                "in the evidence locker while one file absorbs all the edits, all the bugs and all the "
                "blame. The court suspects merge conflicts live there rent-free.",
                "Sentence: {months} months of refactoring, with weekly visits to the parole officer.",
            ),
        ],
        "late_night": [
            (
                "Guilty of committing under cover of darkness.",
                "{late_pct}% of commits were filed between 23:00 and 05:00, when only raccoons and on-call "
                "engineers are awake. The peak hour for bad behaviour was {worst_hour}. The court notes "
                "that nothing good has ever been pushed at 3 a.m.",
                "Sentence: a strict {months}-month curfew. Laptops closed by 23:00.",
            ),
            (
                "Guilty of nocturnal coding with intent to deploy.",
                "The timestamps don't lie: {late_pct}% of this history was written in the dead of night. "
                "Coffee was an accomplice. Sleep was the victim. Prime suspect hour: {worst_hour}.",
                "Sentence: {months} months of mandatory eight-hour nights, enforced by the bailiff.",
            ),
        ],
        "weekend": [
            (
                "Guilty of trespassing on weekends.",
                "{weekend_pct}% of all commits were made on a Saturday or Sunday. The court reminds the "
                "defendant that weekends are for touching grass, not touching production. Family "
                "members have filed a missing-persons report.",
                "Sentence: {months} consecutive weekends offline, no appeals.",
            ),
            (
                "Guilty of weekend-warrior behaviour.",
                "While the rest of the world was at brunch, this repository kept growing. {weekend_pct}% "
                "of commits landed on weekends: a cry for help disguised as productivity.",
                "Sentence: {months} months of hobbies that do not involve a terminal.",
            ),
        ],
        "ghosting": [
            (
                "Guilty of ghosting the repository.",
                "After a promising {streak_days}-day streak, the defendant vanished for {gap_days} days "
                "without a single commit. No note, no README update, nothing. The issue tracker lit a "
                "candle every night.",
                "Sentence: {months} months of daily check-ins, even if it's just fixing a typo.",
            ),
            (
                "Guilty of abandonment in the first degree.",
                "The record shows a silence of {gap_days} days: long enough for dependencies to rot and "
                "for three new JavaScript frameworks to be released. The defendant claims they were "
                "'busy'. The court is unconvinced.",
                "Sentence: {months} months of maintenance duty and a heartfelt apology to the CI server.",
            ),
        ],
        "clean": [
            (
                "Not guilty. The court is suspicious, but impressed.",
                "After reviewing {total} commits the prosecution found no meaningful crime: messages are "
                "readable, fixes are reasonable and nobody was pushing at 4 a.m. Either this team is "
                "genuinely disciplined or they squash-merged the evidence.",
                "Sentence: none. Case dismissed. Keep writing those messages.",
            ),
            (
                "Acquitted on all counts.",
                "The jury searched hard for a `wip` or an `asdf` and came back empty-handed. With a "
                "health score of {score}/100, this repository is the defendant every lawyer dreams of: "
                "boring, predictable and well documented.",
                "Sentence: 0 months. Free to go, with a commendation from the bench.",
            ),
        ],
        "dismissed": [
            (
                "Case dismissed for lack of evidence.",
                "The court searched the record and found no commits to judge. Either this repository is "
                "brand new or the defendant has committed the perfect crime: writing no code at all.",
                "Sentence: go make your first commit, and give it a good message.",
            ),
        ],
    },
    "fa": {
        "bad_messages": [
            (
                "مجرم به ارتکاب مزمن کامیت‌های `{top_bad}`.",
                "دادگاه {total} کامیت را بررسی کرد و {bad} مورد ({bad_pct}٪) را پیام‌هایی یافت که هیچ "
                "نگه‌دارنده‌ای در آینده دوستشان نخواهد داشت. مدرک شماره‌ی یک، `{top_bad}`، {top_bad_count} بار "
                "تکرار شده است. متهم ظاهراً گمان می‌کند git log دفتر خاطراتی است به زبانی که فقط خودش "
                "می‌فهمد. هیئت منصفه هم با یک کلمه رأی داد، که کاملاً مناسب بود.",
                "حکم: {months} ماه نوشتن پیام کامیت درست و حسابی، تحت نظارت.",
            ),
            (
                "مجرم به تخریب پیام‌های کامیت.",
                "شاهدان از تاریخچه‌ای پر از `{top_bad}`، کوبیدن بی‌هدف روی کیبورد و اعترافات تک‌کلمه‌ای خبر "
                "می‌دهند. {bad} کامیت از {total} کامیت چیزی جز حس‌وحال به خواننده نمی‌دهند. git blame برای "
                "حفظ جانش تحت حمایت از شهود قرار گرفته است.",
                "حکم: {hours} ساعت خدمات عمومی؛ بازنویسی دستی changelog.",
            ),
        ],
        "fixes": [
            (
                "مجرم به فیکس کردن فیکس‌ها.",
                "{fix_pct}٪ از کامیت‌های این پرونده فیکس، پچ، revert یا «اوپس» هستند. صحنه‌ی جرم محبوب "
                "متهم `{top_file}` است که {top_file_fixes} بار به آن سر زده؛ مثل آتش‌افروزی که داوطلب "
                "آتش‌نشانی شده باشد. دادگاه پشتکار را تحسین می‌کند، نه نشانه‌گیری را.",
                "حکم: {months} ماه نوشتن تست، پیش از هات‌فیکس.",
            ),
            (
                "مجرم به راه‌اندازی مزرعه‌ی غیرمجاز باگ.",
                "باگ‌ها اینجا فقط پیدا نشدند؛ پرورش داده شدند. با {fix_pct}٪ کامیت‌هایی که صرف جمع‌وجور "
                "کردن کامیت‌های قبلی شده، این مخزن بیشتر شبیه شرکت نظافت صحنه‌ی جرم است تا یک کدبیس. "
                "`{top_file}` درخواست قرار منع تعقیب داده است.",
                "حکم: {months} ماه تعلیق مراقبتی و بازبینی اجباری کد برای هر پچ.",
            ),
        ],
        "hotspots": [
            (
                "مجرم به ساختن یک فایل باربر.",
                "شواهد به `{top_file}` اشاره دارد: فایلی که بار کل عملیات را به دوش می‌کشد. {hot_pct}٪ از کل "
                "تغییرات روی شلوغ‌ترین ده درصد کدبیس انباشته شده است. وقتی این فایل عطسه کند، "
                "پروداکشن سرما می‌خورد.",
                "حکم: {months} ماه اعمال شاقه؛ شکستن `{top_file}` به ماژول‌های کوچک‌تر.",
            ),
            (
                "مجرم به احتکار تغییرات در `{top_file}`.",
                "همه‌ی راه‌های این مخزن به `{top_file}` ختم می‌شود. بقیه‌ی کد در انبار مدارک خاک می‌خورد، "
                "در حالی که یک فایل همه‌ی ویرایش‌ها، همه‌ی باگ‌ها و همه‌ی تقصیرها را جذب می‌کند. دادگاه "
                "مظنون است که مرج‌کانفلیکت‌ها آنجا مجانی زندگی می‌کنند.",
                "حکم: {months} ماه ریفکتور، با حضور هفتگی نزد افسر آزادی مشروط.",
            ),
        ],
        "late_night": [
            (
                "مجرم به کامیت کردن در تاریکی شب.",
                "{late_pct}٪ از کامیت‌ها بین ساعت 23:00 تا 05:00 ثبت شده‌اند؛ ساعاتی که فقط راکون‌ها و "
                "مهندس‌های آنکال بیدارند. ساعت اوج رفتار بد {worst_hour} بوده است. دادگاه یادآوری می‌کند "
                "که هیچ چیز خوبی ساعت سه بامداد push نشده است.",
                "حکم: {months} ماه منع رفت‌وآمد شبانه. لپ‌تاپ تا ساعت 23:00 بسته.",
            ),
            (
                "مجرم به کدنویسی شبانه با قصد دیپلوی.",
                "مهرهای زمانی دروغ نمی‌گویند: {late_pct}٪ از این تاریخچه در دل شب نوشته شده است. قهوه "
                "شریک جرم بود و خواب قربانی. ساعت مظنون اصلی: {worst_hour}.",
                "حکم: {months} ماه هشت ساعت خواب اجباری، با نظارت مأمور دادگاه.",
            ),
        ],
        "weekend": [
            (
                "مجرم به تجاوز به حریم آخر هفته.",
                "{weekend_pct}٪ از کامیت‌ها در آخر هفته ثبت شده‌اند. دادگاه به متهم یادآوری می‌کند که آخر "
                "هفته برای قدم زدن در طبیعت است، نه دست زدن به پروداکشن. خانواده‌ی متهم گزارش فرد گمشده "
                "داده‌اند.",
                "حکم: {months} آخر هفته‌ی پیاپی آفلاین، بدون حق تجدیدنظر.",
            ),
            (
                "مجرم به رفتار جنگجوی آخر هفته.",
                "در حالی که بقیه‌ی دنیا مشغول صبحانه‌ی مفصل بودند، این مخزن رشد می‌کرد. {weekend_pct}٪ از "
                "کامیت‌ها در آخر هفته فرود آمدند؛ فریادی برای کمک در لباس بهره‌وری.",
                "حکم: {months} ماه سرگرمی‌هایی که هیچ ربطی به ترمینال ندارند.",
            ),
        ],
        "ghosting": [
            (
                "مجرم به غیب شدن از مخزن.",
                "پس از یک رکورد امیدوارکننده‌ی {streak_days} روزه، متهم {gap_days} روز بدون حتی یک کامیت "
                "ناپدید شد. نه یادداشتی، نه به‌روزرسانی README، هیچ. ایشوها هر شب برایش شمع روشن کردند.",
                "حکم: {months} ماه حضور روزانه، حتی اگر فقط برای اصلاح یک غلط تایپی باشد.",
            ),
            (
                "مجرم به رها کردن عمدی مخزن.",
                "دادگاه در پرونده سکوتی {gap_days} روزه یافته است؛ آن‌قدر طولانی که وابستگی‌ها بپوسند و سه "
                "فریم‌ورک جاوااسکریپت جدید منتشر شود. متهم ادعا می‌کند «سرش شلوغ بوده». دادگاه قانع نشد.",
                "حکم: {months} ماه خدمت نگه‌داری و یک عذرخواهی صادقانه از سرور CI.",
            ),
        ],
        "clean": [
            (
                "بی‌گناه. دادگاه مشکوک است، اما تحت تأثیر قرار گرفته.",
                "پس از بررسی {total} کامیت، دادستان جرم قابل‌توجهی پیدا نکرد: پیام‌ها خوانا هستند، فیکس‌ها "
                "معقول‌اند و کسی ساعت چهار صبح push نمی‌کرد. یا این تیم واقعاً منضبط است، یا مدارک را "
                "squash-merge کرده‌اند.",
                "حکم: هیچ. پرونده مختومه است؛ به نوشتن همین پیام‌ها ادامه دهید.",
            ),
            (
                "تبرئه از همه‌ی اتهامات.",
                "هیئت منصفه با دقت دنبال یک `wip` یا `asdf` گشت و دست خالی برگشت. با نمره‌ی سلامت "
                "{score}/100، این مخزن همان متهمی است که هر وکیلی آرزویش را دارد: کسل‌کننده، قابل "
                "پیش‌بینی و مستند.",
                "حکم: صفر ماه. آزادید، با تقدیرنامه از طرف قاضی.",
            ),
        ],
        "dismissed": [
            (
                "پرونده به دلیل فقدان مدرک مختومه شد.",
                "دادگاه پرونده را گشت و هیچ کامیتی برای قضاوت پیدا نکرد. یا این مخزن تازه متولد شده، یا "
                "متهم مرتکب جرم کامل شده است: اصلاً کدی ننوشته.",
                "حکم: بروید اولین کامیتتان را بزنید؛ و پیامش را خوب بنویسید.",
            ),
        ],
    },
}


@dataclass
class Verdict:
    crime: str
    headline: str
    paragraph: str
    sentence: str
    source: str = "template"  # or "ai"


def _pct(x: float) -> int:
    return int(round(x * 100))


def _safe(text: str, limit: int = 60) -> str:
    # Backticks delimit inline code in rulings; a repo-supplied backtick must not break that.
    text = text.replace("`", "'").replace("\n", " ").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def crime_scores(stats: Stats) -> Dict[str, float]:
    """How strongly each crime applies, 0-1. The largest one becomes the charge."""
    scores = dict(stats.score_parts)
    scores["weekend"] = max(0.0, min(1.0, (stats.ratio(stats.weekend_commits) - 0.35) / 0.4))
    scores["ghosting"] = max(0.0, min(1.0, (stats.gap.days - 45) / 180))
    return scores


def pick_crime(stats: Stats) -> str:
    if stats.is_empty:
        return "dismissed"
    scores = crime_scores(stats)
    # Weigh score-driving crimes by how many points they cost, so the charge matches the score.
    weighted = {k: v * WEIGHTS.get(k, 15) for k, v in scores.items()}
    crime = max(sorted(weighted), key=lambda k: weighted[k])
    return crime if weighted[crime] >= 4 else "clean"


def _facts(stats: Stats) -> Dict[str, object]:
    # The most repeated bad message makes the best exhibit.
    top_bad = max(stats.worst_messages, key=lambda b: (b.count, b.severity)) if stats.worst_messages else None
    suspect = stats.defendants[0] if stats.defendants else (stats.hotspots[0] if stats.hotspots else None)
    hotspot = stats.hotspots[0] if stats.hotspots else None
    worst = stats.worst_bad_hour
    if worst is None:
        worst = max(range(24), key=lambda h: stats.hours[h]) if stats.total_commits else 0
    months = max(1, int(round((100 - stats.score) / 8)))
    return {
        "total": stats.total_commits,
        "bad": stats.bad_commits,
        "bad_pct": _pct(stats.ratio(stats.bad_commits)),
        "top_bad": _safe(top_bad.subject, 30) if top_bad else "fix",
        "top_bad_count": top_bad.count if top_bad else 0,
        "fix_pct": _pct(stats.ratio(stats.fix_commits)),
        "late_pct": _pct(stats.ratio(stats.late_night_commits)),
        "weekend_pct": _pct(stats.ratio(stats.weekend_commits)),
        "hot_pct": _pct(_top_decile_share(stats)),
        "top_file": _safe(suspect.path) if suspect else "main.py",
        "top_file_fixes": suspect.fixes if suspect else 0,
        "hot_file": _safe(hotspot.path) if hotspot else "main.py",
        "worst_hour": f"{worst:02d}:00",
        "gap_days": stats.gap.days,
        "streak_days": stats.streak.days,
        "score": stats.score,
        "months": months,
        "hours": months * 20,
    }


def _top_decile_share(stats: Stats) -> float:
    # Recover the raw share from the normalized concentration for display purposes.
    n = stats.files_touched
    if n <= 1:
        return 1.0 if n == 1 else 0.0
    k = max(1, -(-n // 10))
    baseline = k / n
    return stats.concentration * (1 - baseline) + baseline


def template_verdict(stats: Stats, lang: str = "en") -> Verdict:
    crime = pick_crime(stats)
    rulings = TEMPLATES.get(lang, TEMPLATES["en"])[crime]
    seed = f"{stats.total_commits}:{stats.bad_commits}:{stats.fix_commits}:{stats.late_night_commits}"
    headline, paragraph, sentence = rulings[zlib.crc32(seed.encode()) % len(rulings)]
    facts = _facts(stats)
    if crime == "hotspots":
        facts["top_file"] = facts["hot_file"]
    return Verdict(
        crime=crime,
        headline=headline.format(**facts),
        paragraph=paragraph.format(**facts),
        sentence=sentence.format(**facts),
    )


# --------------------------------------------------------------------------- AI judge

SYSTEM_PROMPT = (
    "You are the presiding judge of Commit Court, a comedic courtroom that puts git repositories on "
    "trial. You write short, witty, good-natured verdicts. Roast habits, never people. Base every "
    "claim strictly on the statistics provided; do not invent numbers, file names or people."
)

LANG_NAMES = {"en": "English", "fa": "Persian (Farsi)"}


def _ai_prompt(payload: dict, lang: str) -> str:
    return (
        "Here are aggregated statistics about a git repository's history, as JSON:\n\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        f"Write the court's verdict in {LANG_NAMES.get(lang, 'English')}. Reply with exactly three "
        "lines and nothing else. Keep the labels HEADLINE, VERDICT and SENTENCE in English:\n"
        "HEADLINE: <one sentence, like 'Guilty of chronic `fix` commits.'>\n"
        "VERDICT: <a witty 2-4 sentence paragraph citing the stats>\n"
        "SENTENCE: <a funny punishment, like 'Sentence: 3 months of writing proper messages.'>\n"
        "Wrap commit messages in backticks."
    )


_LINE_RE = re.compile(
    r"^[\s*_#>-]*(HEADLINE|VERDICT|SENTENCE)[\s*_]*[:：][\s*_]*(.+?)\s*$", re.IGNORECASE
)


def parse_ai_reply(text: str) -> Optional[Dict[str, str]]:
    found: Dict[str, str] = {}
    for line in text.splitlines():
        m = _LINE_RE.match(line)
        if m:
            found.setdefault(m.group(1).upper(), m.group(2))
    if {"HEADLINE", "VERDICT", "SENTENCE"} <= found.keys():
        return found
    return None


def ai_verdict(
    stats: Stats,
    lang: str = "en",
    model: Optional[str] = None,
    log: Callable[[str], None] = print,
) -> Optional[Verdict]:
    """Ask Claude for a verdict. Returns None (caller falls back to templates) on any problem."""
    if stats.is_empty:
        return None
    try:
        import anthropic
    except ImportError:
        log("AI verdict skipped: the 'anthropic' package is not installed (pip install 'commit-court[ai]').")
        return None

    model = model or os.environ.get("COMMIT_COURT_MODEL") or DEFAULT_MODEL
    try:
        client = anthropic.Anthropic(timeout=45.0, max_retries=1)
        response = client.messages.create(
            model=model,
            max_tokens=2000,
            output_config={"effort": "low"},
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": _ai_prompt(ai_payload(stats), lang)}],
        )
    except anthropic.AuthenticationError:
        log("AI verdict skipped: the API key was rejected. Using a template verdict.")
        return None
    except anthropic.RateLimitError:
        log("AI verdict skipped: rate limited. Using a template verdict.")
        return None
    except anthropic.APIStatusError as exc:
        log(f"AI verdict skipped: API error {exc.status_code}. Using a template verdict.")
        return None
    except anthropic.APIConnectionError:
        log("AI verdict skipped: could not reach the API (offline?). Using a template verdict.")
        return None
    except Exception as exc:  # never let the optional AI path break the report
        log(f"AI verdict skipped: {type(exc).__name__}. Using a template verdict.")
        return None

    if response.stop_reason == "refusal":
        log("AI verdict skipped: the model declined. Using a template verdict.")
        return None
    text = "".join(getattr(block, "text", "") for block in response.content if block.type == "text")
    parsed = parse_ai_reply(text)
    if parsed is None:
        log("AI verdict skipped: unexpected reply format. Using a template verdict.")
        return None
    return Verdict(
        crime=pick_crime(stats),
        headline=parsed["HEADLINE"][:300],
        paragraph=parsed["VERDICT"][:1200],
        sentence=parsed["SENTENCE"][:300],
        source="ai",
    )
