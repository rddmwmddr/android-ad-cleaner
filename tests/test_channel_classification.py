"""渠道判定：哪些渠道算营销、受保护、默认不勾，扫描因此列出谁、排除谁。不用手机。

`classify()` 的七组判定与只读扫描的清单都收在这一份。旧实现（69cfc4d 的 chan_fast.KW/SKIP/
VIVO_MARKETING 与 gui.SERVICE）逐字冻结在这里作为对拍基线；改前改后判定必须逐条相同。
引导词表之外的判定另按单词样例覆盖：广告网络 ID、发送进度名（#459 前台的渠道与服务词条）、
繁体词条（#498，本文件的繁体一组按繁简成对验证）。
扫完之后怎么记、怎么报不在这一份，见 test_channel_outcomes.py。
"""
import contextlib
import io
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("AAC_NO_SOUND", "1")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))
import adb_link
import channel_policy as policy
import chan_fast as chan
import fast
from fixtures import fake_adb
from phone import connection as phone_connection


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


class BaselineEquivalenceTests(unittest.TestCase):
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


# 广告网络词表在测试侧冻结：只遍历实现自己的元组时，删词会连样例一起消失。
AD_NETWORK_TERMS = ("tencentadnet", "adroi", "pangle", "admob", "applovin", "unityads", "mintegral")


class AdNetworkTests(unittest.TestCase):
    """厂商把广告网络写在渠道 ID 里（#456）：ID 命中即营销，且越过服务词。"""

    def test_ad_network_id_alone_is_a_marketing_candidate(self):
        for cid in ("TencentAdNetCH1", "ADroiUnion"):
            with self.subTest(cid=cid):
                j = policy.classify("频道", cid)
                self.assertTrue(j.ad_network_id)
                self.assertTrue(j.marketing_candidate)
                self.assertFalse(j.scan_excluded)

    def test_implementation_terms_match_the_frozen_list(self):
        self.assertEqual(tuple(policy.AD_NETWORK_TERMS), AD_NETWORK_TERMS)

    def test_every_token_has_a_case(self):
        # 词表里漏一个、抄错一个，这里就红；与基线词表的 TERM_CASES 同一思路。
        for term in AD_NETWORK_TERMS:
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


# ---- channel_send_progress ----
# 发送进度类渠道（WhatsApp「发送影音内容」）不进营销候选：名字带「内容」曾被默认勾选。


class SendProgressTest(unittest.TestCase):
    def test_send_progress_is_excluded(self):
        for name in ("发送影音内容", "發送影音內容"):
            self.assertTrue(policy.classify(name).scan_excluded, name)

    def test_marketing_content_still_listed(self):
        self.assertFalse(policy.classify("内容资讯").scan_excluded)


# ---- service_channel_459 ----
# #459 前台服务的常驻通知渠道：dump 行带 mFgServiceShown=true 时不进扫描清单。
#
# 字段属于 NotificationChannel，不属于 NotificationRecord：AOSP 由
# getFieldsString() 打在 PackagePreferences: 段那行 NotificationChannel{...} 上，
# 也就是 parse() 已经在逐行解析的行。粘性——渠道发过一次前台服务通知就永久为
# true，之后转成纯营销仍会被排除，这条代价已确认接受（见 ADR-0006 增补）。


PACKAGE = "com.freeme.cloud.launcher.recommendationservice"
CHANNEL_ID = "necessary_splash_start_channel"


def channel_line(cid, name, importance=3, deleted="false", fg=None, field="mFgServiceShown"):
    # 真机行的字段顺序：mImportance → … → 前台服务标记 → … → mDeleted。
    mark = "" if fg is None else f", {field}={fg}"
    return (f"NotificationChannel{{mId='{cid}', mName={name}, mDescription=null,"
            f" mImportance={importance}{mark}, mBypassDnd=false, mDeleted={deleted}}}")


