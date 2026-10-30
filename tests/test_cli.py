import pytest

from commit_court import __version__
from commit_court.cli import main


def test_cli_writes_report(sample_repo, tmp_path, capsys):
    out = tmp_path / "report.html"
    code = main([str(sample_repo.path), "--out", str(out), "--no-open"])
    assert code == 0
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "Commit Court" in text
    assert "Health score" in capsys.readouterr().out


def test_cli_persian(sample_repo, tmp_path):
    out = tmp_path / "fa" / "report.html"  # parent dir is created on demand
    assert main([str(sample_repo.path), "--out", str(out), "--lang", "fa", "--no-open"]) == 0
    assert 'dir="rtl"' in out.read_text(encoding="utf-8")


def test_cli_filters(sample_repo, tmp_path, capsys):
    out = tmp_path / "r.html"
    assert main([str(sample_repo.path), "--out", str(out), "--no-open", "--since", "2024-03-15"]) == 0
    assert "Commits reviewed : 3" in capsys.readouterr().out
    assert main([str(sample_repo.path), "--out", str(out), "--no-open", "--author", "Nobody At All"]) == 0
    assert "No commits found" in capsys.readouterr().out


def test_cli_rejects_option_like_values(sample_repo, tmp_path):
    assert main([str(sample_repo.path), "--out", str(tmp_path / "r.html"), "--no-open", "--since=--all"]) == 2


def test_cli_non_git_dir(tmp_path, capsys):
    plain = tmp_path / "plain"
    plain.mkdir()
    assert main([str(plain), "--no-open", "--out", str(tmp_path / "x.html")]) == 2
    assert "not inside a git repository" in capsys.readouterr().err


def test_cli_empty_repo(make_repo, tmp_path):
    repo = make_repo()
    out = tmp_path / "empty.html"
    assert main([str(repo.path), "--out", str(out), "--no-open"]) == 0
    assert "Case dismissed" in out.read_text(encoding="utf-8")


def test_cli_ai_without_key_falls_back(sample_repo, tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    out = tmp_path / "ai.html"
    assert main([str(sample_repo.path), "--out", str(out), "--no-open", "--ai"]) == 0
    assert "ANTHROPIC_API_KEY is not set" in capsys.readouterr().out
    assert "standard rulings" in out.read_text(encoding="utf-8")


def test_cli_no_ai_overrides_ai(sample_repo, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-used")
    out = tmp_path / "noai.html"
    assert main([str(sample_repo.path), "--out", str(out), "--no-open", "--ai", "--no-ai"]) == 0
    assert "Privacy notice" not in capsys.readouterr().out


def test_cli_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out
