"""回归测试：config.json 写不进去时到底发生了什么。

对应事故：设置页提示「未写入 %APPDATA%\\Taofu\\config.json（本机配置不可写）」，
既没告诉用户真实原因，也没做任何退让，配置就此丢失。

锁死四条：

1. 只读文件先被清属性再写，能写成功（copy2/copytree 搬过来的只读属性不再是死路）；
2. 真写不进去时，返回**具体**的 OSError（WinError / errno / 路径），不再只吞成 False；
3. 主落点写不进 → 自动改存到备用落点，并且读的时候读到的是最新那份；
4. 老数据迁移后，新目录里的文件一律可写。

跑法::

    .venv\\Scripts\\python.exe -m unittest discover -s desktop/tests -v
"""

from __future__ import annotations

import os
import stat
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

DESKTOP = Path(__file__).resolve().parents[1]
if str(DESKTOP) not in sys.path:
    sys.path.insert(0, str(DESKTOP))

from core import config as cfg  # noqa: E402


class ConfigSaveTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.settings = cfg.Settings(output_dir=str(self.root), theme="浅色",
                                     api_base_url="https://api.deepseek.com/v1",
                                     api_key="sk-test", api_model="deepseek-chat")
        self._orig_candidates = cfg.config_candidates

    def tearDown(self):
        cfg.config_candidates = self._orig_candidates
        self._tmp.cleanup()

    def test_readonly_file_is_cleared_and_written(self):
        target = self.root / "config.json"
        target.write_text("{}", encoding="utf-8")
        os.chmod(target, stat.S_IREAD)          # 模拟 copy2 带过来的只读属性
        ok, path, error = cfg.save_settings_ex(self.settings, target)
        self.assertTrue(ok, f"只读文件应被清属性后写成功，实际: {error}")
        self.assertEqual(path, target)
        self.assertIn("api_key", target.read_text(encoding="utf-8"))

    def test_failure_reports_specific_oserror(self):
        bogus = self.root / "not-a-file"         # 目录当文件写 → 必然失败
        bogus.mkdir()
        ok, path, error = cfg.save_settings_ex(self.settings, bogus)
        self.assertFalse(ok)
        self.assertEqual(path, bogus)
        self.assertTrue(error, "失败必须带回具体原因")
        self.assertTrue(
            ("Errno" in error) or ("WinError" in error) or ("错误" in error)
            or ("Error" in error),
            f"错误文案里应含 WinError/errno，实际: {error}",
        )
        self.assertIn(str(bogus), error)

    def test_falls_back_to_second_location_when_primary_blocked(self):
        blocked = self.root / "blocked" / "config.json"
        blocked.parent.mkdir()
        (blocked.parent / "config.json").mkdir()          # 占位目录 → 主落点写不进
        good = self.root / "local" / "config.json"
        cfg.config_candidates = lambda: (blocked, good)

        ok, path, error = cfg.save_settings_ex(self.settings)
        self.assertTrue(ok, f"应退让到备用落点，实际: {error}")
        self.assertEqual(path, good)
        self.assertTrue(good.is_file())
        self.assertEqual(cfg.active_config_path(), good)
        self.assertEqual(cfg.api_config_values()["api_key"], "sk-test")

    def test_reads_newest_regardless_of_candidate_order(self):
        primary = self.root / "primary.json"
        backup = self.root / "backup.json"
        primary.write_text('{"api_key": "old"}', encoding="utf-8")
        backup.write_text('{"api_key": "new"}', encoding="utf-8")
        os.utime(primary, (1000, 1000))
        cfg.config_candidates = lambda: (primary, backup)
        self.assertEqual(cfg.active_config_path(), backup)
        self.assertEqual(cfg.api_config_values()["api_key"], "new")


class MigrationPermissionTest(unittest.TestCase):
    def test_migrated_files_become_writable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            new_dir = root / "Taofu"
            old_dir = root / "WordFormatAssistant"
            (old_dir / "presets").mkdir(parents=True)
            legacy_cfg = old_dir / "config.json"
            legacy_cfg.write_text('{"api_key": "legacy"}', encoding="utf-8")
            (old_dir / "presets" / "a.txt").write_text("x", encoding="utf-8")
            os.chmod(legacy_cfg, stat.S_IREAD)      # 老文件是只读的

            original_user = cfg.user_data_dir
            original_legacy = cfg.legacy_user_data_dir
            cfg.user_data_dir = lambda create=False: new_dir
            cfg.legacy_user_data_dir = lambda: old_dir
            try:
                summary = cfg.migrate_legacy_data()
            finally:
                cfg.user_data_dir = original_user
                cfg.legacy_user_data_dir = original_legacy

            self.assertIsNotNone(summary, "迁移应被触发")
            copied = new_dir / "config.json"
            self.assertTrue(copied.is_file())
            self.assertTrue(copied.stat().st_mode & stat.S_IWRITE,
                            "迁移后必须可写，否则设置页永远保存失败")
            # 迁移完还能正常覆盖写
            ok, _path, error = cfg.save_settings_ex(cfg.Settings(), copied)
            self.assertTrue(ok, error)


if __name__ == "__main__":
    unittest.main(verbosity=2)
