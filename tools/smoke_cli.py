"""Smoke test for the CLI surface (run manually; part of `python tools/smoke_cli.py`)."""

from __future__ import annotations

import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable


def run(args):
    env = dict(os.environ)
    env["PYTHONPATH"] = os.path.join(ROOT, "src")
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run([PY, "-m", "word_format_applier", *args], cwd=ROOT, env=env,
                          capture_output=True, text=True, encoding="utf-8")
    return proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "").strip()


def main() -> int:
    code, out, _ = run(["--list-presets"])
    print("[list-presets]", code, out.splitlines()[:1])
    assert code == 0 and "格式要求1" in out

    code, out, _ = run(["--list-presets-json"])
    payload = json.loads(out)
    assert payload["count"] >= 3, payload
    print("[list-presets-json] count =", payload["count"])

    code, out, _ = run(["--target", "samples/target.docx", "--preset", "格式要求1",
                        "--output", "samples/cli-out.docx", "--json"])
    summary = json.loads(out)
    print("[apply]", json.dumps(summary, ensure_ascii=False))
    assert code == 0 and summary["ok"] and summary["text_unchanged"]
    assert summary["llm_calls"] == 0 and summary["used_preset"] == "格式要求1"

    code, out, _ = run(["--target", "samples/target.docx", "--format", "preset:格式要求3",
                        "--output", "samples/cli-out3.docx", "--dry-run", "--json"])
    summary = json.loads(out)
    print("[dry-run]", json.dumps(summary, ensure_ascii=False))
    assert code == 0 and not os.path.exists(os.path.join(ROOT, "samples", "cli-out3.docx"))

    code, out, _ = run(["--target", "samples/target.docx", "--preset", "不存在的预设", "--json"])
    print("[missing preset]", code, out[:160])
    assert code == 1 and "不存在的预设" in out

    code, out, _ = run(["--print-rules", "--preset", "格式要求3"])
    print("[print-rules]", json.loads(out)["rule_count"])
    assert code == 0

    print("CLI SMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