def dump(*lines):
    return ("PackagePreferences:\n"
            f"      AppSettings: {PACKAGE} importance=DEFAULT\n"
            + "".join(f"        {line}\n" for line in lines))


class ForegroundServiceScanTests(unittest.TestCase):
    def setUp(self):
        fake_adb(self)

    def scan(self, output):
        result = SimpleNamespace(returncode=0, stdout=output, stderr="")
        with patch.object(subprocess, "run", return_value=result), \
             patch.object(chan, "app_labels", return_value={}) as labels, \
             patch.object(sys, "argv", ["chan_fast.py", "-s", "test", "scan"]), \
             contextlib.redirect_stdout(io.StringIO()) as out, \
             contextlib.redirect_stderr(io.StringIO()) as err:
            chan.main()
        labels.assert_called_once()
        return out.getvalue(), err.getvalue()

    def test_foreground_service_channel_is_not_listed(self):
        out, err = self.scan(dump(channel_line(CHANNEL_ID, "应用推荐服务", fg="true")))
        self.assertEqual(out, "")
        self.assertIn("另有 1 个前台服务渠道未列入清单", err)
        self.assertNotIn(CHANNEL_ID, err)

    def test_line_without_the_field_keeps_current_behavior(self):
        # OEM 剥掉字段时退回现状：照常列入清单，stderr 不多行
        out, err = self.scan(dump(channel_line(CHANNEL_ID, "应用推荐服务")))
        self.assertEqual(out, f"{PACKAGE}\t{CHANNEL_ID}\t应用推荐服务\n")
        self.assertEqual(err, "")

    def test_field_false_does_not_exclude(self):
        out, err = self.scan(dump(channel_line(CHANNEL_ID, "应用推荐服务", fg="false")))
        self.assertEqual(out, f"{PACKAGE}\t{CHANNEL_ID}\t应用推荐服务\n")
        self.assertEqual(err, "")

    def test_foreground_service_outranks_ad_network_hit(self):
        # 同一渠道同时命中广告网络：按前台服务排除，只计一次
        out, err = self.scan(dump(channel_line("TencentAdNetCH1", "频道", fg="true")))
        self.assertEqual(out, "")
        self.assertIn("另有 1 个前台服务渠道未列入清单", err)
        self.assertIn("另有 1 个", err)
        self.assertEqual(err.count("另有"), 1)

    def test_android14_renamed_field_is_recognised(self):
        # Android 14 起框架把字段改名，语义与粘性不变；只认老名字会让这条排除在新系统上静默失效
        out, err = self.scan(dump(channel_line(CHANNEL_ID, "应用推荐服务", fg="true",
                                               field="mUserVisibleTaskShown")))
        self.assertEqual(out, "")
        self.assertIn("另有 1 个前台服务渠道未列入清单", err)

    def test_foreground_service_is_counted_before_truncated_id(self):
        out, err = self.scan(dump(channel_line("com.se...", "活动优惠", fg="true")))
        self.assertEqual(out, "")
        self.assertIn("另有 1 个前台服务渠道未列入清单", err)
        self.assertNotIn("缩略", err)

    def test_foreground_service_is_counted_before_system_locked(self):
        locked = ("PackagePreferences:\n"
                  f"      AppSettings: {PACKAGE} importance=DEFAULT fixedImportance=true\n"
                  "        " + channel_line(CHANNEL_ID, "活动优惠", fg="true")
                  .replace("mBypassDnd=false", "mBypassDnd=false, mBlockableSystem=false") + "\n")
        out, err = self.scan(locked)
        self.assertEqual(out, "")
        self.assertIn("另有 1 个前台服务渠道未列入清单", err)
        self.assertNotIn("系统锁定", err)

    def test_channel_that_would_not_be_listed_is_not_counted(self):
        # 服务类渠道本来就不进清单，不该算进「前台服务渠道」的数字
        out, err = self.scan(dump(channel_line(CHANNEL_ID, "应用推荐服务", fg="true"),
                                  channel_line("system_channel", "系统消息", fg="true")))
        self.assertEqual(out, "")
        self.assertIn("另有 1 个前台服务渠道未列入清单", err)


