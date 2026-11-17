"""tool/ 只留出厂引擎、devtools/ 是仓库工具链：边界由目录与两份冻结名单回答（ADR-0041）。

`tool/` = 出厂引擎（随包发到手机上），`devtools/` = 仓库工具链（只在 CI 与本机跑）。搬移（#1391）
已完成：`syncEngine` 是整目录 glob，往 `tool/` 放一个新脚本它就会自动进包，于是「会不会随包」必须
由目录本身回答，并由这里的三条用例在漂移时立刻报红。判据是文件系统与 import 后的 `sys.modules`，
不写 AST 扫——那是与书写形态耦合（同 C2a / C3 / #1280 的既有判据）。

三条用例各守一件事：两个目录与冻结名单各自全等、引擎不拖进工具链、打包清单不含 `devtools/`。
"""
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GRADLE = ROOT / "android" / "app" / "build.gradle.kts"

# 出厂引擎：留在 tool/，随 APK 发到手机上（名单逐字来自 #1389 的「实现决定」）。
ENGINE = frozenset({
    "run", "fast", "chan_fast", "adapt", "explore", "huawei_channels", "adb_link", "backups",
    "captures", "channel_arrive", "channel_batch", "channel_decide", "channel_policy", "channel_toggle",
    "coverage_note",
    "diagnostics", "entries",
    "events", "geometry", "host", "plan", "polarity", "reader", "recipe_audit", "recipe_kit",
    "recipe_loader", "recipe_meta", "recipe_nav", "recipe_pick", "recipe_runtime",
    "recipe_source", "recipe_steps", "recipe_strategies", "row", "screen_snapshot", "stdio",
    "summary", "troubleshooting", "ui_hidden", "ui_session",
    "verify_ledger", "vocab", "wait",
})
# 仓库工具链：搬进 devtools/，只在 CI 与本机跑、不随包（#1390 冻结的 19 项，加上 #1411 的
# mutation / mutation_scope、#1477 的 script_surface）。
TOOLCHAIN = frozenset({
    "check_comment_tickets", "check_conventional", "check_dco", "check_ticket_ref", "claim",
    "commits", "followup", "gen_adr_index", "gen_brand_taps", "gen_site_css", "gh", "glob_scan",
    "mutation", "mutation_scope", "release_assets", "release_meta", "script_surface", "stale",
    "test_anchors", "triage_audit", "typecheck_recipes", "unittest_summary",
})
# 引擎的两个子包整体算引擎；逐个 import 时一并带上。
ENGINE_PACKAGES = ("phone", "catalog")

# 在独立解释器里 import 引擎模块，再打出两类污染：`bare:` 是出现在 sys.modules 里的工具链裸名，
# `pkg:` 是 devtools 包自身。用子进程是因为主测试进程里别的用例早已 import 过工具链模块。
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
    "        print('bare:' + name)\n"
    "for name in list(sys.modules):\n"
    "    if name == 'devtools' or name.startswith('devtools.'):\n"
    "        print('pkg:' + name)\n"
)


