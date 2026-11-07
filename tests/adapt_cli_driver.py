"""起一次 tool/adapt.py：临时工作目录 + 用例给的种子文件，返回 rc / stdout / stderr。

基线生成器（tests/make_adapt_cli_baseline.py）与对拍测试都用它，
「同一批输入」的定义只有这一处。子进程以临时目录为 cwd，用例里的相对路径
（探路 TSV、勾选清单、输出文件名）因此原样出现在输出里。

只规范化 `OSError` 的系统文案：`写不出 …` 那条会把 `[Errno 2] No such file or
directory` 原样带进 stderr，这句由 C 库按平台与 LC_MESSAGES 翻译，不规范化的话
基线在别的机器上会红；errno 与路径码本身仍逐字比对。
"""
import os
import re
import subprocess
import sys
from pathlib import Path

DROP = ("AAC_EVENTS", "AAC_GUI", "AAC_PAUSE_FILE", "ADB", "ADBUTILS_ADB_PATH")
OSERR = re.compile(r"(\[Errno \d+\]) [^:\n]*:")


def normalize(text):
    return OSERR.sub(r"\1 <OSERR>:", text)


def run_once(repo_root, spec, work):
    """跑一条用例。work 是一个空的临时目录，调用方负责它的生命周期。"""
    work = Path(work)
    for name, content in spec["seed"].items():
        target = work / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k not in DROP}
    env["PYTHONIOENCODING"] = "utf-8"
    done = subprocess.run([sys.executable, os.path.join(os.fspath(repo_root), "tool", "adapt.py"), *spec["argv"]],
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          cwd=work, env=env, timeout=120)
    return {"rc": done.returncode, "stdout": normalize(done.stdout), "stderr": normalize(done.stderr)}
