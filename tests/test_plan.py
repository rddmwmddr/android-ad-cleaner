"""#1105：一次执行跑哪些步骤的规格——八个键、默认值、宽容收、与 JSON 往返。"""
import dataclasses
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
import plan as plan_module

Plan = plan_module.Plan

# 冻结的键集合：只遍历 Plan 自己的字段时，删掉一个键连样例一起消失，用例照样绿。
FROZEN_KEYS = {"backup", "model", "steps", "ref", "channels", "quickapp", "ads", "finish"}


def keys_of(instance):
    return {f.name for f in dataclasses.fields(instance)}


class DefaultsTests(unittest.TestCase):
    def test_a_bare_plan_is_a_first_run(self):
        p = Plan()
        self.assertTrue(p.backup)
        self.assertTrue(p.finish)
        self.assertEqual((p.steps, p.channels, p.ads), ([], [], []))
        self.assertFalse(p.ref)
        self.assertFalse(p.quickapp)
        self.assertEqual(p.model, "")

    def test_the_spec_holds_exactly_the_eight_keys(self):
        self.assertEqual(keys_of(Plan()), FROZEN_KEYS)

    def test_an_empty_payload_is_a_first_run(self):
        self.assertEqual(Plan.from_json({}), Plan())


class FromJsonTests(unittest.TestCase):
    def test_missing_keys_take_their_defaults(self):
        p = Plan.from_json({"backup": False})
        self.assertFalse(p.backup)
        self.assertTrue(p.finish, "没收到的键取默认，不跟着相邻的键一起关")
        self.assertEqual(p.steps, [])

    def test_unknown_keys_are_ignored(self):
        self.assertEqual(Plan.from_json({"nope": 1, "backup": False}).to_json(),
                         Plan(backup=False).to_json())

    def test_values_are_coerced_to_the_declared_shape(self):
        p = Plan.from_json({"backup": 0, "model": 5, "steps": None, "ref": "",
                            "channels": ({"pkg": "p"},), "quickapp": 1, "ads": None, "finish": "x"})
        self.assertIs(p.backup, False)
        self.assertIs(p.finish, True)
        self.assertIs(p.quickapp, True)
        self.assertIs(p.ref, False)
        self.assertEqual(p.model, "5")
        self.assertEqual(p.steps, [])
        self.assertEqual(p.ads, [])
        self.assertEqual(p.channels, [{"pkg": "p"}])
        self.assertIsInstance(p.channels, list)

    def test_a_string_in_a_list_field_is_dropped_not_split_into_characters(self):
        p = Plan.from_json({"steps": "桌面", "ads": "com.a"})
        self.assertEqual((p.steps, p.ads), ([], []))

    def test_direct_construction_lands_on_the_same_shape(self):
        p = Plan(steps=None, channels=None, ads=None)
        self.assertEqual((p.steps, p.channels, p.ads), ([], [], []))

    def test_a_plan_is_returned_as_is(self):
        p = Plan(steps=["桌面"], ads=["com.a"])
        self.assertIs(Plan.from_json(p), p)


class RoundTripTests(unittest.TestCase):
    def full(self):
        return Plan(backup=False, model="M", steps=["桌面", "商店"], ref=True,
                    channels=[{"pkg": "p", "id": "1", "name": "活动"}], quickapp=True,
                    ads=["com.a"], finish=False)

    def test_json_round_trips(self):
        p = self.full()
        self.assertEqual(Plan.from_json(p.to_json()), p)

    def test_the_json_shape_is_the_eight_keys(self):
        self.assertEqual(set(self.full().to_json()), FROZEN_KEYS)

    def test_to_json_copies_so_callers_cannot_mutate_the_plan_through_it(self):
        p = self.full()
        p.to_json()["steps"].append("快应用")
        self.assertEqual(p.steps, ["桌面", "商店"])


if __name__ == "__main__":
    unittest.main()
