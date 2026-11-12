"""工具层共用的 `gh` 会话（tool/gh.py，ADR-0036）：跑命令那一行取哪一路文本，判 JSON 的三档报错。

调用方的用例注入假 runner，只看得到「取到了 / 抛 GhError」；这个文件直接对着 `call` 与
`json_of` 的边界跑，失败一档一档分开验。`tool/gh.py` 在基线 `0f1f0fe` 就已在（#1217、#1218），
所以每条用例在旧树上也绿——守的是不回退，不是那次迁移本身。

这里的假件不复用 `fixtures.FakeRunner`：那是带 `.run()` 的客户端对象，而 `tool/gh.py` 的注入面
是一个裸可调用体 `(script, *args) -> (标准输出, 错误输出, 返回码)`，两者形状不同。
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))

import gh  # noqa: E402


def runner(output="", error="", code=0):
    """一个只说结局的 runner：每次调用都回同一组 (标准输出, 错误输出, 返回码)。"""
    return lambda script, *args: (output, error, code)


def missing(script, *args):
    """没装 `gh` 的机器：起进程这一步就失败。"""
    raise FileNotFoundError("gh 不在 PATH 上")


class CallTests(unittest.TestCase):
    def test_success_takes_stdout(self):
        text, code = gh.call(runner("  open\n"), "issue", "list")
        self.assertEqual((text, code), ("open", 0))

    def test_failure_takes_stderr(self):
        text, code = gh.call(runner("", "could not resolve host\n", 1), "issue", "list")
        self.assertEqual((text, code), ("could not resolve host", 1))

    def test_failure_without_stderr_falls_back_to_stdout(self):
        text, code = gh.call(runner("no such label\n", "", 1), "issue", "list")
        self.assertEqual((text, code), ("no such label", 1))

    def test_missing_gh_is_a_gh_error(self):
        with self.assertRaises(gh.GhError) as caught:
            gh.call(missing, "issue", "list")
        self.assertIn("跑不了 gh", str(caught.exception))


class JsonTests(unittest.TestCase):
    def test_output_is_parsed(self):
        self.assertEqual(
            gh.json_of(runner('[{"number": 7}]'), "issue", "list", source="票"),
            [{"number": 7}])

    def test_missing_gh_is_a_gh_error(self):
        with self.assertRaises(gh.GhError) as caught:
            gh.json_of(missing, "issue", "list", source="停摆扫描")
        self.assertIn("跑不了 gh", str(caught.exception))

    def test_nonzero_exit_names_the_source(self):
        with self.assertRaises(gh.GhError) as caught:
            gh.json_of(runner("", "gh: auth required\n", 4), "issue", "list", source="停摆扫描")
        self.assertIn("停摆扫描 退出码非零", str(caught.exception))
        self.assertIn("auth required", str(caught.exception))

    def test_nonzero_exit_without_text_still_says_something(self):
        with self.assertRaises(gh.GhError) as caught:
            gh.json_of(runner("", "", 2), "issue", "list", source="复测队列")
        self.assertIn("gh 返回非零", str(caught.exception))

    def test_output_that_is_not_json(self):
        with self.assertRaises(gh.GhError) as caught:
            gh.json_of(runner("not json\n"), "issue", "list", source="复测队列")
        self.assertIn("复测队列 的输出不是 JSON", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
