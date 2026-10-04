import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github" / "scripts" / "download-manager-from-actions.sh"
SHA = "cf87e3f4ddd3f6e5464d85acf56aaa6950e70841"
SUKISU = "SukiSU-Ultra/SukiSU-Ultra"
RUN_ID = 35591292466

FAKE_CURL = r'''
import json
import os
import shutil
import sys
from pathlib import Path

root = Path(os.environ["MANAGER_TEST_FIXTURES"])
fixture = json.loads((root / "fixture.json").read_text())
args = sys.argv[1:]
url = next(arg for arg in args if arg.startswith("https://"))
with (root / "requests.jsonl").open("a") as stream:
    stream.write(json.dumps({"url": url, "args": args}) + "\n")

if "/actions/workflows/build-manager.yml/runs?" in url:
    if "head_sha=" + fixture["sha"] not in url:
        sys.exit(22)
    print(json.dumps({"workflow_runs": [{"id": fixture["run_id"]}]}))
elif "/actions/runs/" in url and "/artifacts?" in url:
    if fixture.get("metadata_error"):
        sys.exit(22)
    print(json.dumps({"artifacts": fixture["artifacts"]}))
elif "/actions/artifacts/" in url:
    if fixture.get("api_error"):
        sys.exit(22)
    shutil.copyfile(root / "artifact.zip", args[args.index("-o") + 1])
elif url.startswith("https://nightly.link/"):
    if url.rsplit("/", 1)[1] not in fixture["nightly_names"]:
        sys.exit(22)
    shutil.copyfile(root / "artifact.zip", args[args.index("-o") + 1])
else:
    sys.exit(22)
'''


