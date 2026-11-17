"""起一次 tool/chan_fast.py：假设备（`tests/chan_cli_probe.py`）+ 临时备份目录，返回规范化后的结果。

基线生成器（`tests/make_chan_cli_baseline.py`）与对拍测试都用它，「同一批输入」的定义只有这一处。
子进程 cwd 是临时目录，用例里的清单路径因此是相对的；规范化只把临时目录的绝对路径换成 `<TMP>`。
"""
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROBE = HERE / "chan_cli_probe.py"
DROP = ("AAC_EVENTS", "AAC_GUI", "AAC_PAUSE_FILE", "AAC_CAPTURES", "ADB", "ADBUTILS_ADB_PATH")


def normalize(text, work):
    return text.replace(os.fspath(work), "<TMP>")


def run_once(repo_root, spec, work):
    """跑一条用例。work 是一个空的临时目录，调用方负责它的生命周期。"""
    work = Path(work)
    backups = work / "backups"
    backups.mkdir()
    if spec.get("hidden"):
        store = backups / f"ui-hidden-{spec.get('model', 'M1')}.tsv"
        store.write_text("".join(f"{pk}\t{cid}\n" for pk, cid in spec["hidden"]), encoding="utf-8")
    (work / "list.tsv").write_text(spec.get("items", ""), encoding="utf-8")
    (work / "spec.json").write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    out = work / "result.json"
    env = {k: v for k, v in os.environ.items() if k not in DROP}
    env.update(AAC_BACKUPS=str(backups), AAC_NO_SOUND="1", PYTHONIOENCODING="utf-8")
    done = subprocess.run(
        [sys.executable, "-I", str(PROBE), str(Path(repo_root) / "tool"), str(work / "spec.json"),
         str(out), str(work)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=work, env=env, timeout=120)
    if done.returncode != 0 or not out.is_file():
        raise RuntimeError(f"探针没有产出结果（rc={done.returncode}）：\n{done.stderr[-2000:]}")
    got = json.loads(out.read_text(encoding="utf-8"))
    got["stdout"] = normalize(got["stdout"], work)
    got["stderr"] = normalize(got["stderr"], work)
    got["guards"]["shells"] = [normalize(call, work) for call in got["guards"]["shells"]]
    return got