class ForegroundServiceClassifyTests(unittest.TestCase):
    def test_default_judgement_is_unchanged(self):
        default = chan.classify("活动优惠", "promo")
        self.assertFalse(default.foreground_service)
        self.assertTrue(default.marketing_candidate)

    def test_foreground_service_keeps_the_marketing_signal(self):
        # 排除由调用方合成（同 scan_excluded / truncated 的写法），判定本身不抹掉营销信号
        judgement = chan.classify("活动优惠", "promo", foreground_service=True)
        self.assertTrue(judgement.foreground_service)
        self.assertTrue(judgement.marketing_candidate)


# ---- traditional_chinese_498（词表部分） ----
# #498 繁体中文界面：渠道页认页与营销/服务词表只认简体、英文。
#
# 报告者 vivo V2436A（PD2436E_A_17.2.13.5.W10 / Android 17 / 繁体台湾）的 chan-off 日志：
# 「标题顶部，允许通知开关 0 个，开关 6 个」——页面已认出来，只差「允許通知」不在 ALLOW。
# 渠道页样本沿用 #336 的真机结构（顶栏无 resource-id、向上导航、允许通知行），按界面语言换掉全部文字。

# 繁体写法：每个词条一条单词样例，删掉任何一个词条都会让对应用例红（CODING_STANDARDS:38）。
TRAD_KW = (
    "營銷", "活動", "推薦", "推廣", "熱點", "熱門", "資訊", "新聞", "優惠", "精選",
    "營運", "運營", "促銷", "紅包", "種草", "內容", "頭條", "權益", "會員", "簽到", "廣告",
)
TRAD_SKIP = (
    "下載", "安裝", "上傳", "訂單", "快遞", "帳號", "驗證", "通話", "來電", "訊息",
    "評論", "互動", "鬧鐘", "天氣預警", "系統", "後台", "服務運行", "媒體",
    "熱點和網路共享", "熱點和網絡共享", "智慧熱點", "智能熱點", "紅包助手", "竊盜", "盜竊",
    "駕駛狀態", "權限建議", "電信業者", "營運商", "運營商",
    "即時活動", "實時活動", "賽事", "護眼", "上層顯示", "傳輸", "正在進行",
    "發送",
)
TRAD_SERVICE = ("熱點", "紅包", "竊盜", "盜竊", "駕駛", "權限建議", "即時活動", "實時活動", "賽事", "護眼", "個人化提示")


def trad_judgement(name):
    j = policy.classify(name, "x")
    return j.marketing_candidate, j.scan_excluded, j.default_unchecked


class TraditionalTermTests(unittest.TestCase):
    def test_every_traditional_marketing_term_is_a_candidate(self):
        for term in TRAD_KW:
            with self.subTest(term=term):
                self.assertTrue(policy.classify(term, "x").marketing_candidate)

    def test_every_traditional_service_term_is_excluded_from_scan(self):
        for term in TRAD_SKIP:
            with self.subTest(term=term):
                self.assertTrue(policy.classify(term, "x").scan_excluded)

    def test_every_traditional_service_term_is_default_unchecked(self):
        for term in TRAD_SERVICE:
            with self.subTest(term=term):
                self.assertTrue(policy.classify(term, "x").default_unchecked)


