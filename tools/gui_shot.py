# -*- coding: utf-8 -*-
"""批量截图：把主窗口的各页面 × 主题存成 PNG，用于人工核对布局。

用法：
    .venv\\Scripts\\python.exe tools\\gui_shot.py [输出目录] [样例docx]

默认输出到 ./screenshots/，文件名形如 ``gui-home-light.png``。
只读屏幕（PIL ImageGrab），除截图外不改任何文件；主题会改回运行前的值。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "desktop"))

from desktop.app import FormatApp  # noqa: E402

PAGES = ("home", "presets", "settings", "about")
THEMES = ("浅色", "深色")


def main() -> int:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else (_ROOT / "screenshots")
    sample = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    out_dir.mkdir(parents=True, exist_ok=True)

    from PIL import ImageGrab

    app = FormatApp()
    original_theme = app.settings.theme
    app.geometry("1080x720+60+40")
    app.update()

    if sample is not None and sample.is_file():
        app.pages["home"].load_file(sample)
        app.update()

    shots = []

    def grab(tag: str) -> None:
        app.update()
        app.update_idletasks()
        time.sleep(0.25)
        app.update()
        x, y = app.winfo_rootx(), app.winfo_rooty()
        w, h = app.winfo_width(), app.winfo_height()
        img = ImageGrab.grab(bbox=(x, y, x + w, y + h))
        path = out_dir / f"{tag}.png"
        img.save(path)
        shots.append(str(path))

    def run() -> None:
        for theme in THEMES:
            app.apply_theme(theme)
            app.update()
            for page in PAGES:
                app.show_page(page)
                app.update()
                grab(f"gui-{page}-{'dark' if theme == '深色' else 'light'}")
        app.apply_theme(original_theme)
        print("\n".join(shots))
        print("RESULT: SHOT_OK")
        app.destroy()

    app.after(900, run)
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
