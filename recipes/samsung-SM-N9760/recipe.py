# 三星 One UI 4 机型脚本：Galaxy Note10+ 5G（SM-N9760，国行）
# 录制：2026-11-05，SP1A.210812.016.N9760ZCU6HZE1 / Android 12，1440×3040，简体中文。
#
# 状态：只有一个段「广告」，2026-11-05 在真机上逐步核对并回读确认，单段执行 5 秒。
#
# 为什么只有一段：这台机器上可自动化的只有「广告」这一面。
#   1) 通知渠道：渠道列表在「通知类别」可点击行后面的 com.android.settings/.SubSettings，
#      AppNotificationSettings 首层没有渠道行，chan-off 停在这一层报「同名 0 行」并跳过
#      （本例 13 条全跳过）。在子页上同一判据能正常读出三行，未写成段。
#      按 docs/清单/三星-OneUI.md 手动处理。
#   2) Galaxy 应用商店：设置齿轮 [868,222][1036,389] 与三星账号按钮 [728,249][840,361]
#      只隔 28px，按文字点击会命中账号页；
#      启动弹窗「是否更新三星应用商店？」上点「取消」后，商店仍进入
#      OdcUpdateProgressActivity 自更新流程并升到 4.6.12.11。
#      两项都不写成段。
#
# 用法：python3 tool/run.py -s 序列号 recipe [广告]
BUILD = "SP1A.210812.016.N9760ZCU6HZE1"
MODELS = ["SM-N9760"]
import time

ONLY = globals().get("ONLY") or []
FAILED_STEPS = []


def step(name):
    def deco(f):
        if (not ONLY or name in ONLY) and p.locked():
            print(f"\n== {name}：手机锁屏了，后面的都不跑"); return f
        if not ONLY or name in ONLY:
            print(f"\n== {name}"); p.miss = 0
            t = time.time()
            try:
                f()
            except Exception as e:
                FAILED_STEPS.append(name)
                print(f"  ✗ 未完成：{e}")
            print(f"  ({time.time()-t:.0f} 秒)")
        return f
    return deco


def protect(title_part):
    """把标题含 title_part、当前为「关」的保护类开关拨到「开」，并回读确认。

    没走 p.off()：这一页点开关圆点本身不弹确认框、也不改状态，必须点整行标题（2026-11-05
    真机实测）。off() 的落点是开关本体（control() 取内层 Switch），在这页上点了没反应；
    判据一侧不是问题——简体译名「选择停用广告个性化功能」已由 #604 认成保护类开关。

    点标题后弹「停止根据您的兴趣展示广告？…取消 / 确定」，用 p.confirm() 收掉。
    成功标志：回读为「开」，且广告 ID 从原 UUID 变为全零，
    再查 settings get global advertising_id 返回 null。
    """
    p.await_page()
    for t, checked, xy in p.switches():
        if title_part not in t:
            continue
        if checked:
            print(f"  · {t} 已是开，跳过")
            return True
        if not p.tap(t, exact=True, scrolls=0):
            p.note_miss(t)
            return False
        p.confirm()
        p.await_page()
        after = [c for title, c, _ in p.switches() if title_part in title]
        if after and after[0]:
            print(f"  ✓ 开 {t}")
            return True
        print(f"  ✗ {t} 点了没变，跳过")
        return False
    p.note_miss(title_part)
    return False


@step("广告")
def _():
    # One UI 4 的系统设置里没有独立的广告入口，只能直达 GMS 的广告设置页。
    # 该页三项：重置广告 ID（动作项）、选择停用广告个性化功能（开关）、启用广告调试日志记录（开关）。
    p.start("com.google.android.gms", ".adid.settings.AdsSettingsActivity", expect=("广告",))
    protect("停用广告个性化")
    p.back()
