"""tool/ 下哪些模块会随 APK 发到手机上，由目录与两份冻结名单回答（ADR-0041）。

边界：`tool/` = 出厂引擎（随包发到手机上），`devtools/` = 仓库工具链（只在 CI 与本机跑）。
本段（#1390）不动物理布局，只冻结名单与可达性：`syncEngine` 是整目录 glob，往 `tool/`
放一个新脚本它就会自动进包，于是「会不会随包」必须由目录本身回答，并由这里的三条用例在
漂移时立刻报红。判据是文件系统与 import 后的 `sys.modules`，不写 AST 扫——那是与书写形态
耦合（同 C2a / C3 / #1280 的既有判据）。

三条用例各守一件事：文件系统与冻结名单全等、引擎不拖进工具链、打包清单不含 `devtools/`。
"""
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GRADLE = ROOT / "android" / "app" / "build.gradle.kts"

# 出厂引擎：随 APK 发到手机上，手机版与桌面版同一份（名单逐字来自 #1389 的「实现决定」）。
ENGINE = frozenset({
    "run", "fast", "chan_fast", "adapt", "explore", "huawei_channels", "adb_link", "backups",
    "captures", "channel_policy", "coverage_note", "diagnostics", "entries", "events", "host",
    "plan", "polarity", "reader", "recipe_audit", "recipe_kit", "recipe_loader", "recipe_meta",
    "recipe_nav", "recipe_pick", "recipe_runtime", "recipe_source", "recipe_steps",
    "recipe_strategies", "row", "stdio", "summary", "troubleshooting", "ui_hidden", "ui_session",
    "verify_ledger", "vocab", "wait",
})
# 仓库工具链：只在 CI 与本机跑，不随包（第二段搬进 devtools/，名单内容不变）。
TOOLCHAIN = frozenset({
    "check_comment_tickets", "check_conventional", "check_dco", "check_ticket_ref", "claim",
    "commits", "followup", "gen_adr_index", "gen_brand_taps", "gen_site_css", "gh", "glob_scan",
    "release_assets", "release_meta", "stale", "test_anchors", "triage_audit",
    "typecheck_recipes", "unittest_summary",
})
# 引擎的两个子包整体算引擎；逐个 import 时一并带上。
ENGINE_PACKAGES = ("phone", "catalog")

# 在独立解释器里 import 引擎模块，再把「出现在 sys.modules 里的工具链模块名」打到 stdout。
# 用子进程是因为主测试进程里别的用例早已 import 过工具链模块，sys.modules 会被污染。
_PROBE = (
    "import importlib, sys\n"
    "sys.path.insert(0, sys.argv[1])\n"
    "rest = sys.argv[2:]\n"
    "cut = rest.index('--toolchain--')\n"
    "engine, chain = rest[:cut], rest[cut + 1:]\n"
    "for name in engine:\n"
    "    importlib.import_module(name)\n"
    "for name in chain:\n"
    "    if name in sys.modules:\n"
    "        print(name)\n"
)


class ToolPackageSeamTests(unittest.TestCase):
    def test_module_lists_match_the_filesystem(self):
        """`tool/` 下的顶层 `.py` 与两份冻结名单全等：无交、无遗漏、无多余。

        往 `tool/` 放一个本来不该随包的脚本，它会经 `syncEngine` 的整目录 glob 自动进 APK；
        这条断言把「路径 = 归属」变成可执行的棘轮。"""
        present = {path.stem for path in (ROOT / "tool").glob("*.py")}
        self.assertEqual(ENGINE & TOOLCHAIN, frozenset(), "ENGINE 与 TOOLCHAIN 有交集，一个模块不能既随包又不随包")
        self.assertEqual(len(ENGINE | TOOLCHAIN), 56, "两份名单合计应是 56 个顶层模块，别同时把它们改小")
        extra = sorted(present - (ENGINE | TOOLCHAIN))
        self.assertEqual(
            extra, [],
            f"tool/ 下出现名单外的顶层模块：{'、'.join(extra)}。放进名单要同时改这张表与 ADR-0041；"
            "不该随包或不该存在的，删掉或挪走。")
        missing = sorted((ENGINE | TOOLCHAIN) - present)
        self.assertEqual(
            missing, [],
            f"名单里这些顶层模块在 tool/ 下不存在：{'、'.join(missing)}。删掉登记或恢复文件。")

    def test_engine_modules_do_not_import_the_toolchain(self):
        """逐个 import 37 个引擎模块与两个子包后，`sys.modules` 里不得出现任何工具链模块。

        引擎 import 了某个工具链模块，那个模块就会随包发到手机上——正是第二段搬移前要钉住的
        方向：依赖只许「工具链 → 引擎」。"""
        engine = sorted(ENGINE) + list(ENGINE_PACKAGES)
        proc = subprocess.run(
            [sys.executable, "-I", "-c", _PROBE, str(ROOT / "tool"),
             *engine, "--toolchain--", *sorted(TOOLCHAIN)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
        )
        self.assertEqual(
            proc.returncode, 0,
            "引擎模块 import 时就抛异常（这也是红，说明某个引擎模块已经坏了）：\n" + proc.stderr[-2000:])
        leaked = proc.stdout.split()
        self.assertEqual(
            leaked, [],
            f"引擎模块 import 了工具链模块：{'、'.join(leaked)}。那个模块会随包发到手机上，"
            "把这条依赖反过来（工具链 → 引擎）或把模块挪出 tool/。")

    def test_packaging_does_not_ship_the_toolchain(self):
        """打包清单不含 `devtools/`。

        此刻是前瞻性断言，第二段把工具链搬进 `devtools/` 后才真正承重：`syncEngine` 与
        `gui.bundle_data` 都不该把仓库工具链收进 APK。"""
        gradle = GRADLE.read_text(encoding="utf-8")
        self.assertNotIn(
            'resolve("devtools")', gradle,
            "构建脚本开始拷 devtools/ 了：仓库工具链只在 CI 与本机跑，不该随 APK 发到手机上（ADR-0041）。")
        from gui.bundle_data import bundle_data
        shipped = {Path(source).relative_to(ROOT).as_posix() for source, _directory in bundle_data(ROOT)}
        leaked = sorted(rel for rel in shipped if rel == "devtools" or rel.startswith("devtools/"))
        self.assertEqual(
            leaked, [],
            f"桌面打包清单收录了 devtools/ 下的文件：{'、'.join(leaked)}。"
            "仓库工具链只在 CI 与本机跑（ADR-0041）。")


if __name__ == "__main__":
    unittest.main()
