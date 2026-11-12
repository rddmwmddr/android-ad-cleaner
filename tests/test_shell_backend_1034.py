"""#1034：手机版后端没就绪时给的那两句文案，仍要被 Python 侧判成「命令服务断线」这一族。

文案的单一来源是 Kotlin 的 `ShellBackend.NO_BACKEND` / `NO_WIRELESS`，Python 只认「命令服务不可用」这个前缀。
两条用例都是守卫：前一条守两侧文案不漂移，后一条守分类不回退——旧树也绿，守的不是这次修复生效。
"""
from pathlib import Path
import unittest

from fixtures import load_tool

load_tool()
import adb_link

ROOT = Path(__file__).resolve().parents[1]
KT = ROOT / "android/app/src/main/java/com/ahuamiao/adcleaner/ShellBackend.kt"
NO_BACKEND = ("命令服务不可用：Shizuku 没在运行或没有授权，内置无线调试也没有连上。"
              "启动 Shizuku，或到「开发者选项」把「无线调试」关掉再打开")
NO_WIRELESS = "命令服务不可用：内置无线调试没有连上，到「开发者选项」把「无线调试」关掉再打开"


class BackendMissingTextTests(unittest.TestCase):
    def test_both_sentences_are_carried_by_the_kotlin_source(self):
        source = KT.read_text(encoding="utf-8")
        for text in (NO_BACKEND, NO_WIRELESS):
            self.assertIn(text, source)

    def test_both_sentences_still_read_as_a_disconnect(self):
        for text in (NO_BACKEND, NO_WIRELESS):
            self.assertTrue(adb_link.lib_gone(text), text)
