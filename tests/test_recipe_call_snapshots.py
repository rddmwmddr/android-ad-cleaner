"""机型脚本的调用序列快照（#1239）：回归里对当前树逐条比对入库快照，不建基线 worktree、不起子进程。

判据是「同一份合成手机、同一组读屏观察下，脚本发出的调用逐条相同」：47 份脚本 × `present` /
`absent` 两个场景各记一遍，每一份的每个场景都要有调用量。快照是数据，随 PR 一起审阅。

更新规则见 docs/agents/recipe-snapshots.md：只有行为确实该变的 PR 才能动快照，正文要写清
哪几份、哪几段、为什么 —— 快照不是让 CI 变绿的橡皮章。
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "tool"))

import compare_recipe_calls as driver  # noqa: E402

# 一轮装载 47 份 × 2 场景约 1.3 万条调用（0.5 秒上下）：整轮只装一次，几条用例共用
_CURRENT = None


def current():
    """当前树的调用序列。"""
    global _CURRENT
    if _CURRENT is None:
        _CURRENT = driver.dump(ROOT)
    return _CURRENT


class CoverageTests(unittest.TestCase):
    """快照与脚本一一对应，且记到的是「哪一段发出的哪一条」。"""

    def test_every_recipe_has_a_snapshot_and_the_other_way_round(self):
        """新机型没记快照、删脚本没删快照，都要红：否则守卫悄悄少守一份。"""
        scripts = driver.scripts()
        self.assertGreaterEqual(len(scripts), 47, "脚本没扫到：路径或通配写错了")
        snapshots = driver.read_snapshots()
        missing = sorted(set(scripts) - set(snapshots))
        stale = sorted(set(snapshots) - set(scripts))
        self.assertEqual(missing, [], "这些脚本没有快照：python tests/compare_recipe_calls.py --write")
        self.assertEqual(stale, [], "这些快照没有对应的脚本了：重新 --write 会把它们删掉")

    def test_each_snapshot_file_name_is_derived_from_its_script(self):
        """文件名由脚本路径算出来：改了脚本位置而漏写快照时，报错指向的是能 grep 到的那份。"""
        for script in driver.scripts():
            path = driver.SNAPSHOTS / driver.snapshot_name(script)
            self.assertTrue(path.is_file(), f"{script} 的快照文件名应是 {path.name}")
            found = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(found["script"], script, f"{path.name} 里写的是 {found['script']}")

    def test_the_calls_carry_the_segment_they_came_from(self):
        """段名来自前导的 `step`：那一层换掉时归属会全部掉到空串，这条用例先红。"""
        calls = current()["recipes/xiaomi/24090RA29C/24090RA29C.toml"]["present"]
        segments = [call[0] for call in calls]
        self.assertIn("系统广告", segments)
        self.assertEqual(segments.count(""), 0, "每条调用都该落在某个段里")


class ComparisonTests(unittest.TestCase):
    """当前树 vs 入库快照：逐条相同，且每份脚本的每个场景都记到了调用。"""

    # Windows 上同一份假页面、同一份代码会多出 1–2 轮「聚焦 / 锁屏」探针（沿用 #1239 的已知缺口：
    # 还有一处等待循环用着定义时绑死的真实时钟，慢机器上多转一圈）。本机 macOS 的 3.12 / 3.13
    # 与两种假钟速度都逐条相同，所以差异只在 Windows；把那一处也注入假钟之前，这条只在 POSIX 比对。
    @unittest.skipIf(sys.platform == "win32", "快照的探针轮数在 Windows 上还不稳定（沿用 #1239 的缺口）")
    def test_the_call_sequences_match_the_snapshots(self):
        found, total = driver.problems(driver.read_snapshots(), current())
        self.assertEqual(found, [], "\n\n".join(f"{summary}\n{detail}" for summary, detail in found))
        self.assertGreaterEqual(total, driver.MIN_CALLS)

    def test_a_hollow_recording_refuses_to_overwrite_the_snapshots(self):
        """记录空转时 --write 拒绝落盘：否则一轮坏记录变成同样坏掉的基线，从此两边一样、永远绿。"""
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "recipe_calls"
            folder.mkdir()
            existing = folder / "keep.json"
            existing.write_text("{}", encoding="utf-8")
            hollow = {"a.py": {"present": [], "absent": []}}
            self.assertNotEqual(driver.write_snapshots(hollow, folder), 0)
            self.assertEqual([path.name for path in folder.iterdir()], ["keep.json"],
                             "空转的一轮不该落盘，也不该删掉已有快照")

    def test_drift_reports_the_script_the_segment_and_the_calls(self):
        """比对失败时的报错要能定位：哪一份、哪一段、第几条起不同（带两边上下文）。"""
        calls = [["段甲", "start", ["com.example.app"], {}]]
        before = {"a.py": {"present": calls, "absent": calls}}
        after = {"a.py": {"present": calls + [["段乙", "click", [1, 2], {}]], "absent": calls}}
        found, _ = driver.problems(before, after)
        summary, detail = found[0]
        self.assertTrue(summary.startswith("a.py[present]"), summary)
        self.assertIn("段乙", summary)
        self.assertIn("第 2 条起不同", detail)
        self.assertIn("click", detail)


if __name__ == "__main__":
    unittest.main()
