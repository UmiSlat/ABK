"""Exercise private-source credentials and SUSFS pins with real local Git."""
import base64
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[2]
CHECKOUT = ROOT / ".github/scripts/checkout-custom-source.sh"
WORKFLOW = ROOT / ".github/workflows/build.yml"


@unittest.skipUnless(os.name != "nt" and shutil.which("git") and shutil.which("bash"), "requires POSIX Git and Bash")
class SourceCheckoutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.remote = self.root / "remote"
        self.real_git = shutil.which("git")
        self.config = self.root / "global.gitconfig"
        self.config.write_text('[user]\n\tname = Checkout test\n\temail = test@example.invalid\n', encoding="utf-8")
        self.original_config = self.config.read_bytes()
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_CONFIG_")}
        self.env.update(
            GIT_CONFIG_GLOBAL=str(self.config), GIT_CONFIG_SYSTEM=os.devnull,
            GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="review.inherited", GIT_CONFIG_VALUE_0="preserved",
            GITHUB_WORKSPACE=str(ROOT), ABK_LOCAL_CACHE_ROOT=str(self.root / "cache"),
            GITHUB_STEP_SUMMARY=str(self.root / "summary"),
        )
        self.git("init", "-b", "gki-android15-6.6", str(self.remote))
        (self.remote / "source").write_text("pinned source", encoding="utf-8")
        self.git("-C", str(self.remote), "add", ".")
        self.git("-C", str(self.remote), "commit", "-m", "pinned")
        self.pinned = self.git("-C", str(self.remote), "rev-parse", "HEAD")
        (self.remote / "source").write_text("new upstream source", encoding="utf-8")
        self.git("-C", str(self.remote), "commit", "-am", "new upstream")

    def git(self, *args):
        result = subprocess.run([self.real_git, *args], env=self.env, text=True, encoding="utf-8", capture_output=True, check=True)
        return result.stdout.strip()

    def install_git_observer(self):
        directory = self.root / "bin"
        directory.mkdir()
        observer = directory / "git"
        observer.write_text('''#!/usr/bin/env bash
set -eu
if [ "${REVIEW_OBSERVE:-}" = true ]; then
  "$REVIEW_REAL_GIT" config --get review.inherited >> "$REVIEW_INHERITED_LOG"
  "$REVIEW_REAL_GIT" config --get-urlmatch http.extraheader https://github.com/example/private.git >> "$REVIEW_AUTH_LOG" || true
fi
exec "$REVIEW_REAL_GIT" "$@"
''', encoding="utf-8")
        observer.chmod(0o755)
        self.env.update(PATH=str(directory) + os.pathsep + self.env["PATH"],
                        REVIEW_REAL_GIT=self.real_git, REVIEW_OBSERVE="true",
                        REVIEW_INHERITED_LOG=str(self.root / "inherited.log"),
                        REVIEW_AUTH_LOG=str(self.root / "auth.log"))

    def run_checkout(self, cached, private=True, fail=False):
        work = self.root / f"work-{cached}-{private}-{fail}"
        work.mkdir()
        env = dict(self.env, SOURCE_PRIVATE=str(private).lower(),
                   ABK_CUSTOM_SOURCE_GITHUB_TOKEN="test-token-never-real",
                   SOURCE_REPO=(self.root / "missing").as_uri() if fail else self.remote.as_uri(),
                   SOURCE_COMMIT=self.pinned, ABK_LOCAL_CACHE_ENABLED=str(cached).lower())
        if not cached:
            env["ABK_LOCAL_CACHE_ROOT"] = ""
        result = subprocess.run([shutil.which("bash"), str(CHECKOUT)], cwd=work, env=env,
                                capture_output=True, text=True, encoding="utf-8", errors="replace")
        if fail:
            self.assertNotEqual(result.returncode, 0)
        else:
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(self.git("-C", str(work / "common"), "rev-parse", "HEAD"), self.pinned)
        self.assertEqual(self.config.read_bytes(), self.original_config)
        # No newly written Git config, including cached mirrors, contains credentials.
        for path in self.root.rglob("config"):
            if path.is_file():
                value = path.read_text(encoding="utf-8")
                self.assertNotIn("extraheader", value.lower())
                self.assertNotIn("test-token-never-real", value)
        return result

    def test_private_auth_is_scoped_for_cached_and_uncached_success(self):
        self.install_git_observer()
        expected = "AUTHORIZATION: basic " + base64.b64encode(b"x-access-token:test-token-never-real").decode()
        for cached in (False, True):
            with self.subTest(cached=cached):
                self.run_checkout(cached)
        headers = (self.root / "auth.log").read_text().splitlines()
        self.assertTrue(headers)
        self.assertEqual(set(headers), {expected})
        self.assertEqual(set((self.root / "inherited.log").read_text().splitlines()), {"preserved"})
        self.assertEqual(self.git("config", "--get", "review.inherited"), "preserved")

    def test_failure_does_not_leave_credentials(self):
        for cached in (False, True):
            with self.subTest(cached=cached):
                self.run_checkout(cached, fail=True)

    def test_public_checkout_does_not_set_auth_headers(self):
        self.install_git_observer()
        for cached in (False, True):
            with self.subTest(cached=cached):
                self.run_checkout(cached, private=False)
        self.assertEqual((self.root / "auth.log").read_text(), "")

    def test_missing_private_token_fails_before_checkout(self):
        work = self.root / "missing-token"
        work.mkdir()
        env = dict(self.env, SOURCE_PRIVATE="true", ABK_CUSTOM_SOURCE_GITHUB_TOKEN="")
        result = subprocess.run([shutil.which("bash"), str(CHECKOUT)], cwd=work, env=env, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((work / "common").exists())
        self.assertEqual(self.config.read_bytes(), self.original_config)

    def test_workflow_checks_out_short_and_full_susfs_pins(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        step = text.split("- name: 克隆依赖仓库", 1)[1].split("- name: 克隆自定义外部模块", 1)[0]
        script = textwrap.dedent(step.split("run: |\n", 1)[1])
        retry = re.search(r"(?ms)^retry_git_clone\(\) \{.*?^\}", script).group()
        block = script.split('if [ "${{ inputs.enable_susfs }}" == "true" ]; then', 1)[1]
        block = 'if [ "true" == "true" ]; then' + block.split('echo "准备补丁资源..."', 1)[0]
        block = block.replace('https://gitlab.com/simonpunk/susfs4ksu.git', self.remote.as_uri())
        script = 'set -euo pipefail\n' + retry + '\n' + block
        for cached in (False, True):
            # Run a second cached build using the same history after the first pin.
            for pin in (self.pinned[:12], self.pinned):
                with self.subTest(cached=cached, pin_length=len(pin)):
                    work = self.root / f"susfs-{cached}-{len(pin)}"
                    (work / "config").mkdir(parents=True)
                    (work / "config/config").write_text(f"custom=true\ngki-android15-6.6={pin}\n", encoding="utf-8")
                    env = dict(self.env, ABK_LOCAL_CACHE_ENABLED=str(cached).lower(),
                               SUSFS_BRANCH="gki-android15-6.6", GITHUB_ENV=str(work / "env"))
                    if not cached:
                        env["ABK_LOCAL_CACHE_ROOT"] = ""
                    result = subprocess.run([shutil.which("bash"), "-c", script], cwd=work, env=env,
                                            text=True, encoding="utf-8", capture_output=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(self.git("-C", str(work / "susfs4ksu"), "rev-parse", "HEAD"), self.pinned)
                    self.assertEqual((work / "susfs4ksu/source").read_text(), "pinned source")
                    if cached and len(pin) == 12:
                        (self.remote / "source").write_text("another upstream update", encoding="utf-8")
                        self.git("-C", str(self.remote), "commit", "-am", "advance branch between cached builds")
