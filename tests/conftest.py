"""Shared fixtures: throwaway git repositories with fully controlled history."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Dict, Optional

import pytest


def _isolated_env(date: Optional[str] = None, author: str = "Test Author") -> Dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            # Ignore the developer's own git config (signing, hooks, templates...).
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": author,
            "GIT_AUTHOR_EMAIL": "author@example.com",
            "GIT_COMMITTER_NAME": author,
            "GIT_COMMITTER_EMAIL": "author@example.com",
        }
    )
    if date:
        env["GIT_AUTHOR_DATE"] = date
        env["GIT_COMMITTER_DATE"] = date
    return env


class GitRepo:
    def __init__(self, path: Path):
        self.path = path
        self.path.mkdir(parents=True, exist_ok=True)
        self.git("init", "-q")
        self.git("checkout", "-q", "-b", "main")

    def git(self, *args: str, date: Optional[str] = None, author: str = "Test Author") -> str:
        result = subprocess.run(
            ["git", "-C", str(self.path), *args],
            env=_isolated_env(date, author),
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )
        return result.stdout

    def commit(
        self,
        message: str,
        date: str,
        files: Optional[Dict[str, str]] = None,
        author: str = "Test Author",
    ) -> None:
        """Commit ``files`` (path -> content to append) at ISO ``date``."""
        files = files or {"notes.txt": message + "\n"}
        for rel, content in files.items():
            target = self.path / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "a", encoding="utf-8", newline="\n") as fh:
                fh.write(content)
            self.git("add", "--", rel)
        self.git("commit", "-q", "--allow-empty", "-m", message, date=date, author=author)


@pytest.fixture
def make_repo(tmp_path: Path):
    counter = {"n": 0}

    def factory() -> GitRepo:
        counter["n"] += 1
        return GitRepo(tmp_path / f"repo{counter['n']}")

    return factory


@pytest.fixture(scope="session")
def sample_repo(tmp_path_factory) -> GitRepo:
    """A small repo with a known mix of good, bad and late-night commits. Read-only for tests."""
    repo = GitRepo(tmp_path_factory.mktemp("sample") / "repo")
    repo.commit("Add initial project skeleton", "2024-03-01T10:00:00+00:00", {"app.py": "a\n"})
    repo.commit("fix", "2024-03-02T02:15:00+00:00", {"app.py": "b\n"})
    repo.commit("Implement user login with session cookies", "2024-03-03T14:30:00+00:00", {"auth.py": "x\n"})
    repo.commit("asdf", "2024-03-04T02:45:00+00:00", {"app.py": "c\n"})
    repo.commit("Fix crash when config file is missing", "2024-03-05T09:00:00+00:00", {"app.py": "d\n", "config.py": "e\n"})
    repo.commit("WIP", "2024-03-15T23:30:00+00:00", {"auth.py": "y\n"})
    repo.commit("Документация: добавить раздел о установке ✨", "2024-03-16T11:00:00+00:00", {"docs/readme.md": "z\n"})
    repo.commit("<script>alert('pwned')</script>", "2024-03-17T12:00:00+00:00", {"src/tom&jerry's.txt": "q\n"})
    return repo
