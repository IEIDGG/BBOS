import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_ws.sh"


def run_git(repo, *args, check=True):
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=check,
        capture_output=True,
        text=True,
    )


def init_repo(path):
    run_git(path, "init", "-b", "main")
    run_git(path, "config", "user.email", "ci@example.test")
    run_git(path, "config", "user.name", "CI")
    run_git(path, "config", "commit.gpgsign", "false")


def commit_file(repo, relpath, content, message):
    target = Path(repo) / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    run_git(repo, "add", relpath)
    run_git(repo, "commit", "-m", message)
    return run_git(repo, "rev-parse", "HEAD").stdout.strip()


def setup_race_repos(tmp):
    remote = Path(tmp) / "remote.git"
    work = Path(tmp) / "work"
    local = Path(tmp) / "local"
    remote.mkdir()
    run_git(remote, "init", "--bare", "-b", "main")
    work.mkdir()
    run_git(work, "clone", str(remote), str(work / "repo"))
    repo = work / "repo"
    run_git(repo, "config", "user.email", "ci@example.test")
    run_git(repo, "config", "user.name", "CI")
    run_git(repo, "config", "commit.gpgsign", "false")
    before = commit_file(repo, "app.txt", "ok\n", "base")
    head = commit_file(repo, "app.txt", "ok\nnext\n", "under test")
    run_git(repo, "push", "origin", "main")
    later = commit_file(repo, "app.txt", "ok\nnext\nlater\n", "newer main")
    run_git(repo, "push", "origin", "main")
    run_git(local.parent, "clone", "--branch", "main", str(remote), str(local))
    run_git(local, "checkout", "--detach", head)
    return local, before, head, later


class CheckWsTests(unittest.TestCase):
    def test_shallow_fetch_of_newer_main_loses_merge_base(self):
        with tempfile.TemporaryDirectory() as tmp:
            local, _before, _head, _later = setup_race_repos(tmp)
            fetch = run_git(local, "fetch", "origin", "main", "--depth=1", check=False)
            self.assertEqual(fetch.returncode, 0, fetch.stderr)
            diff = run_git(local, "diff", "--check", "origin/main...HEAD", check=False)
            self.assertNotEqual(diff.returncode, 0)
            self.assertIn("merge base", (diff.stderr + diff.stdout).lower())

    def test_script_survives_shallow_newer_main(self):
        with tempfile.TemporaryDirectory() as tmp:
            local, before, head, _later = setup_race_repos(tmp)
            run_git(local, "fetch", "origin", "main", "--depth=1")
            result = subprocess.run(
                ["bash", str(SCRIPT), before],
                cwd=local,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn(head[:7], result.stdout)
            self.assertIn(before[:7], result.stdout)

    def test_script_flags_trailing_whitespace(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            init_repo(repo)
            before = commit_file(repo, "app.txt", "ok\n", "base")
            commit_file(repo, "app.txt", "ok \n", "space")
            result = subprocess.run(
                ["bash", str(SCRIPT), before],
                cwd=repo,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("trailing whitespace", result.stdout + result.stderr)

    def test_script_falls_back_when_base_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            init_repo(repo)
            commit_file(repo, "app.txt", "ok\n", "base")
            commit_file(repo, "app.txt", "ok\nnext\n", "head")
            result = subprocess.run(
                ["bash", str(SCRIPT), "0000000000000000000000000000000000000000"],
                cwd=repo,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("fallback", result.stdout.lower())


if __name__ == "__main__":
    unittest.main()
