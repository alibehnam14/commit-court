import pytest

from commit_court.gitlog import GitError, has_commits, iter_commits, parse_date, repo_root


def test_reads_all_commits_newest_first(sample_repo):
    commits = list(iter_commits(str(sample_repo.path)))
    assert len(commits) == 8
    assert commits[0].subject == "<script>alert('pwned')</script>"
    assert commits[-1].subject == "Add initial project skeleton"
    assert commits[-1].date.hour == 10


def test_numstat_paths_and_counts(sample_repo):
    commits = {c.subject: c for c in iter_commits(str(sample_repo.path))}
    fix = commits["Fix crash when config file is missing"]
    assert sorted(f.path for f in fix.files) == ["app.py", "config.py"]
    assert all(f.added == 1 and f.deleted == 0 for f in fix.files)


def test_unicode_messages_survive(sample_repo):
    subjects = [c.subject for c in iter_commits(str(sample_repo.path))]
    assert "Документация: добавить раздел о установке ✨" in subjects


def test_merge_commits_excluded_by_default(make_repo):
    repo = make_repo()
    repo.commit("Base commit for merge test", "2024-01-01T10:00:00+00:00")
    repo.git("checkout", "-q", "-b", "feature")
    repo.commit("Feature work on a branch", "2024-01-02T10:00:00+00:00", {"f.txt": "f\n"})
    repo.git("checkout", "-q", "main")
    repo.commit("Mainline work meanwhile", "2024-01-03T10:00:00+00:00", {"m.txt": "m\n"})
    repo.git("merge", "-q", "--no-ff", "-m", "Merge branch feature", "feature", date="2024-01-04T10:00:00+00:00")

    default = list(iter_commits(str(repo.path)))
    assert len(default) == 3
    assert not any(c.is_merge for c in default)

    with_merges = list(iter_commits(str(repo.path), include_merges=True))
    assert len(with_merges) == 4
    assert sum(c.is_merge for c in with_merges) == 1


def test_since_and_author_filters(make_repo):
    repo = make_repo()
    repo.commit("Old work by alice", "2023-01-01T10:00:00+00:00", author="Alice")
    repo.commit("New work by bob", "2024-06-01T10:00:00+00:00", author="Bob")
    repo.commit("New work by alice", "2024-06-02T10:00:00+00:00", author="Alice")
    assert [c.subject for c in iter_commits(str(repo.path), since="2024-01-01")] == [
        "New work by alice",
        "New work by bob",
    ]
    assert [c.subject for c in iter_commits(str(repo.path), author="Alice")] == [
        "New work by alice",
        "Old work by alice",
    ]


def test_empty_repo_yields_nothing(make_repo):
    repo = make_repo()
    assert not has_commits(str(repo.path))
    assert list(iter_commits(str(repo.path))) == []


def test_non_git_directory_raises_friendly_error(tmp_path):
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    with pytest.raises(GitError, match="not inside a git repository"):
        repo_root(str(plain))


def test_missing_directory_raises(tmp_path):
    with pytest.raises(GitError, match="not a directory"):
        repo_root(str(tmp_path / "nope"))


def test_stopping_early_does_not_hang(sample_repo):
    gen = iter_commits(str(sample_repo.path))
    first = next(gen)
    gen.close()
    assert first.subject


def test_parse_date_accepts_z_suffix():
    assert parse_date("2024-01-01T03:00:00Z").utcoffset().total_seconds() == 0
