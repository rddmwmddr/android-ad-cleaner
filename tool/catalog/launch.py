"""catalog `start` op 的拉起命令（#1473）：把数据里的形状拼成一条 `am start` / `monkey`。

形状只在这里拼一次。数据里手写的 `am start` 迁进 op 时（#1478）要的是**逐字节相同**的下发命令，
所以这个模块是那份等价性的唯一 owner：解释器与事实层都读它，谁也不在别处再拼一遍。
"""
import shlex

CLEAR_TASK = "0x10008000"
# `flags` 的白名单：只放行数据里真出现过、且与清栈标志能同时用的那一个。
LAUNCH_FLAGS = frozenset({"--windowingMode"})
# 只有它们能把 `start` 从 `p.start` 那条路（落点校验、关弹窗）拉到原始命令上。
SHAPE_KEYS = ("action", "data", "flags", "clear_task", "launcher")


def launches_by_command(op):
    """这条 `start` 是拼命令还是走 `p.start`：写了任何形状键就只能拼命令。

    裸启动、窗口模式与 monkey 都不是 `p.start` 能表达的；也不该把它们塞进去——`p.start` 会等落点、
    关弹窗，而下发序列要跟数据里原来那条命令逐条相同（#1478 的对拍口径）。"""
    return any(key in op for key in SHAPE_KEYS)


def launch_command(op):
    """一条 `start` op 在手机上执行的命令。裸启动（`clear_task = false`）不带清栈参数。

    `-d` 的 URI 一律单引号包起来：数据里原来那两条就是 `-d 'gs://…'`，包起来既与迁移前的字面量
    逐字节相同，也不会让 `&` 之类的字符在设备端被再解释一次。`-n` 的页面名交 `shlex.quote`，
    与 `Launcher._launch` 同一条口径（vivo 的页面名带 `$`）。"""
    if op.get("launcher"):
        return f"monkey -p {op['pkg']} -c android.intent.category.LAUNCHER 1"
    parts = ["am start"]
    if "flags" in op:
        parts.append(op["flags"])
    if op.get("clear_task", True):
        parts += ["-f", CLEAR_TASK]
    if "action" in op:
        parts += ["-a", op["action"]]
    if "data" in op:
        parts.append(f"-d '{op['data']}'")
    if "pkg" in op:
        if "activity" in op:
            parts += ["-n", shlex.quote(op["pkg"] + "/" + op["activity"])]
        else:
            parts += ["-p", op["pkg"]]
    return " ".join(parts)
