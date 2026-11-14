# 三星 SM-N9760 的本机例外函数（catalog 的 `code=`，影随 `SM-N9760.toml`）。只有 `protect`：
# 「选择停用广告个性化功能」是保护类开关，点开关本体不弹确认框也不改状态，必须点整行标题
# （2026-11-05 真机实测）；off() 的落点是开关本体（control() 取内层 Switch），在这页上点了没反应。
# p / rt 由 catalog 装载器写进执行作用域（preamble），例外函数按模块全局名取。


def protect(p, rt, title_part):
    """把标题含 title_part、当前为「关」的保护类开关拨到「开」，并回读确认。

    点标题后弹「停止根据您的兴趣展示广告？…取消 / 确定」，用 p.confirm() 收掉。
    成功标志：回读为「开」，且广告 ID 从原 UUID 变为全零，再查 settings get global advertising_id 返回 null。
    """
    p.await_page()
    for t, checked, _ in p.switches():
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
