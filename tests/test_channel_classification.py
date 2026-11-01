"""渠道判定：新 classify() 与基线实现逐条等价。

旧实现（69cfc4d 的 chan_fast.KW/SKIP/VIVO_MARKETING 与 gui.SERVICE）逐字冻结在这里
作为对拍基线；改前改后判定必须逐条相同。判定是值，判据是纯函数，不用手机。
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
import channel_policy as policy


# ---------- 基线：69cfc4d 的旧实现，逐字冻结 ----------
# 词表按 alternation 拆成元组：既用来重建旧正则，也给每个词条生成一条对拍样例。
# 新实现漏词、抄错或改了匹配域，对应样例在基线里仍命中，对拍就会红。
BASE_KW_TERMS = (
    "营销", "活动", "推荐", "推广", "热点", "热门", "资讯", "新闻", "福利", "优惠", "特惠",
    "精选", "精彩", "运营", "促销", "红包", "直播", "种草", "内容", "头条", "猜你", "好物",
    "权益", "会员", "签到", "广告", "recommend", "promo", "market", "deal", "news",
    "topstory", "upsell", "offer",
)
BASE_SKIP_TERMS = (
    "下载", "更新", "安装", "上传", "订单", "物流", "快递", "交易", "支付", "付款",
    r"\bpayments?\b", "账号", "安全", "验证", "通话", "来电", "消息", "聊天", "私信", "评论",
    "互动", "提醒", "闹钟", "日程", "天气预警", "系统", "前台", "后台", "服务运行", "播放",
    "媒体", "热点和网络共享", "智能热点", "红包助手", "盗窃", "驾驶状态", "权限建议", "运营商",
    "警告", "告警", "实时活动", "赛事", "护眼", "上层显示", "提取", "传输", "已共享", "正在进行",
)
BASE_SERVICE_TERMS = (
    "TETHERING", "热点", "ENVELOPE", "红包", "Auto lock", "盗窃", "hotspot", "drive_mode",
    "驾驶", "securitypermission", "权限建议", "直播", "ig_live", "警告", "告警", "实时活动",
    "赛事", "护眼", "清理加速", "普通通知", "推送通知", "个性化提示",
)
BASE_KW = re.compile("|".join(BASE_KW_TERMS), re.I)
BASE_SKIP = re.compile("|".join(BASE_SKIP_TERMS), re.I)
BASE_SERVICE = re.compile("|".join(BASE_SERVICE_TERMS + (r"youtube\t2\t", r"\t其他$")), re.I)
BASE_VIVO = re.compile(r"^VPushChannel_(?:0|4|6)$", re.I)
BASE_PHOTO = re.compile(r"找[机機]位|[机機]位推[荐薦]|推[荐薦][机機]位")


def _sample(term):
    """把一个 alternation 词条变成一段能命中它的渠道名（只去掉正则边界与可选符）。"""
    return term.replace(r"\b", "").replace("?", "")


def base_protected(name, cid, label=""):
    text = re.sub(r"[\s\u200b\ufeff]+", "", " ".join((name, cid, label)))
    return bool(BASE_PHOTO.search(text))


def base_line(pkg, cid, name, app):
    # scan 只在读到非空应用名时打第四列；app_labels() 已 strip 并跳过空值。
    return "\t".join((pkg, cid, name, app) if app else (pkg, cid, name))


def base_judgement(pkg, cid, name, app):
    return {
        "marketing_candidate": bool(BASE_KW.search(name + " " + cid)),
        "scan_excluded": bool(BASE_SKIP.search(name)) and not BASE_VIVO.match(cid),
        "default_unchecked": bool(BASE_SERVICE.search(base_line(pkg, cid, name, app))),
        "protected": base_protected(name, cid),
        "vivo_marketing_id": bool(BASE_VIVO.match(cid)),
    }


CURATED = [
    # 营销关键词
    ("com.shop", "promo", "活动优惠", ""),
    ("com.news", "recommend_1", "热点推荐", ""),
    ("com.live", "live", "直播推荐", ""),
    ("com.x", "promo", "内容资讯", ""),
    # 扫描排除（SKIP）
    ("com.x", "promo", "订单物流", ""),
    ("com.x", "promo", "系统消息", ""),
    ("com.x", "promo", "内容提取", ""),
    ("com.x", "promo", "内容已传输", ""),
    ("com.x", "promo", "“钱包”正在其他应用的上层显示内容", ""),
    ("com.x", "promo", "付款提醒", ""),
    ("com.x", "promo", "天气预警", ""),
    ("com.x", "promo", "热点和网络共享", ""),
    ("com.x", "promo", "红包助手", ""),
    ("com.x", "promo", "驾驶状态", ""),
    ("com.x", "promo", "系统", ""),
    ("com.x", "promo", "播放媒体", ""),
    # 默认不勾（SERVICE）
    ("com.x", "promo", "清理加速", ""),
    ("com.x", "promo", "普通通知", ""),
    ("com.x", "promo", "推送通知", ""),
    ("com.x", "promo", "个性化提示", ""),
    ("com.x", "promo", "其他", ""),
    ("com.x", "promo", "其他", "某应用"),
    ("com.x", "promo", "营销通知", "其他"),
    ("com.x", "promo", "TETHERING状态", ""),
    ("com.x", "promo", "ENVELOPE", ""),
    ("com.x", "promo", "Auto lock", ""),
    ("com.x", "promo", "drive_mode", ""),
    ("com.x", "promo", "securitypermission", ""),
    ("com.x", "promo", "直播", ""),
    ("com.x", "promo", "ig_live", ""),
    ("com.hotspothelper", "promo", "营销通知", ""),
    ("com.x", "promo", "营销通知", "热点资讯"),
    # youtube\t2\t 的字段位置
    ("com.google.android.youtube", "2", "订阅内容", ""),
    ("com.google.android.youtube", "2", "订阅内容", "YouTube"),
    ("com.google.android.youtube", "3", "订阅内容", ""),
    ("com.x", "com.youtube", "2", "某应用"),      # 「youtube」也可落在渠道 ID 位置
    ("com.x", "promo", "Xyoutube", "2"),          # 2 是最后一个字段：旧规则要求后面还有字段，不命中
    # vivo 厂商营销 ID
    ("com.vivo.x", "VPushChannel_0", "运营消息", ""),
    ("com.vivo.x", "VPushChannel_1", "系统消息", ""),
    ("com.vivo.x", "VPushChannel_4", "运营消息", ""),
    ("com.vivo.x", "VPushChannel_6", "运营消息", ""),
    ("com.vivo.x", "VPushChannel_7", "运营消息", ""),
    ("com.vivo.x", "VPushChannel_0x", "运营消息", ""),
    # 受保护
    ("com.x", "recommend", "找机位推荐", ""),
    ("com.x", "recommend", "机位推荐", ""),
    ("com.x", "recommend", "推荐机位", ""),
]

# 每个基线词条一条样例：新实现漏词、抄错或改域，这条就会红。
TERM_CASES = (
    # cid 用中性值：否则 cid 里的英文营销词会掩盖渠道名上的 KW 词条被删。
    [("com.term", "x", _sample(term), "") for term in BASE_KW_TERMS]
    + [("com.term", "x", _sample(term), "") for term in BASE_SKIP_TERMS]
    + [("com.term", "x", _sample(term), "") for term in BASE_SERVICE_TERMS]
)

CORPUS = CURATED + TERM_CASES


class EquivalenceTests(unittest.TestCase):
    def test_every_baseline_term_has_a_case(self):
        self.assertEqual(len(TERM_CASES),
                         len(BASE_KW_TERMS) + len(BASE_SKIP_TERMS) + len(BASE_SERVICE_TERMS))

    def test_new_judgement_matches_frozen_baseline(self):
        for pkg, cid, name, app in CORPUS:
            with self.subTest(name=name, cid=cid, app=app):
                want = base_judgement(pkg, cid, name, app)
                got = policy.classify(name, cid, package=pkg, app=app)
                for field, value in want.items():
                    self.assertEqual(getattr(got, field), value, field)


class SerializationEdgeTests(unittest.TestCase):
    """旧 SERVICE 匹配整行 TSV；两条依赖形状的词条改成字段规则后必须等价。"""

    def test_bare_other_without_app_column_is_default_unchecked(self):
        self.assertTrue(policy.classify("其他", "promo").default_unchecked)

    def test_fourth_column_other_is_not_pinned_by_the_trailing_term(self):
        # 旧实现同样如此：整行末尾不是 `\t其他` 时不命中；重构没有改变这一点。
        self.assertFalse(policy.classify("其他", "promo", package="com.x", app="某应用").default_unchecked)

    def test_youtube_channel_two_is_matched_by_package_and_id(self):
        self.assertTrue(policy.classify("订阅内容", "2", package="com.google.android.youtube").default_unchecked)

    def test_youtube_channel_two_needs_a_field_after_the_id(self):
        # `youtube\t2\t` 要求 2 后面还有字段；2 落在最后一个字段时不命中
        self.assertFalse(policy.classify("Xyoutube", "2", package="com.x").default_unchecked)

    def test_service_term_in_package_or_app_still_counts(self):
        self.assertTrue(policy.classify("营销通知", "promo", package="com.hotspothelper").default_unchecked)
        self.assertTrue(policy.classify("营销通知", "promo", package="com.x", app="热点资讯").default_unchecked)


class AdNetworkTests(unittest.TestCase):
    """厂商把广告网络写在渠道 ID 里（#456）：ID 命中即营销，且越过服务词。"""

    def test_ad_network_id_alone_is_a_marketing_candidate(self):
        for cid in ("TencentAdNetCH1", "ADroiUnion"):
            with self.subTest(cid=cid):
                j = policy.classify("频道", cid)
                self.assertTrue(j.ad_network_id)
                self.assertTrue(j.marketing_candidate)
                self.assertFalse(j.scan_excluded)

    def test_every_token_has_a_case(self):
        # 词表里漏一个、抄错一个，这里就红；与基线词表的 TERM_CASES 同一思路。
        for term in policy.AD_NETWORK_TERMS:
            with self.subTest(term=term):
                self.assertTrue(policy.classify("频道", f"vendor_{term}_ch1").ad_network_id)

    def test_ad_network_id_is_case_insensitive(self):
        for cid in ("tencentadnetch1", "adroiunion", "ADROI_UNION"):
            with self.subTest(cid=cid):
                self.assertTrue(policy.classify("频道", cid).ad_network_id)

    def test_lookalike_ids_are_not_ad_network(self):
        for cid in ("unionpay_notify", "update_channel", "payments"):
            with self.subTest(cid=cid):
                j = policy.classify("频道", cid)
                self.assertFalse(j.ad_network_id, cid)
                self.assertFalse(j.marketing_candidate, cid)

    def test_ad_network_overrides_service_word_skip(self):
        j = policy.classify("更新提醒", "ADroiUnion")
        self.assertTrue(j.marketing_candidate)
        self.assertFalse(j.scan_excluded)

    def test_ad_network_tokens_do_not_leak_into_channel_names(self):
        j = policy.classify("adroi union", "neutral_channel")
        self.assertFalse(j.ad_network_id)
        self.assertFalse(j.marketing_candidate)


class InterfaceTests(unittest.TestCase):
    def test_vendor_id_suppresses_scan_exclusion_but_not_marketing_keywords(self):
        j = policy.classify("运营消息", "VPushChannel_0")
        self.assertTrue(j.vivo_marketing_id)
        self.assertFalse(j.scan_excluded)          # 越过 SKIP 的单字「消息」
        self.assertTrue(j.marketing_candidate)     # 「运营」仍在营销关键词里，厂商 ID 不越过它

    def test_protected_uses_list_label_like_before(self):
        self.assertTrue(policy.classify("活动", "promo", list_label="找机位").protected)


if __name__ == "__main__":
    unittest.main()
