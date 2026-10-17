# -*- coding: utf-8 -*-
"""Taofu build helper: finish a PyInstaller onedir build.

Called by build.bat as:  <venv-python> "%~dp0build_finish.py"

Why this file exists
--------------------
build.bat must stay pure ASCII: cmd.exe decodes .bat bytes with the active code
page, so a non-ASCII literal in there - the app name is CJK - gets mangled.
Everything that has to touch the CJK output folder therefore lives here, where
Python handles real Unicode paths natively. No CJK literal is needed either:
the folder is discovered by scanning dist\\.

What it does
------------
1. finds the freshly built folder under dist\\ (newest directory by mtime)
2. moves _internal\\presets next to the exe, where the plugin CLI looks first
3. copies .env.example (the template only - never a real .env) next to the exe
4. deletes development leftovers that must not ship (notes, __pycache__, tools)
5. verifies the .exe exists, then prints the paths and the self-test command
6. reports stale sibling build folders from an older app name (never deletes)

Deliberately does NOT wipe dist\\ - that folder can hold release archives.
Exit code 0 = ok, 1 = hard failure.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

#: Files / folders that are development-only and must never reach a release.
DEV_LEFTOVERS = (
    "NOTES.md", "TODO.md", "docs", "tools", "tests", "samples",
    "_acl-recovery", "debug.log", "Thumbs.db",
)


def main() -> int:
    here = Path(__file__).resolve().parent
    os.chdir(here)                      # build.bat already cd's here; be explicit

    dist = here / "dist"
    if not dist.is_dir():
        print("[ERROR] no dist\\ folder next to build.bat")
        return 1

    dirs = sorted((d for d in dist.iterdir() if d.is_dir()), key=lambda d: d.stat().st_mtime)
    if not dirs:
        print("[ERROR] dist\\ contains no folder - did PyInstaller actually run?")
        return 1

    appdir = dirs[-1]
    print(f"app dir        : dist{os.sep}{os.path.relpath(appdir, dist)}")
    stale = [d.name for d in dirs[:-1]]
    if stale:
        print(f"stale siblings : {', '.join(stale)}   (older builds, left untouched)")

    # --- 1) built-in presets: _internal\presets -> next to the exe -------------
    src_presets = appdir / "_internal" / "presets"
    dst_presets = appdir / "presets"
    if dst_presets.is_dir():
        shutil.rmtree(dst_presets, ignore_errors=True)
    if src_presets.is_dir():
        shutil.move(str(src_presets), str(dst_presets))
        print("presets        : moved out of _internal\\presets")
    if dst_presets.is_dir():
        n = sum(1 for p in dst_presets.iterdir() if p.is_file())
        print(f"presets        : {n} file(s) next to the exe")
    else:
        print("[WARN] no presets folder next to the exe - the preset list may come up empty")

    # --- 2) .env.example：只发模板，绝不发真正的 .env --------------------------
    example = here / ".env.example"
    if example.is_file():
        shutil.copy2(example, appdir / ".env.example")
        print("copied         : .env.example (template only - no key inside)")
    leaked = appdir / ".env"
    if leaked.is_file():
        leaked.unlink()
        print("[WARN] removed a stray .env from the build - it must never ship")

    # --- 3) 清掉开发期残留 -----------------------------------------------------
    removed = []
    for name in DEV_LEFTOVERS:
        target = appdir / name
        if not target.exists():
            continue
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
        else:
            try:
                target.unlink()
            except OSError:
                continue
        removed.append(name)
    for cache in list(appdir.rglob("__pycache__")):
        shutil.rmtree(cache, ignore_errors=True)
    if list(appdir.rglob("__pycache__")):
        removed.append("some __pycache__")
    print("sanitized      : " + (", ".join(removed) if removed else "nothing to remove"))

    # --- 4) the exe ------------------------------------------------------------
    exes = sorted(appdir.glob("*.exe"))
    if not exes:
        print(f"[ERROR] no .exe inside dist{os.sep}{os.path.relpath(appdir, dist)}")
        print("        构建可能没跑完，检查上方 PyInstaller 输出是否有 ERROR。")
        return 1
    exe = exes[0]
    rel_dir = os.path.relpath(appdir, dist)
    print(f"exe            : {exe.name}   ({exe.stat().st_size} bytes)")

    print("")
    print('self-test - no GUI; "count" should equal the number of built-in presets:')
    print(f'    cd dist{os.sep}{rel_dir} && .\\{exe.name} --wfa-cli --list-presets-json')
    print("")
    return 0


if __name__ == "__main__":
    sys.exit(main())
