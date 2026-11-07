"""子进程的文本模式必须写清解码方式（#684）。

text=True 却不定 encoding 时按平台码页解码：Windows 上是 cp1252 / cp936，对方吐出非 ASCII
就 UnicodeDecodeError，而 Linux 与 macOS 上跑一万遍都看不出来。
"""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPAWN = {"run", "Popen", "check_output", "check_call"}


def missing_decoder(source):
    """返回源码里 text=True 却缺解码参数的行号。"""
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
        if name not in SPAWN:
            continue
        keywords = {k.arg: k.value for k in node.keywords if k.arg}
        text = keywords.get("text")
        if not (isinstance(text, ast.Constant) and text.value is True):
            continue
        if "encoding" in keywords and "errors" in keywords:
            continue
        yield node.lineno


class TextModeTests(unittest.TestCase):
    def test_every_text_mode_spawn_declares_encoding_and_errors(self):
        offenders = []
        for folder in ("tool", "gui", "tests"):
            for path in sorted((ROOT / folder).rglob("*.py")):
                for line in missing_decoder(path.read_text(encoding="utf-8")):
                    offenders.append(f"{path.relative_to(ROOT).as_posix()}:{line}")
        self.assertEqual(offenders, [])

    def test_guard_flags_a_spawn_without_decoder(self):
        self.assertEqual(list(missing_decoder('subprocess.run([adb], text=True)\n')), [1])

    def test_guard_accepts_a_spawn_with_decoder(self):
        source = 'subprocess.run([adb], text=True, encoding="utf-8", errors="replace")\n'
        self.assertEqual(list(missing_decoder(source)), [])


if __name__ == "__main__":
    unittest.main()
