"""#973：选择页「挂起广告组件」的默认值来自 status-json 的 `default_on`。

小米族的两个 msa 包在**未挂起**时默认勾上（直接开始就挂，省掉 OS4 主题段被开屏窗
打断的首轮）；已挂起的不预勾（走「广告组件已经挂起」的跳过行）；其他品牌维持不勾。
判据只认包名，不按 brand 字段或机型字符串。
"""
import unittest

from test_issue_regressions import AdPackagesHarness


class MsaDefaultTests(AdPackagesHarness, unittest.TestCase):
    """国行包（本 harness 的 INSTALLED 只有 com.miui.systemAdSolution）。"""

    def ads(self, brand, suspended=False):
        return {a["pkg"]: a for a in self.status_json(brand, suspended=suspended)["ads"]}

    def test_unsuspended_china_msa_is_default_on(self):
        self.assertIs(self.ads("Redmi")["com.miui.systemAdSolution"]["default_on"], True)

    def test_already_suspended_msa_is_not_default_on(self):
        """预勾与否在引擎侧就算好：已挂起的项不给勾选框，消费者不必再读 suspended。"""
        self.assertIs(self.ads("Redmi", suspended=True)["com.miui.systemAdSolution"]["default_on"], False)


class OtherBrandDefaultTests(AdPackagesHarness, unittest.TestCase):
    INSTALLED = ("com.opos.ads", "com.heytap.pictorial")

    def test_oppo_ads_stay_off_by_default(self):
        ads = {a["pkg"]: a for a in self.status_json("OPPO")["ads"]}
        self.assertIs(ads["com.opos.ads"]["default_on"], False)
        self.assertIs(ads["com.heytap.pictorial"]["default_on"], False)


class DefaultOnTableTests(unittest.TestCase):
    """默认勾选的包名集合是显式的：AD_PKGS 里给小米族加新包时这条会红，
    逼着回来想清楚它该不该跟着默认勾上。"""

    def test_default_on_is_exactly_the_two_msa_packages(self):
        import run
        self.assertEqual(set(run.DEFAULT_ON), {"com.miui.systemAdSolution", "com.miui.msa.global"})
