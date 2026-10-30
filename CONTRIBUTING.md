# Contributing to commit-court

Thanks for wanting to help the court! Contributions of every size are welcome: typo fixes, new
rulings, translations, new exhibits, bug reports.

## Development setup

```bash
git clone https://github.com/your-username/commit-court.git
cd commit-court
python -m venv .venv
. .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest
```

Regenerate the sample reports after any visual change:

```bash
python scripts/make_demo_repo.py --open
```

## Ground rules

- **Standard library only** in `src/commit_court/`. The optional `anthropic` import lives behind `--ai`.
- **Python 3.9+.** CI runs 3.9 through 3.13. Avoid `match`, `X | Y` at runtime, and other newer syntax.
- **Escape everything.** Any text that comes from a repository (messages, names, paths) or from the
  AI must go through `render.esc()` / `render.rich()`. Add a test if you add a new field.
- **No network in the report.** No CDNs, web fonts, images from URLs or analytics. The CSP enforces this.
- **Privacy.** Never widen what `analyze.ai_payload()` sends without discussing it in an issue first.

## Adding a ruling or a language

- Rulings live in `src/commit_court/verdicts.py` (`TEMPLATES`). Each crime needs the same number of
  rulings in every language; tests check this.
- UI strings live in `src/commit_court/i18n.py`. Every language must define exactly the same keys.
- New language? Add it to `LANGS`, `STRINGS`, `WEEKDAYS`, `FONTS`, `render.EXHIBIT_LETTERS` and `TEMPLATES`.

## Pull requests

1. Fork and create a branch.
2. Add or update tests in `tests/`.
3. Run `pytest`.
4. Describe what changed and, for visual changes, attach a screenshot.

Be kind in reviews. The court roasts commits, not people.