# 繁简成对：同一语义在两种界面下必须得到同一组判定。台湾 / 香港两种繁体译法各对一次。
PAIRS = (
    ("推薦", "推荐"), ("廣告", "广告"), ("精選", "精选"), ("活動優惠", "活动优惠"),
    ("熱門資訊", "热门资讯"), ("新聞", "新闻"), ("推廣", "推广"), ("促銷", "促销"),
    ("種草", "种草"), ("內容", "内容"), ("頭條", "头条"), ("權益", "权益"),
    ("會員", "会员"), ("簽到", "签到"), ("營運", "运营"), ("運營", "运营"),
    ("熱點", "热点"), ("紅包", "红包"), ("駕駛", "驾驶"), ("個人化提示", "个性化提示"),
    ("系統", "系统"), ("訂單", "订单"), ("帳號", "账号"), ("訊息", "消息"),
    ("驗證", "验证"), ("通話", "通话"), ("快遞", "快递"), ("下載", "下载"),
    ("安裝", "安装"), ("上傳", "上传"), ("來電", "来电"), ("評論", "评论"),
    ("互動", "互动"), ("鬧鐘", "闹钟"), ("天氣預警", "天气预警"), ("後台", "后台"),
    ("服務運行", "服务运行"), ("媒體", "媒体"), ("熱點和網路共享", "热点和网络共享"),
    ("智慧熱點", "智能热点"), ("紅包助手", "红包助手"), ("竊盜", "盗窃"), ("盜竊", "盗窃"),
    ("駕駛狀態", "驾驶状态"), ("權限建議", "权限建议"), ("營運商", "运营商"),
    ("即時活動", "实时活动"), ("實時活動", "实时活动"),
    ("賽事", "赛事"), ("護眼", "护眼"), ("上層顯示", "上层显示"), ("傳輸", "传输"),
    ("正在進行", "正在进行"), ("發送", "发送"),
)


class TraditionalEquivalenceTests(unittest.TestCase):
    def test_traditional_and_simplified_terms_judge_alike(self):
        for trad, simp in PAIRS:
            with self.subTest(trad=trad, simp=simp):
                self.assertEqual(trad_judgement(trad), trad_judgement(simp))


class TraditionalSafetyTests(unittest.TestCase):
    def test_traditional_service_terms_do_not_leak_into_default_checked_candidates(self):
        # scan 只列 marketing_candidate 且未 scan_excluded 的渠道：繁体服务渠道不能同时满足两条
        for term in TRAD_SKIP:
            with self.subTest(term=term):
                j = policy.classify(term, "x")
                self.assertFalse(j.marketing_candidate and not j.scan_excluded)

    def test_vivo_marketing_id_still_requires_a_marketing_keyword(self):
        # #337：厂商分类号越过 SKIP，但不越过营销词；繁体渠道名同样要命中
        j = policy.classify("服務訊息", "VPushChannel_0")
        self.assertTrue(j.vivo_marketing_id)
        self.assertFalse(j.marketing_candidate)


# ---- scan_startup ----
# 0.2.2：只读扫描不依赖 UiAutomation，初始化失败保留完整原因。


def scan_dump(importance=3):
    return f"""PackagePreferences:
      AppSettings: com.example importance=DEFAULT
        NotificationChannel{{mId='promo', mName=活动优惠, mDescription=null, mImportance={importance}, mDeleted=false}}
    """


