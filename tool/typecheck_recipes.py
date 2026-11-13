#!/usr/bin/env python3
"""跑一遍机型脚本的类型检查（#1247）：`recipes/*/*/recipe*.py` 逐份交给 mypy 的宽松档。

为什么不是一条 `mypy recipes`：43 份脚本都叫 `recipe.py`（另有 4 份版本变体），mypy 按
basename 取模块名，一次扫多份会报 `Duplicate module named 'recipe'`；目录名
（`xiaomi-M154FF`、`MEIZU 21 Pro`）也不是合法标识符，`--explicit-package-bases` 给不出唯一
模块名。所以这里逐份起一次 mypy，
每份单独成模块（模块名都叫 `recipe`，互不冲突）；`tool/` 走 `MYPYPATH` 当库目录，
脚本末尾 `if TYPE_CHECKING:` 块里那些注入名由各注入面模块的 `__getattr__` 认得。

范围与宽松档参数仍只在仓库根 `pyproject.toml` 的 `[tool.mypy]`：这一条只决定「怎么扫」，
不决定「扫得严不严」。`recipes/` 不进严格档名单（判据见 `dev.types.narrow-scope-in-config`）。

`gui/` 与 `tool/` 仍由不带参数的那条 `mypy` 负责；本脚本只管机型脚本。
横传的参数原样交给每一次 mypy（例如 `--no-incremental`）。
"""
import glob
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def recipes():
    """机型脚本清单：与事实层、对拍驱动同一口径（`recipes/<家族>/<型号>/…`，按路径排序）。

    每个型号目录出一份活脚本（`.py` 或 `.toml`，见 `recipe_meta.recipe_files`）；catalog 型号
    同目录的 `<型号>.py` 例外函数也在静态检查范围内，一并列出。"""
    files = []
    for model_dir in sorted(glob.glob(os.path.join(ROOT, "recipes", "*", "*"))):
        if not os.path.isdir(model_dir):
            continue
        py = sorted(glob.glob(os.path.join(model_dir, "recipe*.py")))
        if py:
            files += py
            continue
        tomls = sorted(glob.glob(os.path.join(model_dir, "*.toml")))
        files += tomls
        files += [os.path.splitext(path)[0] + ".py" for path in tomls
                  if os.path.isfile(os.path.splitext(path)[0] + ".py")]
    return files


def _check_python(path, tool_dir, argv, env):
    """跑一次 mypy（每份单独成模块，见模块 docstring）：返回 (失败?, 输出)。"""
    done = subprocess.run([sys.executable, "-m", "mypy", "--no-error-summary", *argv, path],
                          cwd=ROOT, env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    return bool(done.returncode), done.stdout, done.stderr


def _check_catalog(path):
    """`.toml` 不在 mypy 范围内（没有 Python），改走 catalog 的 schema 校验器：返回 (失败?, 报错)。"""
    sys.path.insert(0, os.path.join(ROOT, "tool"))
    import catalog
    import tomllib
    try:
        with open(path, "rb") as handle:
            data = tomllib.load(handle)
        catalog.validate(data)
    except (catalog.SchemaError, tomllib.TOMLDecodeError) as error:
        return True, f"{error}\n"
    finally:
        sys.path.pop(0)
    return False, ""


def main(argv):
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    files = recipes()
    if not files:
        print("recipes/ 下没有脚本：这条检查会空转")
        return 1
    tool_dir = os.path.join(ROOT, "tool")
    env = dict(os.environ)
    env["MYPYPATH"] = tool_dir + (os.pathsep + env["MYPYPATH"] if env.get("MYPYPATH") else "")
    failed = []
    for path in files:
        if path.endswith(".toml"):
            bad, output = _check_catalog(path)
            if bad:
                failed.append(os.path.relpath(path, ROOT))
                sys.stdout.write(output)
            continue
        bad, out, err = _check_python(path, tool_dir, argv, env)
        if bad:
            failed.append(os.path.relpath(path, ROOT))
            sys.stdout.write(out)
            sys.stderr.write(err)
    print(f"机型脚本类型检查：{len(files)} 份，{len(failed)} 份没过")
    for name in failed:
        print(f"  ✗ {name}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
