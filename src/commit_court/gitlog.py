"""Stream commits out of ``git log`` without loading the whole history into memory.

Each commit header is introduced by an ASCII record separator (0x1E) and its
fields are split by a unit separator (0x1F). Neither byte appears in normal
commit subjects, so parsing stays unambiguous even for unicode or punctuation-
heavy messages. ``--numstat`` lines follow each header.
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterator, List, Optional

RS = "\x1e"
US = "\x1f"
LOG_FORMAT = RS + US.join(["%H", "%aI", "%an", "%P", "%s"])


class GitError(Exception):
    """A friendly, user-facing problem talking to git."""


@dataclass
class FileChange:
    path: str
    added: int
    deleted: int


@dataclass
class Commit:
    hash: str
    date: datetime  # author date, in the author's own timezone
    author: str
    subject: str
    parents: int
    files: List[FileChange] = field(default_factory=list)

    @property
    def is_merge(self) -> bool:
        return self.parents > 1


def _git_cmd(path: str, *args: str) -> List[str]:
    return [
        "git",
        "-C",
        str(path),
        "-c",
        "core.quotepath=off",
        "-c",
        "i18n.logOutputEncoding=UTF-8",
        *args,
    ]


def _run(path: str, *args: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            _git_cmd(path, *args),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError:
        raise GitError("git is not installed or not on your PATH.") from None


def repo_root(path: str) -> str:
    """Return the top-level directory of the repository containing ``path``."""
    if not os.path.isdir(path):
        raise GitError(f"'{path}' is not a directory.")
    if shutil.which("git") is None:
        raise GitError("git is not installed or not on your PATH.")
    result = _run(path, "rev-parse", "--show-toplevel")
    if result.returncode != 0:
        raise GitError(
            f"'{os.path.abspath(path)}' is not inside a git repository. "
            "Run commit-court from a repo, or pass the repo path."
        )
    return result.stdout.strip()


def has_commits(path: str) -> bool:
    return _run(path, "rev-parse", "--verify", "--quiet", "HEAD").returncode == 0


def parse_date(value: str) -> datetime:
    # Python 3.9/3.10 fromisoformat() does not accept a trailing "Z".
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


def _parse_numstat(line: str) -> Optional[FileChange]:
    parts = line.split("\t", 2)
    if len(parts) != 3:
        return None
    added, deleted, path = parts
    # Binary files report "-" for both counts.
    return FileChange(
        path=path,
        added=int(added) if added.isdigit() else 0,
        deleted=int(deleted) if deleted.isdigit() else 0,
    )


def _parse_header(line: str) -> Optional[Commit]:
    fields = line[len(RS):].split(US, 4)
    if len(fields) != 5:
        return None
    sha, date, author, parents, subject = fields
    try:
        when = parse_date(date)
    except ValueError:
        return None
    return Commit(
        hash=sha,
        date=when,
        author=author,
        subject=subject,
        parents=len(parents.split()),
    )


def iter_commits(
    path: str,
    since: Optional[str] = None,
    author: Optional[str] = None,
    include_merges: bool = False,
) -> Iterator[Commit]:
    """Yield commits newest-first, streaming ``git log`` line by line."""
    if not has_commits(path):
        return

    args = ["log", "--no-color", "--no-renames", "--numstat", f"--format={LOG_FORMAT}"]
    if not include_merges:
        args.append("--no-merges")
    if since:
        args.append(f"--since={since}")
    if author:
        args.append(f"--author={author}")

    # stderr goes to a temp file so a chatty git can never fill a pipe and deadlock.
    with tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(_git_cmd(path, *args), stdout=subprocess.PIPE, stderr=err)
        finished = False
        try:
            assert proc.stdout is not None
            stream = io.TextIOWrapper(proc.stdout, encoding="utf-8", errors="replace", newline="\n")
            current: Optional[Commit] = None
            for raw in stream:
                line = raw.rstrip("\n")
                if line.startswith(RS):
                    if current is not None:
                        yield current
                    current = _parse_header(line)
                elif line and current is not None:
                    change = _parse_numstat(line)
                    if change is not None:
                        current.files.append(change)
            if current is not None:
                yield current
            finished = True
        finally:
            if not finished:
                proc.kill()
            returncode = proc.wait()
        if returncode != 0:
            err.seek(0)
            message = err.read().decode("utf-8", "replace").strip()
            raise GitError(f"git log failed: {message or 'exit code ' + str(returncode)}")
