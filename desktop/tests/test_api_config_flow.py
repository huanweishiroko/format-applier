"""回归测试：设置页 API 配置校验。

锁死三条不变量（对应「界面 ✅ 却提示三项没填齐」的事故）：

1. 只要三个输入框有值，就一定能组装出请求参数，**不依赖 config.json 是否写得进去**；
2. 「写不进盘」不再被当成「没填齐」；
3. 纯空白（含 NBSP / 全角空格 / 零宽字符）按没填处理。

跑法::

    .venv\\Scripts\\python.exe -m unittest discover -s desktop/tests -v
"""

from __future__ import annotations

import sys
import threading
import types
import unittest
from pathlib import Path

DESKTOP = Path(__file__).resolve().parents[1]
if str(DESKTOP) not in sys.path:
    sys.path.insert(0, str(DESKTOP))

from parser import llm_parser  # noqa: E402
from ui import settings as ui_settings  # noqa: E402


class ConfigFromValuesTest(unittest.TestCase):
    """输入框的值 → LlmConfig，不该再看磁盘。"""

    def test_strips_invisible_whitespace(self):
        conf = llm_parser.config_from_values(
            "\u3000 https://api.deepseek.com/v1 \u200b",
            "  sk-2df1234567890d64b\u00a0 ",
            "\tdeepseek-chat\n",
        )
        self.assertEqual(conf.base_url, "https://api.deepseek.com/v1")
        self.assertEqual(conf.api_key, "sk-2df1234567890d64b")
        self.assertEqual(conf.model, "deepseek-chat")
        self.assertEqual(conf.missing, ())
        self.assertEqual(conf.source, "设置页输入")

    def test_blank_only_value_counts_as_missing(self):
        with self.assertRaises(llm_parser.LlmConfigError) as ctx:
            llm_parser.config_from_values("https://api.deepseek.com/v1", "\u3000 ", "deepseek-chat")
        self.assertIn("API 密钥", str(ctx.exception))

    def test_to_dsl_accepts_cfg_without_disk_lookup(self):
        conf = llm_parser.config_from_values("https://x/v1", "k", "m")
        seen = {}

        def fake_client(cfg):  # noqa: ANN001
            seen["cfg"] = cfg
            raise RuntimeError("stop-before-network")

        original = llm_parser.get_client
        llm_parser.get_client = fake_client
        try:
            with self.assertRaises(RuntimeError):
                llm_parser.to_dsl("标题黑体二号居中", cfg=conf)
        finally:
            llm_parser.get_client = original
        self.assertIs(seen.get("cfg"), conf)


class TestApiFlowTest(unittest.TestCase):
    """_test_api 的分支：缺项 vs 写不进盘。"""

    FULL = {
        "api_base_url": " https://api.deepseek.com/v1 ",
        "api_key": "sk-2df1234567890d64b",
        "api_model": "deepseek-chat",
    }

    def _run(self, values, save_result, wait=False):
        cap = {}
        fired = threading.Event()

        def fake_client(conf):  # noqa: ANN001
            cap["conf"] = conf
            fired.set()
            raise RuntimeError("stop-before-network")

        original = llm_parser.get_client
        llm_parser.get_client = fake_client
        stub = types.SimpleNamespace(
            _testing=False,
            api_vars={},
            _current_api=lambda: dict(values),
            _save_api=lambda announce=True: save_result,
            api_state=types.SimpleNamespace(configure=lambda **kw: cap.update(state=kw.get("text"))),
            app=types.SimpleNamespace(status=lambda m: None, log=lambda m: None),
            _show_api_detail=lambda t: cap.update(detail=t),
            after=lambda ms, fn: cap.update(after=fn),
        )
        try:
            ui_settings.SettingsPage._test_api(stub)
            if wait:
                fired.wait(5)
        finally:
            llm_parser.get_client = original
        return cap

    def test_unwritable_config_still_sends_request(self):
        cap = self._run(self.FULL, "unwritable", wait=True)
        detail = cap.get("detail", "")
        self.assertEqual(detail.count("✅"), 3)
        self.assertNotIn("三项没填齐", detail)
        self.assertIn("没能写入", detail)
        conf = cap.get("conf")
        self.assertIsNotNone(conf, "填齐后必须真的发起请求")
        self.assertEqual(conf.api_key, "sk-2df1234567890d64b")
        self.assertEqual(conf.source, "设置页输入")

    def test_saved_config_also_sends_request(self):
        cap = self._run(self.FULL, "ok", wait=True)
        self.assertIn("三项已写入", cap.get("detail", ""))
        self.assertIsNotNone(cap.get("conf"))

    def test_truly_missing_field_blocks_request(self):
        cap = self._run({"api_base_url": "https://api.deepseek.com/v1",
                         "api_key": "sk-2df1234567890d64b",
                         "api_model": "   "}, "ok")
        detail = cap.get("detail", "")
        self.assertIn("三项没填齐", detail)
        self.assertIn("模型名称", detail)
        self.assertNotIn("conf", cap)
        self.assertEqual(cap.get("state"), "缺少 API 配置")


if __name__ == "__main__":
    unittest.main(verbosity=2)
