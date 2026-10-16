# -*- coding: utf-8 -*-
"""拖放人工验证窗：打开一个小窗口，把一个 .docx 拖进去，看是否打印路径。

用法：
    .venv\\Scripts\\python.exe tools\\gui_probe.py --dnd-check
    .venv\\Scripts\\python.exe tools\\gui_probe.py            # 只做环境探测

只读：不写任何文件（DND 结果只打印到终端）。窗口 60 秒后自动关闭。
"""

from __future__ import annotations

import sys
import tkinter as tk

REQUIRED = (
    "CTk", "CTkFrame", "CTkLabel", "CTkButton", "CTkEntry", "CTkComboBox",
    "CTkOptionMenu", "CTkTextbox", "CTkScrollableFrame", "CTkProgressBar",
    "CTkFont", "CTkToplevel", "set_appearance_mode", "set_default_color_theme",
)


def probe() -> int:
    print(f"python {sys.version.split()[0]}")
    try:
        import customtkinter as ctk
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL  customtkinter 导入失败：{exc}")
        return 2
    print(f"OK    customtkinter {getattr(ctk, '__version__', '?')}")

    missing = [n for n in REQUIRED if not hasattr(ctk, n)]
    print(f"{'OK   ' if not missing else 'FAIL '} 控件 API 缺失：{missing or '无'}")

    try:
        import tkinterdnd2
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL  tkinterdnd2 导入失败：{exc}")
        return 3
    print(f"OK    tkinterdnd2 {getattr(tkinterdnd2, '__version__', '?')}")

    try:
        import PIL
        print(f"OK    pillow {PIL.__version__}")
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL  pillow 导入失败：{exc}")

    # tkdnd 在 CTk 根窗口上手工加载（与 desktop/app.py 的 enable_dnd 同路子）
    root = ctk.CTk()
    root.withdraw()
    try:
        from tkinterdnd2 import DND_FILES, TkinterDnD

        TkinterDnD._require(root)
        print(f"OK    tkdnd {TkinterDnD.TkdndVersion} 已加载（Tcl {root.tk.call('info', 'tclversion')}）")
        frame = ctk.CTkFrame(root)
        frame.pack()
        frame._canvas.drop_target_register(DND_FILES)
        print("OK    drop_target_register 可用")
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL  拖放注册失败：{exc}")
        return 4

    families = set(tk.font.families(root))  # type: ignore[attr-defined]
    for name in ("Microsoft YaHei UI", "Microsoft YaHei"):
        print(f"{'OK   ' if name in families else 'WARN '} 字体 {name}")
    root.destroy()

    print("RESULT: PROBE_OK")
    return 0


def dnd_check() -> int:
    """人工验证：拖一个文件进窗口，终端会打印收到的路径。"""
    import customtkinter as ctk
    from tkinterdnd2 import DND_FILES, TkinterDnD

    root = ctk.CTk()
    TkinterDnD._require(root)
    root.title("拖放验证 · 把一个 .docx 拖进来")
    root.geometry("520x260")

    box = ctk.CTkFrame(root, corner_radius=12)
    box.pack(fill="both", expand=True, padx=20, pady=20)
    label = ctk.CTkLabel(box, text="拖拽 .docx 文件到此处", font=ctk.CTkFont(size=16, weight="bold"))
    label.pack(expand=True)

    def on_drop(event) -> None:
        paths = list(event.widget.tk.splitlist(event.data))
        print("DROP OK:", paths)
        label.configure(text="收到：\n" + "\n".join(paths))

    for widget in (box._canvas, root._canvas):
        try:
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", on_drop)
        except Exception as exc:  # noqa: BLE001
            print(f"WARN 注册 {widget} 失败：{exc}")

    print("请在 60 秒内把文件拖进窗口；ESC 或关窗结束。")
    root.after(60000, root.destroy)
    root.mainloop()
    print("RESULT: DND_CHECK_DONE")
    return 0


def main() -> int:
    if "--dnd-check" in sys.argv:
        return dnd_check()
    return probe()


if __name__ == "__main__":
    raise SystemExit(main())