@unittest.skipUnless(
    os.name != "nt" and all(shutil.which(tool) for tool in ("bash", "jq", "unzip")),
    "Manager workflow integration tests require POSIX bash, jq and unzip",
)
class ManagerDownloadTests(unittest.TestCase):
    def run_download(
        self, artifacts, *, repo=SUKISU, github_repo="UmiSlat/ABK",
        token="test-workflow-token", nightly_names=None, metadata_error=False,
        api_error=False, archive="apk", existing_apk=False,
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            curl = bin_dir / "curl"
            curl.write_text(f"#!{sys.executable}\n" + FAKE_CURL, encoding="utf-8")
            curl.chmod(0o755)
            fixture = {
                "sha": SHA, "run_id": RUN_ID, "artifacts": artifacts,
                "nightly_names": nightly_names or ["Manager.zip"],
                "metadata_error": metadata_error, "api_error": api_error,
            }
            (root / "fixture.json").write_text(json.dumps(fixture), encoding="utf-8")
            if archive == "corrupt":
                (root / "artifact.zip").write_bytes(b"not a zip archive")
            else:
                with zipfile.ZipFile(root / "artifact.zip", "w") as artifact_zip:
                    if archive == "apk":
                        artifact_zip.writestr("release/SukiSU.apk", b"fixture apk")
                    else:
                        artifact_zip.writestr("mapping.txt", "mapping fixture")
            output = root / "output"
            if existing_apk:
                output.mkdir()
                (output / "old.apk").write_bytes(b"old download")
            env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}",
                       MANAGER_TEST_FIXTURES=str(root), GITHUB_TOKEN=token,
                       GITHUB_REPOSITORY=github_repo, TMPDIR=str(root))
            result = subprocess.run(
                ["bash", str(SCRIPT), repo, SHA, str(output)],
                env=env, capture_output=True, text=True, timeout=20,
            )
            requests = [json.loads(line) for line in
                        (root / "requests.jsonl").read_text().splitlines()]
            files = {path.relative_to(output).as_posix(): path.read_bytes()
                     for path in output.rglob("*") if path.is_file()}
            return result, requests, files

    def assert_downloaded(self, result, files):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(files["release/SukiSU.apk"], b"fixture apk")

    def test_sukisu_uses_actual_case_and_ignores_other_manager_variants(self):
        artifacts = [
            {"id": 1, "name": "Manager-spoofed", "expired": False},
            {"id": 2, "name": "Manager-mappings", "expired": False},
            {"id": 3, "name": "Manager-gradle", "expired": False},
            {"id": 4, "name": "manager", "expired": True},
            {"id": 5, "name": "Manager", "expired": False},
        ]
        result, requests, files = self.run_download(artifacts)
        self.assert_downloaded(result, files)
        self.assertEqual(requests[-1]["url"],
                         f"https://nightly.link/{SUKISU}/actions/runs/{RUN_ID}/Manager.zip")
        self.assertNotIn("fallback-main", result.stdout)
        self.assertTrue(all("Authorization: Bearer test-workflow-token" not in request["args"]
                            for request in requests))
        self.assertFalse(any("/actions/artifacts/" in request["url"] for request in requests))

    def test_legacy_and_other_variants_keep_their_artifact_names(self):
        for repo, name in ((SUKISU, "manager"), ("tiann/KernelSU", "manager"),
                           ("ReSukiSU/ReSukiSU", "Manager-release")):
            with self.subTest(repo=repo):
                result, requests, files = self.run_download(
                    [{"id": 5, "name": name, "expired": False}], repo=repo,
                    nightly_names=[name + ".zip"], token="",
                )
                self.assert_downloaded(result, files)
                self.assertEqual(requests[-1]["url"],
                                 f"https://nightly.link/{repo}/actions/runs/{RUN_ID}/{name}.zip")

    def test_same_repo_downloads_selected_artifact_via_authenticated_api(self):
        result, requests, files = self.run_download(
            [{"id": 5, "name": "Manager", "expired": False}], github_repo=SUKISU,
        )
        self.assert_downloaded(result, files)
        self.assertEqual(requests[-1]["url"],
                         f"https://api.github.com/repos/{SUKISU}/actions/artifacts/5/zip")
        self.assertIn("Authorization: Bearer test-workflow-token", requests[-1]["args"])

    def test_api_failure_falls_back_to_the_same_artifact_and_run(self):
        result, requests, files = self.run_download(
            [{"id": 5, "name": "Manager", "expired": False}],
            github_repo=SUKISU, api_error=True,
        )
        self.assert_downloaded(result, files)
        self.assertEqual(requests[-1]["url"],
                         f"https://nightly.link/{SUKISU}/actions/runs/{RUN_ID}/Manager.zip")

    def test_metadata_outage_tries_current_and_legacy_names_on_the_same_run(self):
        result, requests, files = self.run_download(
            [], metadata_error=True, nightly_names=["manager.zip"],
        )
        self.assert_downloaded(result, files)
        nightly_urls = [request["url"] for request in requests if "nightly.link" in request["url"]]
        self.assertEqual(nightly_urls, [
            f"https://nightly.link/{SUKISU}/actions/runs/{RUN_ID}/Manager.zip",
            f"https://nightly.link/{SUKISU}/actions/runs/{RUN_ID}/manager.zip",
        ])

    def test_missing_or_expired_normal_artifact_does_not_select_spoofed_apk(self):
        for artifacts in ([], [{"id": 5, "name": "Manager", "expired": True},
                               {"id": 6, "name": "Manager-spoofed", "expired": False}]):
            with self.subTest(artifacts=artifacts):
                result, requests, files = self.run_download(artifacts)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("No unexpired manager APK artifact", result.stderr)
                self.assertFalse(files)
                self.assertFalse(any("nightly.link" in request["url"] for request in requests))

    def test_invalid_download_cannot_succeed_because_of_an_existing_apk(self):
        for archive in ("no-apk", "corrupt"):
            with self.subTest(archive=archive):
                result, _, files = self.run_download(
                    [{"id": 5, "name": "Manager", "expired": False}],
                    archive=archive, existing_apk=True,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(files, {"old.apk": b"old download"})
                self.assertNotIn("Downloaded manager from", result.stdout)


if __name__ == "__main__":
    unittest.main()
