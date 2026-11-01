"""渠道判定：营销候选、扫描排除、默认不勾、受保护；未知包名和渠道 ID 不猜测。"""
from dataclasses import dataclass
import re


PHOTO_SPOT = re.compile(r"找[机機]位|[机機]位推[荐薦]|推[荐薦][机機]位")

# 营销关键词。scan 用渠道名 + 渠道 ID 匹配：有的厂商把营销分类写在 ID 里。
KW = re.compile(r"营销|活动|推荐|推广|热点|热门|资讯|新闻|福利|优惠|特惠|精选|精彩|运营|促销|红包|直播|种草|内容|头条|猜你|好物|权益|会员|签到|广告|recommend|promo|market|deal|news|topstory|upsell|offer", re.I)

# 「不进候选清单」的服务 / 功能通知。只匹配渠道名。
SKIP = re.compile(r"下载|更新|安装|上传|订单|物流|快递|交易|支付|付款|\bpayments?\b|账号|安全|验证|通话|来电|消息|聊天|私信|评论|互动|提醒|闹钟|日程|天气预警|系统|前台|后台|服务运行|播放|媒体"
                  r"|热点和网络共享|智能热点|红包助手|盗窃|驾驶状态|权限建议|运营商|警告|告警|实时活动|赛事|护眼"
                  r"|上层显示"     # 「“钱包”正在其他应用的上层显示内容」是悬浮窗提示，名字带「内容」被误选（#115）
                  r"|提取|传输|已共享|正在进行", re.I)   # 识屏「内容提取」（系统锁定）、三星「内容已传输」等功能通知（错误日志 10-27）

# vivo 把营销推送固定编在 VPushChannel_0/4/6（AGENTS.md §5）。渠道名常是「运营消息」，
# 会被 SKIP 的单字「消息」剔掉；分类号是厂商固定值，比渠道名可靠，越过的只有 SKIP，
# 营销关键词仍要命中，否则同 ID 下的服务类渠道会混进客户端默认勾选（#337）。
VIVO_MARKETING = re.compile(r"^VPushChannel_(?:0|4|6)$", re.I)

# 广告网络渠道 ID 是厂商固定车道（#456，来自 #455 的真机反馈）：TencentAdNetCH1、
# ADroiUnion 这类 ID 与渠道名都不带营销词，只认中文营销词会漏。ID 常带前后缀
# （CH1、_union），整段锚定认不出来——子串匹配、大小写不敏感；只匹配渠道 ID，
# 渠道名仍交给营销关键词。与 vivo 的差别：广告网络 ID 只承载广告，命中即营销候选，
# 不再要求营销关键词；SKIP 的服务类排除同样越过。
AD_NETWORK = re.compile(r"tencentadnet|adroi|pangle|admob|applovin|unityads|mintegral", re.I)

# 「已进清单但默认不勾」的服务 / 含糊类别，匹配任一字段（包名、渠道 ID、渠道名、应用名）。
SERVICE_TERMS = re.compile(r"TETHERING|热点|ENVELOPE|红包|Auto lock|盗窃|hotspot|drive_mode|驾驶|securitypermission|权限建议|直播|ig_live|警告|告警|实时活动|赛事|护眼|清理加速|普通通知|推送通知|个性化提示", re.I)
# 旧实现里还有两个依赖 TSV 形状的词条，改写成字段规则：前者是「包名尾部 youtube + ID 2」，
# 后者是「最后一个字段恰为『其他』」。其余词条不含制表符，落在任一字段里等价于整行命中。


@dataclass(frozen=True)
class ChannelJudgement:
    marketing_candidate: bool = False
    scan_excluded: bool = False
    default_unchecked: bool = False
    protected: bool = False
    vivo_marketing_id: bool = False
    ad_network_id: bool = False


def protected_channel(name, channel_id="", list_label=""):
    # 名称可能带空格 / 零宽字符；当前名称、ID、旧清单描述任一命中就保留。
    text = re.sub(r"[\s\u200b\ufeff]+", "", " ".join((name, channel_id, list_label)))
    return bool(PHOTO_SPOT.search(text))


def _youtube_channel_two(fields):
    """旧 SERVICE 的 `youtube\\t2\\t`：某字段以 youtube 结尾，紧邻的下一字段是 2，且 2 后面还有字段。"""
    for i in range(len(fields) - 2):
        if fields[i].lower().endswith("youtube") and fields[i + 1] == "2":
            return True
    return False


def classify(name, channel_id="", list_label="", package="", app=""):
    vivo = bool(VIVO_MARKETING.match(channel_id))
    ad_network = bool(AD_NETWORK.search(channel_id))
    # scan 只在读到应用名时打第四列；没有第四列时，最后一个字段就是渠道名。
    fields = [package, channel_id, name] + ([app] if app else [])
    default_unchecked = (
        any(SERVICE_TERMS.search(field) for field in fields)
        or _youtube_channel_two(fields)
        or fields[-1] == "其他"
    )
    return ChannelJudgement(
        marketing_candidate=ad_network or bool(KW.search(name + " " + channel_id)),
        scan_excluded=bool(SKIP.search(name)) and not (vivo or ad_network),
        default_unchecked=default_unchecked,
        protected=protected_channel(name, channel_id, list_label),
        vivo_marketing_id=vivo,
        ad_network_id=ad_network,
    )
