import importlib.util
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "build.yml"
REF_SCRIPT_PATH = ROOT / ".github" / "scripts" / "resolve-ksu-ref.sh"
KSU_COMPAT_PATH = ROOT / ".github" / "scripts" / "ensure-ksu-compat.py"


class KernelWorkflowRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        cls.ref_script = REF_SCRIPT_PATH.read_text(encoding="utf-8")
        spec = importlib.util.spec_from_file_location("ensure_ksu_compat", KSU_COMPAT_PATH)
        cls.ksu_compat = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.ksu_compat)

    def test_sukisu_setup_accepts_resolved_bare_sha(self):
        block = self._step_run_block("添加 KernelSU")
        case = block.split('"SukiSU")', 1)[1].split('"ReSukiSU")', 1)[0]

        self.assertIn('requested_ref="$BRANCH"', case)
        self.assertNotIn('${BRANCH#-s }', case)
        self.assertIn('bash "$setup_script" "$requested_ref"', case)
        self.assertIn('requested_head="$(git -C KernelSU rev-parse', case)

    def test_development_refs_are_immutable_commit_pins(self):
        for variable in ("OFFICIAL_DEV_REF", "SUKISU_DEV_REF", "RESUKISU_DEV_REF"):
            with self.subTest(variable=variable):
                pins = re.findall(rf'(?m)^{variable}="([a-f0-9]{{40}})"(?:\s*#.*)?$', self.ref_script)
                self.assertEqual(len(pins), 1, f"{variable} must have one full immutable commit SHA")
                self.assertNotEqual(pins[0], "0" * 40)

    @unittest.skipUnless(os.name != "nt" and shutil.which("bash"), "resolver requires POSIX bash")
    def test_development_tier_selects_variant_pin_without_network(self):
        variants = (
            ("Official", "OFFICIAL_DEV_REF", "1" * 40, "tiann/KernelSU"),
            ("SukiSU", "SUKISU_DEV_REF", "2" * 40, "SukiSU-Ultra/SukiSU-Ultra"),
            ("ReSukiSU", "RESUKISU_DEV_REF", "3" * 40, "ReSukiSU/ReSukiSU"),
        )
        # Distinct canaries detect accidentally selecting Stable or another
        # variant, even when the real Stable/Dev pins happen to be identical.
        fixture = self.ref_script
        for _, variable, sha, _ in variants:
            fixture, count = re.subn(rf'(?m)^{variable}="[a-f0-9]{{40}}"', f'{variable}="{sha}"', fixture)
            self.assertEqual(count, 1)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            script = root / "resolve.sh"
            script.write_text(fixture, encoding="utf-8")
            curl = root / "curl"
            curl.write_text("#!/bin/sh\nprintf 'unexpected network lookup for a pinned tier\\n' >&2\nexit 97\n", encoding="utf-8")
            curl.chmod(0o755)
            for variant, _, sha, repo in variants:
                with self.subTest(variant=variant):
                    exported = root / f"{variant}.env"
                    env = dict(os.environ)
                    for key in ("BASH_ENV", "ENV", "RESOLVED_KSU_SHA", "RESOLVED_KSU_REPO", "RESOLVED_KSU_SOURCE_BRANCH", "GITHUB_TOKEN"):
                        env.pop(key, None)
                    env.update(KSU_VARIANT=variant, KSU_BRANCH="Dev(开发)", GITHUB_ENV=str(exported), PATH=str(root) + os.pathsep + env["PATH"])
                    result = subprocess.run([shutil.which("bash"), str(script)], env=env, capture_output=True, text=True, encoding="utf-8")
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    values = dict(line.split("=", 1) for line in exported.read_text(encoding="utf-8").splitlines())
                    self.assertEqual(values["BRANCH"], sha)
                    self.assertEqual(values["RESOLVED_KSU_SHA"], sha)
                    self.assertEqual(values["RESOLVED_KSU_REPO"], repo)
                    self.assertEqual(values["RESOLVED_KSU_SOURCE_BRANCH"], "")

    def test_resolved_sha_defaults_to_selected_variant_ref(self):
        self.assertIn(
            'emit_env "RESOLVED_KSU_SHA" "${RESOLVED_KSU_SHA:-$BRANCH}"',
            self.ref_script,
        )

    def test_susfs_compatibility_step_covers_sukisu_variants(self):
        step = self.workflow.split("- name: 确保 KernelSU SUSFS ABI 兼容", 1)[1].split("- name: 配置 SukiSU 管理器信息", 1)[0]
        self.assertIn(
            "if: (inputs.ksu_variant == 'SukiSU' || inputs.ksu_variant == 'ReSukiSU') && inputs.enable_susfs",
            step,
        )
        self.assertIn("custom-source-feature-env.sh", step)
        self.assertIn("ABK_FEATURE_ID: kernelsu", step)

    def test_sukisu_nested_supercall_gets_susfs_fd_compatibility(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ksu = root / "KernelSU" / "kernel"
            supercall = ksu / "supercall"
            feature = ksu / "feature"
            supercall.mkdir(parents=True)
            feature.mkdir()
            (ksu / "Kbuild").write_text("obj-y += supercall/\n", encoding="utf-8")
            source = supercall / "supercall.c"
            header = supercall / "supercall.h"
            source.write_text(
                "int ksu_install_fd(void) { return 0; }\n"
                "void __init ksu_supercalls_init(void) {}\n",
                encoding="utf-8",
            )
            header.write_text("int ksu_install_fd(void);\n", encoding="utf-8")
            (feature / "kernel_umount.c").write_text(
                "int ksu_kernel_umount_enabled;\n"
                "\nstatic const struct ksu_feature_handler kernel_umount_handler = {};\n",
                encoding="utf-8",
            )

            self.ksu_compat.main(str(root))

            self.assertIn("int ksu_install_su_fd(void)", source.read_text(encoding="utf-8"))
            self.assertIn("int ksu_install_su_fd(void);", header.read_text(encoding="utf-8"))
            self.assertIn(
                "static int kernel_umount_feature_set(u64 value)",
                (feature / "kernel_umount.c").read_text(encoding="utf-8"),
            )

    def test_scoped_su_fd_compatibility_preserves_session_permission(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            ksu = Path(temp_dir)
            source = ksu / "supercall.c"
            source.write_text(
                "#define KSU_DRIVER_PERMISSION_SU_SESSION (1UL << 0)\n"
                "static int ksu_install_fd_with_permissions(unsigned int flags, unsigned long permissions) { return 0; }\n"
                "int ksu_install_fd(void) { return ksu_install_fd_with_permissions(O_CLOEXEC, 0); }\n"
                "void __init ksu_supercalls_init(void) {}\n",
                encoding="utf-8",
            )

            self.ksu_compat.ensure_su_fd(ksu)

            self.assertIn(
                "ksu_install_fd_with_permissions(O_CLOEXEC, KSU_DRIVER_PERMISSION_SU_SESSION)",
                source.read_text(encoding="utf-8"),
            )

    def test_android12_ntsync_compat_filters_incompatible_lockdep_hunk(self):
        block = self._step_run_block("应用 NTsync 补丁")
        self.assertIn("apply_android12_ntsync_compat", block)
        self.assertIn('source.find("@@ -305,25 +310,29")', block)
        self.assertIn('source.find("@@ -5308,13 +5309,13")', block)
        self.assertIn("#define lockdep_assert(cond)", block)
        self.assertIn("return LOCK_STATE_HELD;", block)
        self.assertIn(
            'if [[ "$ABK_ANDROID_VERSION" == "android12" && "$ABK_KERNEL_VERSION" == "5.10" ]]',
            block,
        )

    def test_android12_statfs_repair_injects_verified_declaration(self):
        block = self._step_run_block("应用 SUSFS 补丁")
        self.assertIn(
            'declaration = "extern int susfs_sus_kstat_spoof_vfs_statfs(struct inode *inode, '
            'struct kstatfs *buf, bool *is_fuse);"',
            block,
        )
        self.assertIn("declared > call", block)
        self.assertIn('#include <linux/security.h>', block)
        self.assertIn('security_sb_statfs(', block)
        self.assertNotIn(
            "android12-5.10 Official fs/statfs.c 缺少 susfs_def.h",
            block,
        )
        statfs_repair = block.split("# Android 12/5.10 的上游补丁", 1)[1].split("# Android 13 - 5.15 修复", 1)[0]
        self.assertNotIn('[[ "$ABK_KSU_VARIANT" == "Official" ]]', statfs_repair)
        self.assertIn("fix_fdinfo_declarations", block)
        self.assertIn('declarations.append("\\tstruct mount *mnt;\\n")', block)

    def test_sukisu_post_exec_wrapper_installs_su_session_fd(self):
        block = self._step_run_block("最终修复 SukiSU/ReSukiSU 源码兼容")
        self.assertIn("ensure_post_execveat_wrapper", block)
        self.assertIn('#include "supercall/supercall.h"', block)
        self.assertIn("int ksu_handle_post_execveat_sucompat(", block)
        self.assertIn("(void)ksu_install_su_fd();", block)

    def test_official_post_exec_wrapper_is_preserved_after_rewrite(self):
        block = self._step_run_block("修复 Official SUSFS 源码兼容")
        self.assertIn('int ksu_handle_post_execveat_sucompat(', block)
        self.assertIn('(void)ksu_install_su_fd();', block)
        self.assertIn('#include "supercall/supercall.h"', block)

    def test_susfs_common_file_fallbacks_cover_upstream_api_renames(self):
        block = self._step_run_block("应用 SUSFS 补丁")
        self.assertIn('mnt_userns', block)
        self.assertIn('text.replace("mnt_userns", "idmap")', block)
        self.assertIn('ensure_susfs_super_compat', block)
        self.assertIn('DEFAULT_KSU_MNT_MINOR_DEV', block)
        self.assertIn('susfs_get_non_sus_mnt_id_unique_from_mnt', block)

    def test_stat_api_rewrite_is_gated_to_native_idmap_kernels(self):
        block = self._step_run_block("应用 SUSFS 补丁")
        self.assertIn("native_new_api = \"struct mnt_idmap\" in text", block)
        self.assertIn(
            'if "mnt_userns" in text and native_new_api:',
            block,
        )

    def test_namespace_tail_repair_closes_truncated_susfs_hunk(self):
        block = self._step_run_block("应用 SUSFS 补丁")
        self.assertIn("ensure_susfs_namespace_tail", block)
        self.assertIn(
            'if (!mnt->mnt.mnt_root || IS_ERR(mnt->mnt.mnt_root)) {',
            block,
        )
        self.assertIn("#endif // #ifdef CONFIG_KSU_SUSFS", block)

    def test_android16_uses_native_ntsync_source(self):
        block = self._step_run_block("应用 NTsync 补丁")
        self.assertIn('if [[ "$ABK_ANDROID_VERSION" != "android16"', block)
        self.assertIn('NTsync 基础源码已由 android16-6.12 内核提供', block)

    def test_android14_builtin_ntsync_does_not_require_symbol_export(self):
        block = self._step_run_block("应用 NTsync 补丁")
        self.assertNotIn("EXPORT_SYMBOL", block)
        self.assertNotIn("拒绝启用 CONFIG_NTSYNC", block)
        self.assertIn("ensure_defconfig_value CONFIG_NTSYNC y", block)

    def _step_run_block(self, name):
        match = re.search(
            rf"(?ms)^      - name: {re.escape(name)}\n.*?^        run: \|\n"
            rf"(?P<body>.*?)(?=^      - name: |^    [A-Za-z0-9_-]+:|\Z)",
            self.workflow,
        )
        self.assertIsNotNone(match, f"step not found: {name}")
        return match.group("body")


if __name__ == "__main__":
    unittest.main()
