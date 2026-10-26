# -*- coding: utf-8 -*-
"""主题引擎回归：单皮肤 cyber_noir 必须完整、别名一致、圆角唯一。

跑法::

    .venv\\Scripts\\python.exe -m unittest discover -s desktop/tests -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

DESKTOP = Path(__file__).resolve().parents[1]
if str(DESKTOP) not in sys.path:
    sys.path.insert(0, str(DESKTOP))

from ui import theme as th  # noqa: E402


class SkinValidationTest(unittest.TestCase):
    def test_all_skins_complete_and_reversible(self):
        th.validate_skins()
        self.assertEqual(set(th.SKIN_KEYS), {"cyber_noir"})
        self.assertEqual(th.DEFAULT_SKIN, "cyber_noir")

    def test_each_skin_has_all_color_tokens(self):
        expected = set(th.COLOR_TOKENS)
        for key, skin in th.SKINS.items():
            with self.subTest(skin=key):
                self.assertEqual(set(skin.colors), expected)
                self.assertEqual(len(skin.colors), 41)

    def test_radius_profiles_are_unique(self):
        for key, skin in th.SKINS.items():
            with self.subTest(skin=key):
                values = list(skin.radii.values())
                self.assertEqual(len(values), 4)
                self.assertEqual(len(set(values)), 4)

    def test_switching_skins_keeps_public_token_names(self):
        old = th.active_key()
        try:
            for key in th.SKIN_KEYS:
                th.set_skin(key)
                self.assertEqual(th.active_key(), key)
                self.assertEqual(len(th.PALETTE), 41)
                self.assertEqual(th.PALETTE["accent"], th.ACCENT)
                # 别名组必须是同一色对
                self.assertEqual(th.ACCENT, th.DROP_BORDER_ACTIVE)
                self.assertEqual(th.WARNING, th.DROP_BORDER_WARN)
                self.assertEqual(th.SECONDARY, th.DANGER)
                self.assertEqual(th.BG_SURFACE_ALT, th.BG_SIDEBAR)
                # 固定深色 + 锐利圆角
                self.assertEqual(
                    [int(th.RADIUS_S), int(th.RADIUS), int(th.RADIUS_L),
                     int(th.RADIUS_XL)],
                    [2, 4, 6, 8],
                )
                self.assertFalse(hasattr(th, "RADIUS_PILL"))
        finally:
            th.set_skin(old)


if __name__ == "__main__":
    unittest.main()
