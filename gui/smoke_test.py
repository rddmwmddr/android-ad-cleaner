"""打包后的冒烟测试：用和客户端一样的方式（管道接输出）启动命令行模式。
用法：python gui/smoke_test.py <打包后的可执行文件>"""
import subprocess, sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
exe = sys.argv[1]
ok = True
for args, expect in ((["run.py", "--help"], "run.py"), (["run.py", "devices"], None)):
    r = subprocess.run([exe, "--cli", *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
    print(f"== {' '.join(args)}  rc={r.returncode}")
    print(r.stdout[:800])
    if r.stderr.strip():
        print("stderr:", r.stderr[-1500:])
    good = r.returncode == 0 and (expect in r.stdout if expect else ("没有连着的手机" in r.stdout or "\t" in r.stdout))
    print("通过" if good else "失败")
    ok &= good
if "--gui" in sys.argv[2:]:
    r = subprocess.run([exe, "--smoke-gui"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90)
    print(f"== GUI 页面与 JS API  rc={r.returncode}")
    print(r.stdout)
    if r.stderr.strip():
        print("stderr:", r.stderr[-1500:])
    ok &= r.returncode == 0 and "GUI smoke:" in r.stdout
sys.exit(0 if ok else 1)
