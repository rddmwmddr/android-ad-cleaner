"""channel_policy 族的用例表（#1402）：一张规则表，一行一个词元，共 111 行。

`tool/channel_policy.py` 的五张词表里，用到「逐词元判一次」的四张收在这里：营销关键词
`KW`（34）、扫描排除 `SKIP`（48）、默认不勾 `SERVICE_TERMS`（22）、广告网络 `AD_NETWORK_TERMS`（7）。
每行的 owner 是它依赖的那个规则项，不再是票号：实现里删掉一个词元，对应行必须跟着退场，
只删行不改词表则由快照与句柄校验报红。

**不给 `produce`**：判定（`base_judgement` 与 `classify` 逐字段比对）留在
`tests/test_channel_classification.py` 的消费循环里现算，与改造前的口径一致；族里再算一遍
是同一断言换一处写。

**不给 `expected`**：`tests/test_channel_classification.py` 侧逐字冻结的基线元组
（`BASE_KW_TERMS` / `BASE_SKIP_TERMS` / `BASE_SERVICE_TERMS` / `AD_NETWORK_TERMS`）已经是
「每个词元都要有一条用例」这件事的 owner。再叠一层从结构反推的 `expected()`，就是同一件事
的第二个 owner——两边各自成立、各自失效，谁也证不了谁。缺行由快照 `ids` 比对抓，实现里缺词
由句柄校验抓，两条已经覆盖。

实现侧也接不上这一向：`KW` / `SKIP` / `SERVICE_TERMS` 都是编译后的 pattern，`SERVICE_TERMS`
里还混着两条形状规则（`youtube\t2\t` 与 `\t其他$`，不是逐项列举的词元），实现没有暴露可以
逐项枚举的词元元组。从 pattern 反推词元不是「结构来源」，所以「结构推导管新增」在这里仍未
接入；要补齐，得先让实现暴露词元元组，再由族按同一口径反推。

`handles` 全部从行自身的 `(table, term)` 现算，不写字符串字面量句柄。`structure` 按同一组
`(table, term)` 去实现常量里核：`kw` / `skip` 看 pattern 里还有没有这个词元（实现侧不暴露
词元元组，词元只以 compiled pattern 存在，`sample()` 去掉正则边界后作子串判断），`service`
看 `SERVICE_TERMS` 的 pattern，`adnet` 看 `AD_NETWORK_TERMS` 元组。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tool"))
import channel_policy  # noqa: E402

from family import Family, cli  # noqa: E402

CASES = [
    {"id": "kw/营销", "table": "kw", "term": "营销"},
    {"id": "kw/活动", "table": "kw", "term": "活动"},
    {"id": "kw/推荐", "table": "kw", "term": "推荐"},
    {"id": "kw/推广", "table": "kw", "term": "推广"},
    {"id": "kw/热点", "table": "kw", "term": "热点"},
    {"id": "kw/热门", "table": "kw", "term": "热门"},
    {"id": "kw/资讯", "table": "kw", "term": "资讯"},
    {"id": "kw/新闻", "table": "kw", "term": "新闻"},
    {"id": "kw/福利", "table": "kw", "term": "福利"},
    {"id": "kw/优惠", "table": "kw", "term": "优惠"},
    {"id": "kw/特惠", "table": "kw", "term": "特惠"},
    {"id": "kw/精选", "table": "kw", "term": "精选"},
    {"id": "kw/精彩", "table": "kw", "term": "精彩"},
    {"id": "kw/运营", "table": "kw", "term": "运营"},
    {"id": "kw/促销", "table": "kw", "term": "促销"},
    {"id": "kw/红包", "table": "kw", "term": "红包"},
    {"id": "kw/直播", "table": "kw", "term": "直播"},
    {"id": "kw/种草", "table": "kw", "term": "种草"},
    {"id": "kw/内容", "table": "kw", "term": "内容"},
    {"id": "kw/头条", "table": "kw", "term": "头条"},
    {"id": "kw/猜你", "table": "kw", "term": "猜你"},
    {"id": "kw/好物", "table": "kw", "term": "好物"},
    {"id": "kw/权益", "table": "kw", "term": "权益"},
    {"id": "kw/会员", "table": "kw", "term": "会员"},
    {"id": "kw/签到", "table": "kw", "term": "签到"},
    {"id": "kw/广告", "table": "kw", "term": "广告"},
    {"id": "kw/recommend", "table": "kw", "term": "recommend"},
    {"id": "kw/promo", "table": "kw", "term": "promo"},
    {"id": "kw/market", "table": "kw", "term": "market"},
    {"id": "kw/deal", "table": "kw", "term": "deal"},
    {"id": "kw/news", "table": "kw", "term": "news"},
    {"id": "kw/topstory", "table": "kw", "term": "topstory"},
    {"id": "kw/upsell", "table": "kw", "term": "upsell"},
    {"id": "kw/offer", "table": "kw", "term": "offer"},
    {"id": "skip/下载", "table": "skip", "term": "下载"},
    {"id": "skip/更新", "table": "skip", "term": "更新"},
    {"id": "skip/安装", "table": "skip", "term": "安装"},
    {"id": "skip/上传", "table": "skip", "term": "上传"},
    {"id": "skip/订单", "table": "skip", "term": "订单"},
    {"id": "skip/物流", "table": "skip", "term": "物流"},
    {"id": "skip/快递", "table": "skip", "term": "快递"},
    {"id": "skip/交易", "table": "skip", "term": "交易"},
    {"id": "skip/支付", "table": "skip", "term": "支付"},
    {"id": "skip/付款", "table": "skip", "term": "付款"},
    {"id": r"skip/\bpayments?\b", "table": "skip", "term": r"\bpayments?\b"},
    {"id": "skip/账号", "table": "skip", "term": "账号"},
    {"id": "skip/安全", "table": "skip", "term": "安全"},
    {"id": "skip/验证", "table": "skip", "term": "验证"},
    {"id": "skip/通话", "table": "skip", "term": "通话"},
    {"id": "skip/来电", "table": "skip", "term": "来电"},
    {"id": "skip/消息", "table": "skip", "term": "消息"},
    {"id": "skip/聊天", "table": "skip", "term": "聊天"},
    {"id": "skip/私信", "table": "skip", "term": "私信"},
    {"id": "skip/评论", "table": "skip", "term": "评论"},
    {"id": "skip/互动", "table": "skip", "term": "互动"},
    {"id": "skip/提醒", "table": "skip", "term": "提醒"},
    {"id": "skip/闹钟", "table": "skip", "term": "闹钟"},
    {"id": "skip/日程", "table": "skip", "term": "日程"},
    {"id": "skip/天气预警", "table": "skip", "term": "天气预警"},
    {"id": "skip/系统", "table": "skip", "term": "系统"},
    {"id": "skip/前台", "table": "skip", "term": "前台"},
    {"id": "skip/后台", "table": "skip", "term": "后台"},
    {"id": "skip/服务运行", "table": "skip", "term": "服务运行"},
    {"id": "skip/播放", "table": "skip", "term": "播放"},
    {"id": "skip/媒体", "table": "skip", "term": "媒体"},
    {"id": "skip/热点和网络共享", "table": "skip", "term": "热点和网络共享"},
    {"id": "skip/智能热点", "table": "skip", "term": "智能热点"},
    {"id": "skip/红包助手", "table": "skip", "term": "红包助手"},
    {"id": "skip/盗窃", "table": "skip", "term": "盗窃"},
    {"id": "skip/驾驶状态", "table": "skip", "term": "驾驶状态"},
    {"id": "skip/权限建议", "table": "skip", "term": "权限建议"},
    {"id": "skip/运营商", "table": "skip", "term": "运营商"},
    {"id": "skip/警告", "table": "skip", "term": "警告"},
    {"id": "skip/告警", "table": "skip", "term": "告警"},
    {"id": "skip/实时活动", "table": "skip", "term": "实时活动"},
    {"id": "skip/赛事", "table": "skip", "term": "赛事"},
    {"id": "skip/护眼", "table": "skip", "term": "护眼"},
    {"id": "skip/上层显示", "table": "skip", "term": "上层显示"},
    {"id": "skip/提取", "table": "skip", "term": "提取"},
    {"id": "skip/传输", "table": "skip", "term": "传输"},
    {"id": "skip/已共享", "table": "skip", "term": "已共享"},
    {"id": "skip/正在进行", "table": "skip", "term": "正在进行"},
    {"id": "service/TETHERING", "table": "service", "term": "TETHERING"},
    {"id": "service/热点", "table": "service", "term": "热点"},
    {"id": "service/ENVELOPE", "table": "service", "term": "ENVELOPE"},
    {"id": "service/红包", "table": "service", "term": "红包"},
    {"id": "service/Auto lock", "table": "service", "term": "Auto lock"},
    {"id": "service/盗窃", "table": "service", "term": "盗窃"},
    {"id": "service/hotspot", "table": "service", "term": "hotspot"},
    {"id": "service/drive_mode", "table": "service", "term": "drive_mode"},
    {"id": "service/驾驶", "table": "service", "term": "驾驶"},
    {"id": "service/securitypermission", "table": "service", "term": "securitypermission"},
    {"id": "service/权限建议", "table": "service", "term": "权限建议"},
    {"id": "service/直播", "table": "service", "term": "直播"},
    {"id": "service/ig_live", "table": "service", "term": "ig_live"},
    {"id": "service/警告", "table": "service", "term": "警告"},
    {"id": "service/告警", "table": "service", "term": "告警"},
    {"id": "service/实时活动", "table": "service", "term": "实时活动"},
    {"id": "service/赛事", "table": "service", "term": "赛事"},
    {"id": "service/护眼", "table": "service", "term": "护眼"},
    {"id": "service/清理加速", "table": "service", "term": "清理加速"},
    {"id": "service/普通通知", "table": "service", "term": "普通通知"},
    {"id": "service/推送通知", "table": "service", "term": "推送通知"},
    {"id": "service/个性化提示", "table": "service", "term": "个性化提示"},
    {"id": "adnet/tencentadnet", "table": "adnet", "term": "tencentadnet"},
    {"id": "adnet/adroi", "table": "adnet", "term": "adroi"},
    {"id": "adnet/pangle", "table": "adnet", "term": "pangle"},
    {"id": "adnet/admob", "table": "adnet", "term": "admob"},
    {"id": "adnet/applovin", "table": "adnet", "term": "applovin"},
    {"id": "adnet/unityads", "table": "adnet", "term": "unityads"},
    {"id": "adnet/mintegral", "table": "adnet", "term": "mintegral"},
]


def sample(term):
    """把一个 alternation 词元变成一段能命中它的渠道名（只去掉正则边界与可选符）。"""
    return term.replace(r"\b", "").replace("?", "")


def _present(case):
    """实现里这张表现在还有没有这个词元。"""
    table, term = case["table"], case["term"]
    if table == "kw":
        return sample(term) in channel_policy.KW.pattern
    if table == "skip":
        return sample(term) in channel_policy.SKIP.pattern
    if table == "service":
        return term in channel_policy.SERVICE_TERMS.pattern
    if table == "adnet":
        return term in channel_policy.AD_NETWORK_TERMS
    raise ValueError(f"unknown table {table!r} in case {case.get('id')!r}")


def handles(case):
    """这一行依赖的规则项，从行自身的 (table, term) 现算。"""
    return [(case["table"], case["term"])]


def structure():
    """实现里还存在的规则项：按同一组 (table, term) 去实现常量里核。"""
    return {(case["table"], case["term"]) for case in CASES if _present(case)}


FAMILY = Family("channel-policy-terms", CASES, handles=handles, structure=structure)

if __name__ == "__main__":
    sys.exit(cli())
