"""打包后的冒烟测试：用和客户端一样的方式（管道接输出）启动命令行模式。
用法：python gui/smoke_test.py <打包后的可执行文件>"""
import subprocess, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tool"))
from stdio import use_utf8_console  # noqa: E402

use_utf8_console()
exe = sys.argv[1]
ok = True
hdc = subprocess.run([exe, "--smoke-harmony"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
print(hdc.stdout)
if hdc.returncode:
    print(hdc.stderr[-1500:])
ok &= hdc.returncode == 0 and "Harmony smoke:" in hdc.stdout
for args, expect in ((["run.py", "--help"], "run.py"), (["fast.py", "--help"], "fast.py"),
                     (["chan_fast.py", "--help"], "chan_fast.py"), (["run.py", "devices"], None)):
    r = subprocess.run([exe, "--cli", *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
    print(f"== {' '.join(args)}  rc={r.returncode}")
    print(r.stdout[:800])
    if r.stderr.strip():
        print("stderr:", r.stderr[-1500:])
    good = r.returncode == 0 and (expect in r.stdout if expect else ("没有连着的手机" in r.stdout or "\t" in r.stdout))
    print("通过" if good else "失败")
    ok &= good
with tempfile.TemporaryDirectory() as directory:
    missing = str(Path(directory, "missing-channels.tsv"))
    # 真实走 run.py → chan_fast.py 两层子进程；文件校验早于连接，不接触手机。
    r = subprocess.run([exe, "--cli", "run.py", "-s", "__aac_smoke__", "chan-off", missing],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=25)
    good = r.returncode != 0 and "missing-channels.tsv" in r.stderr and "[PYI-" not in r.stderr
    print(f"== 两层 CLI 分发与失败退出：{'通过' if good else '失败'} rc={r.returncode}")
    ok &= good
if "--gui" in sys.argv[2:]:
    r = subprocess.run([exe, "--smoke-gui"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90)
    print(f"== GUI 页面与 JS API  rc={r.returncode}")
    print(r.stdout)
    if r.stderr.strip():
        print("stderr:", r.stderr[-1500:])
    ok &= r.returncode == 0 and "GUI smoke:" in r.stdout
sys.exit(0 if ok else 1)