class ReadOnlyScanTests(unittest.TestCase):
    def invoke(self, args, output):
        fake_adb(self)
        result = SimpleNamespace(returncode=0, stdout=output, stderr="")
        with patch.object(phone_connection, "connect", side_effect=AssertionError("只读操作不应启动 UiAutomation")) as connect, \
             patch.object(subprocess, "run", return_value=result) as shell, \
             patch.object(chan, "app_labels", return_value={}), \
             patch.object(sys, "argv", ["chan_fast.py", "-s", "test-device", *args]), \
             contextlib.redirect_stdout(io.StringIO()) as log:
            chan.main()
        connect.assert_not_called()
        self.assertTrue(all(c.args[0][1:3] == ["-s", "test-device"] for c in shell.call_args_list))
        # 只读扫描只发这两条读命令：dumpsys 读渠道，getprop 读型号（「本机 UI 未暴露」名单按型号分文件，#576）
        self.assertTrue(all(c.args[0][-1] in ("dumpsys notification --noredact", "getprop ro.product.model")
                            for c in shell.call_args_list))
        return log.getvalue()

    def test_scan_survives_unavailable_automation(self):
        self.assertEqual(self.invoke(["scan"], scan_dump()), "com.example\tpromo\t活动优惠\n")

    def test_mixed_payment_and_deals_channel_is_not_marketing_candidate(self):
        # 一加 Ace 2 Pro 实机 Google Play 渠道同时承载付款和推荐，不能因推荐字样关闭。
        for name in ("付款事宜、特惠信息和推荐内容", "Payments, deals and recommendations"):
            with self.subTest(name=name):
                self.assertEqual(self.invoke(["scan"], scan_dump().replace("活动优惠", name)), "")

    def test_ad_network_channel_is_listed(self):
        body = (scan_dump().replace("com.example", "com.freeme.launcher")
                .replace("'promo', mName=活动优惠", "'TencentAdNetCH1', mName=频道"))
        self.assertEqual(self.invoke(["scan"], body), "com.freeme.launcher\tTencentAdNetCH1\t频道\n")

    def test_verify_and_noop_close_never_initialize_or_navigate(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "channels.tsv")
            path.write_text("com.example\tpromo\t活动优惠\n", encoding="utf-8")
            self.assertIn("仍开着: 1", self.invoke(["verify", str(path)], scan_dump()))
            self.assertIn("拨了 0 个", self.invoke(["off", str(path)], scan_dump(0)))

    def test_missing_list_fails_before_device_access(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(phone_connection, "connect") as connect, \
             patch.object(subprocess, "run") as shell, \
             patch.object(sys, "argv", ["chan_fast.py", "-s", "test", "off", str(Path(directory, "missing.tsv"))]):
            with self.assertRaises(FileNotFoundError):
                chan.main()
        shell.assert_not_called()
        connect.assert_not_called()

    def test_close_still_requires_working_automation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "channels.tsv")
            path.write_text("com.example\tpromo\t活动优惠\n", encoding="utf-8")
            with patch.object(chan.ShellPhone, "shell", return_value=SimpleNamespace(output=scan_dump())), \
                 patch.object(phone_connection, "accessibility_summary", return_value="只读检查不可用"), \
                 patch.object(phone_connection, "connect", side_effect=fast.u2.exceptions.LaunchUiAutomationError("java.lang.IllegalStateException: example")), \
                 patch.object(sys, "argv", ["chan_fast.py", "-s", "test", "off", str(path)]), \
                 contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit) as stop:
                    chan.main()
            # 不打印 Python 报错堆栈，原因和客户端识别用的标记（LaunchUiAutomationError）仍在
            self.assertRegex(str(stop.exception.code), r"读屏服务.*启动失败[\s\S]*LaunchUiAutomationError")

    def test_adb_failure_is_not_empty_success(self):
        result = SimpleNamespace(returncode=1, stdout="", stderr="device unauthorized")
        with patch.object(adb_link, "adb_path", return_value="/fake/adb"), \
             patch.object(subprocess, "run", return_value=result):
            with self.assertRaisesRegex(RuntimeError, "unauthorized"):
                chan.parse(chan.ShellPhone("test"))

    def test_shell_call_has_serial_utf8_and_timeout(self):
        with patch.object(adb_link, "adb_path", return_value="/fake/adb"), \
             patch.object(subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout=scan_dump(), stderr="")) as shell:
            chan.parse(chan.ShellPhone("test"))
        self.assertEqual(shell.call_args.args[0], ["/fake/adb", "-s", "test", "shell", "dumpsys notification --noredact"])
        self.assertEqual(shell.call_args.kwargs["timeout"], 60)
        self.assertEqual(shell.call_args.kwargs["encoding"], "utf-8")


if __name__ == "__main__":
    unittest.main()
