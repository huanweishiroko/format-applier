# -*- coding: utf-8 -*-
"""回归测试：CLI 崩溃（stdout 为空、stderr 带 traceback）时的错误提取。

对应事故：输出目录不可写 → CLI 打 traceback、stdout 为空 → 界面只弹
「处理失败：CLI 没有输出任何内容」，用户看不到真正的 PermissionError。

跑法::

    .venv\\Scripts\\python.exe -m unittest discover -s desktop/tests -v
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

DESKTOP = Path(__file__).resolve().parents[1]
if str(DESKTOP) not in sys.path:
    sys.path.insert(0, str(DESKTOP))

from core import bridge  # noqa: E402

TRACEBACK = (
    "Traceback (most recent call last):\r\n"
    '  File "...\\cli.py", line 151, in main\r\n'
    "    summary = applier.apply_format(\r\n"
    '  File "...\\report.py", line 256, in write_reports\r\n'
    '    with open(report_json, "w", encoding="utf-8") as handle:\r\n'
    "PermissionError: [Errno 13] Permission denied: 'E:\\\\out\\\\report.json'\r\n"
)


class StderrErrorTest(unittest.TestCase):
    def test_traceback_tail(self) -> None:
        text = bridge._stderr_error(TRACEBACK)
        self.assertIn("PermissionError", text)
        self.assertIn("report.json", text)
        self.assertNotIn("Traceback", text)

    def test_cli_error_line_wins(self) -> None:
        text = bridge._stderr_error("[wfa] 进度\n  error: 预设不存在\n余下噪音\n")
        self.assertEqual(text, "预设不存在")

    def test_empty(self) -> None:
        self.assertEqual(bridge._stderr_error(""), "")
        self.assertEqual(bridge._stderr_error("   \n\n"), "")


class ProcessCrashTest(unittest.TestCase):
    """``process()`` 不能再把 traceback 折成「没有输出」。"""

    def test_stdout_empty_uses_stderr(self) -> None:
        target = DESKTOP.parent / "samples" / "target.docx"
        self.assertTrue(target.is_file(), target)
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(bridge, "_run", return_value=(1, "", TRACEBACK)):
                result = bridge.process(
                    target=str(target),
                    preset="格式要求1",
                    output=str(Path(tmp) / "out.docx"),
                )
        self.assertFalse(result["ok"])
        self.assertIn("PermissionError", result["_error"])
        self.assertNotIn("没有输出", result["_error"])

    def test_empty_stdout_zero_exit_still_raises(self) -> None:
        target = DESKTOP.parent / "samples" / "target.docx"
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(bridge, "_run", return_value=(0, "", "")):
                with self.assertRaises(bridge.BridgeError):
                    bridge.process(
                        target=str(target),
                        preset="格式要求1",
                        output=str(Path(tmp) / "out.docx"),
                    )


class StderrDigestTest(unittest.TestCase):
    """stderr 进弹窗前必须过滤：丢 INFO 进度，留 ERROR/WARN 与异常栈。"""

    def test_filters_progress_keeps_errors_and_frames(self) -> None:
        text = (
            "[wfa] rules: 24\n"
            "[wfa] cleanup: 0 paragraph(s) rewritten\n"
            "Traceback (most recent call last):\n"
            '  File "cli.py", line 1, in main\n'
            "error: 输出目录不可写：E:\\out（PermissionError）\n"
        )
        digest = bridge._stderr_digest(text)
        self.assertNotIn("rules: 24", digest)
        self.assertNotIn("cleanup: 0", digest)
        self.assertIn("Traceback", digest)
        self.assertIn("PermissionError", digest)

    def test_caps_line_count(self) -> None:
        text = "\n".join("frame %d Error" % index for index in range(100))
        self.assertLessEqual(len(bridge._stderr_digest(text).splitlines()), 40)

    def test_empty(self) -> None:
        self.assertEqual(bridge._stderr_digest(" \n\n"), "")


class ProcessSummaryErrorTest(unittest.TestCase):
    """CLI 正常回 JSON（ok=false + errors）时，界面必须看到 errors 原文。"""

    def test_cli_json_errors_beat_exit_code(self) -> None:
        target = DESKTOP.parent / "samples" / "target.docx"
        self.assertTrue(target.is_file(), target)
        payload = json.dumps({
            "ok": False,
            "output_docx": None,
            "errors": ["failed to write output: PermissionError: "
                       "[Errno 13] Permission denied: 'E:\\\\out.docx'"],
            "warnings": [],
            "partial": True,
        }, ensure_ascii=False)
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(bridge, "_run", return_value=(1, payload, "")):
                result = bridge.process(
                    target=str(target),
                    preset="格式要求1",
                    output=str(Path(tmp) / "out.docx"),
                )
        self.assertFalse(result["ok"])
        self.assertIn("PermissionError", result["_error"])
        self.assertIn("failed to write output", result["_error"])
        self.assertNotIn("退出码", result["_error"])


class TempReportPathTest(unittest.TestCase):
    """报告默认落临时目录，绝不写 exe / 输出目录旁边。"""

    def test_default_report_is_under_temp(self) -> None:
        output = str(Path(tempfile.gettempdir()) / "out.docx")
        report = bridge.temp_report_path(output)
        temp_root = str(Path(tempfile.gettempdir()))
        self.assertTrue(report.startswith(temp_root), report)
        self.assertNotEqual(Path(report).parent, Path(output).parent)
        self.assertIn("taofu-reports", report)


if __name__ == "__main__":
    unittest.main()
