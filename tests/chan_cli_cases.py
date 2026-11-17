"""chan_fast.py 三个子命令的对拍用例：同一份用例既生成基线，也比对新实现。

每条用例给的是「假设备会怎么回答」：`reads` 是 `parse()` 逐次的读数（用完停在最后一份）、
`toggles` 是 `toggle()` 逐次的结局（同样停在最后一份）、`unlocks` 是 `wait_unlocked()` 逐次的答案。
点击与读屏本身不在这里（它们由 `channel_page` / `channel_outcomes` 与 `compare_chan_pages.py` 管），
这一份只钉批处理对外的东西：退出码、输出行、adb 往返顺序、名单落盘。

`expect` 是守卫断言：这些子串必须出现在两路输出里，证明这条用例真的走到了目标分支；
`guards` 是同一件事的结构化版本（`parse_calls` / `toggle_calls` / `hidden`），逐项与探针的计数比。
"""


def read(channels=(), app_off=(), locked=(), foreground=(), fail=None):
    """一次 `parse()` 的读数。channels 每项是 (包名, 渠道 ID, 渠道名, importance, 已删除)。"""
    out = {"channels": [list(c) for c in channels], "app_off": list(app_off),
           "locked": [list(k) for k in locked], "foreground": [list(k) for k in foreground]}
    if fail:
        out["fail"] = fail
    return out


def done(kind="done", detail="", **extra):
    return dict(kind=kind, detail=detail, **extra)


def raises(what):
    return {"raise": what}


def case(name, argv, *, reads=(), toggles=(), items="", model="M1", labels=None, hidden=(),
         unlocks=(True,), expect=(), guards=None):
    return {"name": name, "argv": list(argv), "reads": list(reads), "toggles": list(toggles),
            "items": items, "model": model, "labels": labels or {}, "hidden": list(hidden),
            "unlocks": list(unlocks), "expect": list(expect), "guards": guards or {}}


# ---------- 一批渠道的读数 ----------
SHOP, SHOP_CID, SHOP_NAME = "com.shop", "promo", "活动优惠"
NEWS, NEWS_CID, NEWS_NAME = "com.news", "news", "热点资讯"
CHAN_ON = [SHOP, SHOP_CID, SHOP_NAME, 3, False]
NEWS_ON = [NEWS, NEWS_CID, NEWS_NAME, 3, False]
CHAN_OFF = [SHOP, SHOP_CID, SHOP_NAME, 0, False]
NEWS_OFF = [NEWS, NEWS_CID, NEWS_NAME, 0, False]
BOTH_ITEMS = f"{SHOP}\t{SHOP_CID}\t{SHOP_NAME}\n{NEWS}\t{NEWS_CID}\t{NEWS_NAME}\n"

# ---------- scan：清单里列出谁、哪种渠道被哪种排除计数 ----------
SCAN_CHANNELS = [
    [SHOP, SHOP_CID, SHOP_NAME, 3, False],                      # 正常候选，带应用名
    ["com.video", "VPushChannel_0", "运营消息", 3, False],       # vivo 营销分类号
    [SHOP, "offch", "促销信息", 0, False],                      # 本来就关着
    ["com.bank", "pay", "支付提醒", 3, False],                   # 服务类，不进候选
    ["com.photo", "spot", "找机位通知", 3, False],               # 受保护
    ["com.gone", "old", "营销旧渠道", 3, True],                  # 已删除
    ["com.offapp", "promo", "活动推荐", 3, False],               # 应用通知整体关着
    ["com.samsung", "com.se...", "营销新闻", 3, False],          # ID 被系统缩略
    ["com.system", "svc", "限时优惠", 3, False],                 # 系统锁定
    ["com.radio", "fg", "精彩直播", 3, False],                   # 前台服务渠道
    ["com.vivo.desktop", "VPushChannel_4", "运营消息", 3, False],  # 记过本机 UI 未暴露
]
SCAN_READ = read(SCAN_CHANNELS, app_off=["com.offapp"], locked=[["com.system", "svc"]],
                 foreground=[["com.radio", "fg"]])
