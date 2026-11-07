"""开关的极性判据：这一行该拨到开、关，还是干脆不碰。只做文本判定，不读屏、不碰 adb。

引擎（`tool/fast.py` 的 `plan_switches()`）与文档生成器（`tool/vocab.py`）都从这里取，
两边不可能再把同一个词表记成两份（#693：词库曾按 `p.off()` 字面量一律标「要关」，
而引擎会打开保护类开关）。`fast` 仍转发这些名字，写机型脚本的人照旧 `from fast import want_state`。
"""
import re

# 「防止/限制/阻止广告跟踪」「关闭个性化推荐」这类开关是反着的：打开才是保护。不能当广告开关关掉。
# 否定词前允许一组祈使动词：Google 简体译名是「选择停用广告个性化功能」，行首锚定认不到（#604）。
NEG_PREFIX = re.compile(r"^(?:选择|選擇|点击|點擊)?(防止|限制|阻止|禁止|拒绝|拒絕|不允许|不允許|屏蔽|封鎖"
                        r"|关闭|關閉|停用|不接收|不显示|不顯示|不推送|停止|减少|減少)")
# 简繁两套都收，只列写法不同的词条（#604；与 #498 在 channel_policy.py 的做法一致）。
AD_WORDS = re.compile(r"广告|廣告|跟踪|追踪|追蹤|推荐|推薦|个性化|個人化|营销|營銷|行銷"
                      r"|资讯|資訊|热搜|熱搜|热点|熱點|定向|画像|畫像")   # 不含「推送」：「关闭推送」会连订单通知一起关
TRACK_WORDS = re.compile(r"广告|廣告|跟踪|追踪|追蹤")


def want_state(title):
    """这个开关该处在什么状态：False=关（普通广告开关）；True=开（保护类开关）；None=不碰。"""
    if NEG_PREFIX.search(title or ""):
        return True if AD_WORDS.search(title) else None
    return False