class ToolPackageSeamTests(unittest.TestCase):
    def test_module_lists_match_the_filesystem(self):
        """`tool/` 顶层 `.py` 恰好是引擎名单，`devtools/` 顶层恰好是工具链名单。

        往 `tool/` 放一个本来不该随包的脚本，它会经 `syncEngine` 的整目录 glob 自动进 APK；
        这条断言把「路径 = 归属」变成可执行的棘轮。`devtools/` 还得是真包，包导入才立得住。"""
        self.assertEqual(ENGINE & TOOLCHAIN, frozenset(), "ENGINE 与 TOOLCHAIN 有交集，一个模块不能既随包又不随包")
        engine_present = {path.stem for path in (ROOT / "tool").glob("*.py")}
        extra = sorted(engine_present - ENGINE)
        self.assertEqual(
            extra, [],
            f"tool/ 下出现引擎名单外的顶层模块：{'、'.join(extra)}。放进 tool/ 就会随包发到手机上，"
            "该在仓库侧跑的搬到 devtools/，确属引擎的登记进名单并同时改 ADR-0041。")
        missing = sorted(ENGINE - engine_present)
        self.assertEqual(
            missing, [],
            f"名单里这些引擎模块在 tool/ 下不存在：{'、'.join(missing)}。删掉登记或恢复文件。")

        # `syncEngine` 与 `gui.bundle_data` 都是整目录递归收，子目录里的新文件一样会进包。
        subdirs = {path.relative_to(ROOT / "tool").parts[0]
                   for path in (ROOT / "tool").rglob("*.py")
                   if len(path.relative_to(ROOT / "tool").parts) > 1}
        self.assertEqual(
            subdirs, set(ENGINE_PACKAGES),
            f"tool/ 下出现名单外的子目录：{'、'.join(sorted(subdirs - set(ENGINE_PACKAGES)))}。"
            "整目录 glob 会把它一起收进 APK；登记成引擎子包并同时改 ADR-0041，或搬到 devtools/。")

        self.assertTrue(
            (ROOT / "devtools" / "__init__.py").is_file(),
            "devtools/ 必须是真包（有 __init__.py），否则 `from devtools.claim import …` 立不住。")
        chain_present = {path.stem for path in (ROOT / "devtools").glob("*.py")} - {"__init__"}
        extra = sorted(chain_present - TOOLCHAIN)
        self.assertEqual(
            extra, [],
            f"devtools/ 下出现工具链名单外的顶层模块：{'、'.join(extra)}。"
            "登记进名单并同时改 ADR-0041；该随包的放进 tool/ 的引擎名单。")
        missing = sorted(TOOLCHAIN - chain_present)
        self.assertEqual(
            missing, [],
            f"名单里这些工具链模块在 devtools/ 下不存在：{'、'.join(missing)}。删掉登记或恢复文件。")

    def test_engine_modules_do_not_import_the_toolchain(self):
        """逐个 import `tool/` 全部模块（含两个子包）后，`sys.modules` 里既没有工具链裸名，
        也没有 `devtools` 或 `devtools.*`。

        引擎 import 了某个工具链模块，那个模块就会随包发到手机上——依赖只许「工具链 → 引擎」。"""
        engine = sorted(ENGINE) + list(ENGINE_PACKAGES)
        proc = subprocess.run(
            [sys.executable, "-I", "-c", _PROBE, str(ROOT / "tool"),
             *engine, "--toolchain--", *sorted(TOOLCHAIN)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
        )
        self.assertEqual(
            proc.returncode, 0,
            "引擎模块 import 时就抛异常（这也是红，说明某个引擎模块已经坏了）：\n" + proc.stderr[-2000:])
        leaked, packages = [], []
        for line in proc.stdout.splitlines():
            if line.startswith("bare:"):
                leaked.append(line.removeprefix("bare:"))
            elif line.startswith("pkg:"):
                packages.append(line.removeprefix("pkg:"))
        self.assertEqual(
            leaked, [],
            f"引擎模块 import 了工具链模块：{'、'.join(leaked)}。那个模块会随包发到手机上，"
            "把这条依赖反过来（工具链 → 引擎）或把模块挪出 tool/。")
        self.assertEqual(
            packages, [],
            f"引擎模块把 devtools 拉进来了：{'、'.join(packages)}。仓库工具链不随包，"
            "引擎侧不许 import 它（ADR-0041）——把这条依赖反过来或挪出引擎目录。")

    def test_packaging_does_not_ship_the_toolchain(self):
        """打包清单不含 `devtools/`。

        `syncEngine` 与 `gui.bundle_data` 都按 `tool/` 整目录收，仓库工具链只在 CI 与本机跑，
        不该随 APK 发到手机上——这条断言守的就是那个方向。"""
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
