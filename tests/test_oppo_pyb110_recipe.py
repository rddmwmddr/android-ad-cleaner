"""PYB110 机型脚本的商店段：「消息管理」是条件入口，缺了也不挡后面两条子路径（#1281）。

入口在首启时出现过、之后读不到，脚本保留可选探测；快照里这段停在 `in_settings_page`
（合成空页），所以两条分支只能靠这里守。段 action 的取法沿用 #1265。
"""
from pathlib import Path
import sys
import unittest
from unittest.mock import call

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))

from fixtures import load_recipe, phone_mock

RECIPE = ROOT / "recipes/oppo/PYB110/PYB110.toml"


def action(scope, name):
    return next(item.action for item in scope["rt"].steps if item.name == name)


class StoreStepTests(unittest.TestCase):
    def setUp(self):
        self.p = phone_mock(W=1272, H=2772)
        self.p.in_settings_page.return_value = True
        self.scope, _ = load_recipe(self.p, RECIPE)
        self.store = action(self.scope, "软件商店")

    def test_missing_message_entry_leaves_the_two_subpaths_intact(self):
        self.p.entry.return_value = False
        self.store()
        self.assertEqual(self.p.off.call_args_list, [
            call(keep=self.scope["STORE_KEEP"], page="商店·服务管理"),
            call(only=["个性化推荐"], page="商店·个性化推荐"),
        ])

    def test_present_message_entry_is_closed_before_service_management(self):
        self.p.entry.return_value = True
        self.store()
        self.assertEqual(self.p.off.call_args_list[0],
                         call(only=["热门内容推送"], page="商店·消息管理"))
        self.assertEqual(len(self.p.off.call_args_list), 3)
