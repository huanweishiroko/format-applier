# diag_env.py
import os
from pathlib import Path
from dotenv import load_dotenv, find_dotenv

# 从 parser/ 目录向上找
found = find_dotenv()
print("find_dotenv ->", found)

loaded = load_dotenv()
print("load_dotenv ->", loaded)

for k in ["OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_MODEL"]:
    v = os.getenv(k)
    if v is None:
        print(f"{k} = <None>")
    else:
        # 只显示长度和前 6 位
        print(f"{k} = len={len(v)}, first6={v[:6]!r}, last1={v[-1]!r}")
