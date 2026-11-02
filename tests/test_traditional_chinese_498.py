"""#498 繁体中文界面：渠道页认页与营销/服务词表只认简体、英文。

报告者 vivo V2436A（PD2436E_A_17.2.13.5.W10 / Android 17 / 繁体台湾）的 chan-off 日志：
「标题顶部，允许通知开关 0 个，开关 6 个」——页面已认出来，只差「允許通知」不在 ALLOW。
渠道页样本沿用 #336 的真机结构（顶栏无 resource-id、向上导航、允许通知行），按界面语言换掉全部文字。
"""
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
import chan_fast as chan
import channel_policy as policy
from fixtures import phone_stub

FOCUS = ("com.vivo.systemuiplugin/com.vivo.systemui.statusbar.notification"
         ".settings.channels.NotificationSettingsActivity")
APP = "應用名"

# 同一份页面的三种界面语言：认页只看标签，标题 / 导航 / 分组也要跟着换，才对得上真机
HANT = {"name": "熱門推薦", "back": "向上導覽", "allow": "允許通知",
        "show": "顯示通知", "group": "類別"}
HANS = {"name": "热门推荐", "back": "向上导航", "allow": "允许通知",
        "show": "显示通知", "group": "类别"}
EN = {"name": "Popular recommendations", "back": "Navigate up", "allow": "Allow notifications",
      "show": "Show notifications", "group": "Categories"}


def page(*nodes):
    return ('<hierarchy rotation="0"><node package="com.vivo.systemuiplugin" bounds="[0,0][1080,2340]">'
            + "".join(nodes) + "</node></hierarchy>")


def header(title, back):
    return (f'<node class="android.widget.TextView" text="{title}" bounds="[0,111][1080,360]"/>'
            f'<node class="android.widget.Button" content-desc="{back}" bounds="[24,168][156,300]"/>')


def allow_row(label):
    return ('<node clickable="true" bounds="[0,381][1080,489]">'
            f'<node class="android.widget.TextView" text="{label}" bounds="[0,397][342,473]"/>'
            '<node class="android.widget.Switch" text="開啟" content-desc="開啟" checkable="true" checked="true"'
            ' clickable="true" bounds="[876,381][1020,489]"/></node>')


def channel_page(ui, label):
    return page(header(ui["name"], ui["back"]), allow_row(label))


def app_page(ui):
    return page(header(APP, ui["back"]), allow_row(ui["allow"]),
                '<node class="androidx.recyclerview.widget.RecyclerView" scrollable="true" bounds="[0,520][1080,2280]">'
                f'<node class="android.widget.TextView" text="{ui["group"]}" bounds="[0,540][400,616]"/></node>')


def phone(xml):
    p = phone_stub("test", d=Mock())
    p.W, p.H = 1080, 2340
    p.focus = Mock(return_value=FOCUS)
    p.tree = Mock(return_value=ET.fromstring(xml))
    return p


class ChannelPageTests(unittest.TestCase):
    def _recognise(self, ui, label):
        p = phone(channel_page(ui, label))
        return chan.ChannelPage(p, ui["name"], vivo_app=APP)._recognise()

    def test_every_interface_language_is_recognised(self):
        for ui in (HANT, HANS, EN):
            for key in ("allow", "show"):
                with self.subTest(ui=ui["name"], label=ui[key]):
                    self.assertIsNotNone(self._recognise(ui, ui[key]))

    def test_unknown_label_is_still_rejected(self):
        # 放宽语言不等于放宽判据：标着别的字样的开关不能当通知总开关
        self.assertIsNone(self._recognise(HANT, "通知"))

    def test_every_interface_language_channel_group_is_located(self):
        for ui in (HANT, HANS, EN):
            with self.subTest(ui=ui["name"]):
                p = phone(app_page(ui))
                self.assertIsNotNone(chan.group_floor(p.texts(p.tree())))


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
)
TRAD_SERVICE = ("熱點", "紅包", "竊盜", "盜竊", "駕駛", "權限建議", "即時活動", "實時活動", "賽事", "護眼", "個人化提示")


def judgement(name):
    j = policy.classify(name, "x")
    return j.marketing_candidate, j.scan_excluded, j.default_unchecked


class TermTests(unittest.TestCase):
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
    ("正在進行", "正在进行"),
)


class EquivalenceTests(unittest.TestCase):
    def test_traditional_and_simplified_terms_judge_alike(self):
        for trad, simp in PAIRS:
            with self.subTest(trad=trad, simp=simp):
                self.assertEqual(judgement(trad), judgement(simp))


class SafetyTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
