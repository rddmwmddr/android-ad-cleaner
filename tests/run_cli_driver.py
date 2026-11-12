"""起一次 tool/run.py：假 adb + 临时备份目录，返回规范化后的 rc / stdout / stderr。

基线生成器（tests/make_run_cli_baseline.py）与对拍测试都用它，
「同一批输入」的定义只有这一处。规范化只动三类东西：临时目录的绝对路径、
备份目录名里的时间戳（`Backups.create` 用 `%Y%m%d-%H%M`），以及 `status-json` 里从台账现读的
覆盖度 / 证据来源 / 验证日期——那三样跟着 `recipes/verified.toml` 的日常维护变，不是命令行为，
`tests/test_verify_ledger.py` 单独验它们的真实取值。
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FAKE_ADB = HERE / "fake_adb.py"
STAMP = re.compile(r"\d{8}-\d{4}")
LEDGER_FIELD = re.compile(r'("recipe_(?:coverage|evidence|verified)": )"(?:[^"\\]|\\.)*"')
DROP = ("AAC_EVENTS", "AAC_GUI", "AAC_PAUSE_FILE", "AAC_CAPTURES", "ADB", "ADBUTILS_ADB_PATH")


def _adb_wrapper(directory):
    """adb 必须是能直接 exec 的文件，所以套一层 sh；Windows 上没有这套，测试会跳过。"""
    path = Path(directory, "adb")
    path.write_text(f'#!/bin/sh\nexec "{sys.executable}" -S "{FAKE_ADB}" "$@"\n', encoding="utf-8")
    path.chmod(0o755)
    return path


def normalize(text, work):
    text = LEDGER_FIELD.sub(r'\1"<LEDGER>"', text)
    return STAMP.sub("<TS>", text.replace(os.fspath(work), "<TMP>"))


def run_once(repo_root, spec, work):
    """跑一条用例。work 是一个空的临时目录，调用方负责它的生命周期。"""
    work = Path(work)
    backups = work / "backups"
    backups.mkdir()
    for name, content in spec["seed"].items():
        target = backups / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    (work / "rules.json").write_text(json.dumps(spec["rules"], ensure_ascii=False), encoding="utf-8")
    (work / "state.json").write_text(json.dumps(spec["state"] or {"suspended": "false"}), encoding="utf-8")
    log = work / "log.jsonl"
    log.write_text("", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k not in DROP}
    env.update(ADB=str(_adb_wrapper(work)), AAC_BACKUPS=str(backups), FAKE_ADB_RULES=str(work / "rules.json"),
               FAKE_ADB_STATE=str(work / "state.json"), FAKE_ADB_LOG=str(log), PYTHONIOENCODING="utf-8")
    done = subprocess.run([sys.executable, os.path.join(os.fspath(repo_root), "tool", "run.py"), *spec["argv"]],
                          capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=180)
    seen = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line]
    return {"rc": done.returncode, "stdout": normalize(done.stdout, work),
            "stderr": normalize(done.stderr, work)}, seen
