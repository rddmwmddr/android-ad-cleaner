"""回归：广告网络渠道 ID 直接进营销候选（#456，来自 #455 的真机反馈）。

`com.freeme.launcher` 的 TencentAdNetCH1 / ADroiUnion 与渠道名都不带营销词，
旧判定 marketing=False、chan-scan 列不出来。判定是值、判据是纯函数，不用手机。
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
import channel_policy as policy


class AdNetworkChannel456(unittest.TestCase):
    def test_freeme_ad_network_ids_become_marketing_candidates(self):
        for cid in ("TencentAdNetCH1", "ADroiUnion"):
            j = policy.classify("桌面快捷方式", cid)
            self.assertTrue(j.ad_network_id, cid)
            self.assertTrue(j.marketing_candidate, cid)
            self.assertFalse(j.scan_excluded, cid)

    def test_an_ad_network_id_survives_a_service_word_in_the_name(self):
        # 渠道名「系统更新」会被 SKIP 剔掉；ID 是广告网络车道时仍进候选，且不被排除。
        j = policy.classify("系统更新", "TencentAdNetCH1")
        self.assertTrue(j.marketing_candidate)
        self.assertFalse(j.scan_excluded)

    def test_matching_is_substring_and_case_insensitive(self):
        for cid in ("adroi_union", "AppLovinMax", "PANGLE_banner", "csj-tencentadnet-01"):
            self.assertTrue(policy.classify("通知", cid).ad_network_id, cid)

    def test_only_the_channel_id_matches_not_the_name(self):
        # 渠道名撞上广告网络词不算：判定仍只看 ID，营销候选交给关键词（资讯会命中）。
        j = policy.classify("Pangle 资讯", "normal_channel")
        self.assertFalse(j.ad_network_id)
        self.assertTrue(j.marketing_candidate)

    def test_generic_ids_do_not_turn_into_ad_networks(self):
        # 反例不带任何营销关键词，marketing_candidate 也必须为 False。
        for cid in ("unionpay", "update", "main", "daily_backup"):
            j = policy.classify("通知", cid)
            self.assertFalse(j.ad_network_id, cid)
            self.assertFalse(j.marketing_candidate, cid)

    def test_vivo_and_ad_network_bypasses_compose(self):
        # 两个厂商车道互相独立：各自越过 SKIP，vivo 仍要求营销关键词（#337）。
        vivo = policy.classify("运营消息", "VPushChannel_4")
        self.assertTrue(vivo.marketing_candidate and vivo.vivo_marketing_id)
        self.assertFalse(vivo.scan_excluded)
        self.assertFalse(vivo.ad_network_id)


if __name__ == "__main__":
    unittest.main()