SCAN_EXPECT = [
    "com.shop\tpromo\t活动优惠\t购物应用\n",
    "com.video\tVPushChannel_0\t运营消息\n",
    "另有 1 个渠道的 ID 被系统缩略，无法可靠定位，未列入清单",
    "另有 1 个渠道属于系统锁定、不允许关闭的系统应用，未列入清单",
    "另有 1 个前台服务渠道未列入清单",
    "另有 1 个渠道本机 UI 未暴露，未列入清单",
]

CASES = [
    # ---------- scan ----------
    case("scan-正常批", ["-s", "S", "scan"], reads=[SCAN_READ],
         model="M1", labels={SHOP: "购物应用"}, hidden=[["com.vivo.desktop", "VPushChannel_4"]],
         expect=SCAN_EXPECT,
         guards={"parse_calls": 1, "toggle_calls": [],
                 "hidden": ["com.vivo.desktop\tVPushChannel_4"]}),
    case("scan-空清单", ["-s", "S", "scan"], reads=[read()],
         expect=[], guards={"parse_calls": 1, "toggle_calls": []}),
    case("scan-reset-名单清空", ["-s", "S", "scan", "--reset"], reads=[SCAN_READ],
         hidden=[["com.vivo.desktop", "VPushChannel_4"]],
         expect=["com.vivo.desktop\tVPushChannel_4\t运营消息\n"],
         guards={"hidden": [], "parse_calls": 1}),
    case("scan-断线", ["-s", "S", "scan"], reads=[dict(read(), lost=True)],
         expect=["✗ device offline"], guards={"parse_calls": 1}),
    case("scan-读不到清单", ["-s", "S", "scan"],
         reads=[read(fail="读不到通知渠道状态，停止操作；请检查 USB 调试连接和系统权限")],
         expect=["✗ 读不到通知渠道状态，停止操作；请检查 USB 调试连接和系统权限"],
         guards={"parse_calls": 1, "shells": []}),

    # ---------- off ----------
    case("off-正常批", ["-s", "S", "off", "list.tsv"], items=BOTH_ITEMS,
         reads=[read([CHAN_ON, NEWS_ON]), read([CHAN_OFF, NEWS_OFF])],
         toggles=[done(), done()],
         expect=["  关  活动优惠\n", "  关  热点资讯\n", "拨了 2 个，0 秒", "营销渠道仍开着: 0 个"],
         guards={"parse_calls": 2, "toggle_calls": [[SHOP, SHOP_CID, False, SHOP_NAME],
                                                    [NEWS, NEWS_CID, False, NEWS_NAME]]}),
    case("off-受保护", ["-s", "S", "off", "list.tsv"], items="com.photo\tspot\t找机位通知\n",
         reads=[read([["com.photo", "spot", "找机位通知", 3, False]]),
                read([["com.photo", "spot", "找机位通知", 3, False]])],
         expect=["受保护，未改动 找机位通知（找机位功能通知", "拨了 0 个", "营销渠道仍开着: 0 个"],
         guards={"toggle_calls": [], "parse_calls": 2}),
    case("off-渠道不存在", ["-s", "S", "off", "list.tsv"], items="com.gone\tpromo\t已删渠道\n",
         reads=[read(), read()],
         expect=["未操作 已删渠道（渠道不存在、已删除或应用通知已关闭）", "拨了 0 个"],
         guards={"toggle_calls": [], "parse_calls": 2}),
    case("off-应用通知关闭", ["-s", "S", "off", "list.tsv"], items=f"{SHOP}\t{SHOP_CID}\t{SHOP_NAME}\n",
         reads=[read([CHAN_ON], app_off=[SHOP]), read([CHAN_ON], app_off=[SHOP])],
         expect=["未操作 活动优惠（渠道不存在、已删除或应用通知已关闭）", "拨了 0 个"],
         guards={"toggle_calls": []}),
    case("off-渠道已删除", ["-s", "S", "off", "list.tsv"], items=f"{SHOP}\t{SHOP_CID}\t{SHOP_NAME}\n",
         reads=[read([[SHOP, SHOP_CID, SHOP_NAME, 3, True]]), read([[SHOP, SHOP_CID, SHOP_NAME, 3, True]])],
         expect=["未操作 活动优惠（渠道不存在、已删除或应用通知已关闭）"],
         guards={"toggle_calls": []}),
    case("off-已经是目标状态", ["-s", "S", "off", "list.tsv"], items=f"{SHOP}\t{SHOP_CID}\t{SHOP_NAME}\n",
         reads=[read([CHAN_OFF]), read([CHAN_OFF])],
         expect=["拨了 0 个，0 秒"],
         guards={"toggle_calls": [], "parse_calls": 2}),
    case("off-第二遍重试成功", ["-s", "S", "off", "list.tsv"], items=BOTH_ITEMS,
         reads=[read([CHAN_ON, NEWS_ON]), read([CHAN_OFF, NEWS_ON]), read([CHAN_OFF, NEWS_OFF])],
         toggles=[done("unchanged", "点击后渠道状态未改变"),
                  done("unchanged", "点击后渠道状态未改变"), done()],
         expect=["✗ 点击后渠道状态未改变  活动优惠", "✗ 点击后渠道状态未改变  热点资讯",
                 "再试一次刚才没确认的 1 个渠道", "拨了 2 个，0 秒", "营销渠道仍开着: 0 个"],
         guards={"parse_calls": 3,
                 "toggle_calls": [[SHOP, SHOP_CID, False, SHOP_NAME],
                                  [NEWS, NEWS_CID, False, NEWS_NAME],
                                  [NEWS, NEWS_CID, False, NEWS_NAME]]}),
    case("off-第二遍仍失败", ["-s", "S", "off", "list.tsv"], items=BOTH_ITEMS,
         reads=[read([CHAN_ON, NEWS_ON]), read([CHAN_OFF, NEWS_ON]), read([CHAN_OFF, NEWS_ON])],
         toggles=[done("unchanged", "点击后渠道状态未改变")],
         expect=["再试一次刚才没确认的 1 个渠道", "拨了 1 个，0 秒", "仍开着：热点资讯（com.news）"],
         guards={"parse_calls": 3}),
    case("off-一个都没认出不重试", ["-s", "S", "off", "list.tsv"],
         items=f"{SHOP}\t{SHOP_CID}\t{SHOP_NAME}\n{NEWS}\t{NEWS_CID}\t{NEWS_NAME}\n"
               "com.more\tmore\t活动推荐\n",
         reads=[read([CHAN_ON, NEWS_ON, ["com.more", "more", "活动推荐", 3, False]]),
                read([CHAN_ON, NEWS_ON, ["com.more", "more", "活动推荐", 3, False]])],
         toggles=[done("unchanged", "点击后渠道状态未改变")],
         expect=["拨了 0 个，0 秒", "营销渠道仍开着: 3 个"],
         guards={"parse_calls": 2}),
    case("off-重试全部确认", ["-s", "S", "off", "list.tsv"],
         items=BOTH_ITEMS + "com.more\tmore\t活动推荐\n",
         reads=[read([CHAN_ON, NEWS_ON, ["com.more", "more", "活动推荐", 3, False]]),
                read([CHAN_OFF, NEWS_OFF, ["com.more", "more", "活动推荐", 0, False]]),
                read([CHAN_OFF, NEWS_OFF, ["com.more", "more", "活动推荐", 0, False]])],
         toggles=[done(), done("unchanged", "点击后渠道状态未改变"), done("unchanged", "点击后渠道状态未改变"),
                  done("unchanged", "点击后渠道状态未改变")],
         expect=["拨了 3 个，0 秒", "营销渠道仍开着: 0 个"],
         guards={"parse_calls": 3}),
    case("off-锁屏中止", ["-s", "S", "off", "list.tsv"], items=f"{SHOP}\t{SHOP_CID}\t{SHOP_NAME}\n",
         reads=[read([CHAN_ON]), read([CHAN_ON])], toggles=[raises("locked")], unlocks=[True, False],
         expect=["正在连接手机读屏服务……", "要处理 1 个渠道",
                 "✗ 手机锁屏了，停在「活动优惠」，剩下 1 项没有处理", "拨了 0 个，0 秒"],
         guards={"parse_calls": 2, "phone_created": True, "phone_closed": True}),
    case("off-断线", ["-s", "S", "off", "list.tsv"], items=f"{SHOP}\t{SHOP_CID}\t{SHOP_NAME}\n",
         reads=[read([CHAN_ON])], toggles=[raises("lost")],
         expect=["✗ device offline", "拨了 0 个，0 秒"],
         guards={"parse_calls": 1, "phone_created": True}),
    case("off-点错开关停止整批", ["-s", "S", "off", "list.tsv"], items=f"{SHOP}\t{SHOP_CID}\t{SHOP_NAME}\n",
         reads=[read([CHAN_ON]), read([CHAN_ON])], toggles=[raises("stop")],
         expect=["点击后应用通知总开关发生变化，停止整批", "营销渠道仍开着: 1 个"],
         guards={"parse_calls": 2}),
    case("off-本机UI未暴露记名单", ["-s", "S", "off", "list.tsv"],
         items=f"{SHOP}\t{SHOP_CID}\t{SHOP_NAME}\n",
         reads=[read([CHAN_ON]), read([CHAN_ON])], toggles=[done("ui_hidden")],
         expect=["本机界面没有这个渠道的入口，关不掉，不算失败", "拨了 0 个", "营销渠道仍开着: 0 个"],
         guards={"hidden": [f"{SHOP}\t{SHOP_CID}"], "parse_calls": 2}),

    # ---------- on ----------
    case("on-正常批", ["-s", "S", "on", "list.tsv"], items=BOTH_ITEMS,
         reads=[read([CHAN_OFF, NEWS_ON]), read([CHAN_ON, NEWS_ON])],
         toggles=[done()],
         expect=["  开  活动优惠\n", "拨了 1 个，0 秒", "未恢复的渠道: 0 个"],
         guards={"toggle_calls": [[SHOP, SHOP_CID, True, SHOP_NAME]], "parse_calls": 2}),
    case("on-渠道已删除算失败", ["-s", "S", "on", "list.tsv"],
         items=f"{SHOP}\t{SHOP_CID}\t{SHOP_NAME}\n",
         reads=[read([[SHOP, SHOP_CID, SHOP_NAME, 3, True]])] * 2,
         expect=["未操作 活动优惠（渠道不存在、已删除或应用通知已关闭）", "未恢复的渠道: 1 个"],
         guards={"toggle_calls": []}),

    # ---------- verify（只做机械迁移，不调整行为） ----------
    case("verify-逐项", ["-s", "S", "verify", "list.tsv"], items=BOTH_ITEMS,
         reads=[read([CHAN_ON, NEWS_OFF])],
         expect=["ON   活动优惠（com.shop）", "off  热点资讯（com.news）", "营销渠道仍开着: 1 个"],
         guards={"parse_calls": 1, "toggle_calls": []}),

    # ---------- 参数错 ----------
    case("参数-缺子命令", ["-s", "S"], expect=["用法：chan_fast.py -s <序列号> scan|verify|off|on [清单.tsv]"],
         guards={"parse_calls": 0, "toggle_calls": [], "shells": [], "phone_created": False}),
    case("参数-缺清单", ["-s", "S", "off"], expect=["请提供通知清单路径"],
         guards={"parse_calls": 0, "toggle_calls": [], "shells": [], "phone_created": False}),
]
