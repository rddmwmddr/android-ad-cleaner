"""设置搜索：进搜索页、打字、退场（ADR-0033、#1042）。

三件事各有自己的退化链，搬的时候一起搬：开搜索页先试直达动作、不行回设置首页点搜索框；
打字先 setText、对不上再清掉改用剪贴板；失败一律退场回设置首页，不留输入法占着屏幕（沿用 #639 的退场做法）。

对外只有一条语义是硬的：**找不到就只报没找到，不抛异常**。调用方靠返回值决定继续还是收尾
（`if not p.setting(…)` 那一族），抛异常会把「这一页本来就没有」变成整段失败（沿用 #776 的判据）。
所以退场失败也只多一句诊断，返回值仍是假。

观测与动作只经 `Screen`，传输经它背后的 `Connection`；丢失记录（`miss`）归会话对象，
这里起手把它清 0，下游的入口探测才知道不在「已经走丢」的状态里。
"""
import re
import time

import wait

# 输入框：荣耀 MagicOS 10（PNM-AN10 10.0.0.102）设置搜索框是 AutoCompleteTextView，类名里没有 EditText
EDIT = re.compile(r"EditText|AutoCompleteTextView")

BOX = re.compile(r"^搜索.{0,6}设置|^Search settings", re.I)

# 直接打开系统设置搜索页的动作（沿用 #650 的直达动作）：打得开就省掉「设置首页 → 找框 → 点框 → 等输入框」。
# 没有这个动作的系统 am start 当场报解析不到（退出码非零），回到老路，不额外等。
SEARCH_ACTION = "oplus.intent.action.settings.MAIN_SEARCH"        # ColorOS（OPPO / 一加 / 真我）


class SettingsSearch:
    """设置搜索会话：开搜索页、打字、按关键词进页、退场。

    `screen` 给观测与动作原语，`lost_note` 是丢失记录（起手清 `miss`）。
    """

    def __init__(self, screen, lost_note):
        self.screen = screen
        self.conn = screen.conn
        self.lost_note = lost_note

    @property
    def reader(self):
        """读屏 adapter 归 `Connection`：换 reader 时这里跟着换，不缓存。"""
        return self.conn.reader

    def focused_text(self):
        for n in self.screen.tree().iter("node"):
            if n.get("focused") == "true" and EDIT.search(n.get("class") or "") and self.screen.on_screen(n):
                return n.get("text") or ""
        return None

    def edit_ready(self):
        """搜索页打开了：屏幕上有获得焦点的输入框。"""
        for n in self.screen.tree().iter("node"):
            if EDIT.search(n.get("class") or "") and n.get("focused") == "true" and self.screen.on_screen(n):
                return True
        return False

    def type_text(self, kw, timeout=4.0):
        """往当前输入框打字。部分机型（小米 HyperOS 设置搜索）用 setText 会卡住、一直打「%」：
        加超时，打完核对；不对就清掉、改用剪贴板粘贴；还不对就返回 False，不卡住。
        失败时不退场：离开搜索页只由调用方的 `_leave_search()` 做（沿用 #639 的做法）。"""
        if not self.edit_ready():
            return False

        def attempt(fn):
            try:
                fn()
            except Exception:
                return False
            time.sleep(0.4)
            return (self.focused_text() or "").strip() == kw

        def clear():
            if not self.edit_ready():
                return
            try:
                self.reader.jsonrpc.clearTextField(selector, http_timeout=timeout)
            except Exception:
                pass

        # 直接对已确认的输入框发有超时的 RPC，不启动无法取消的后台线程。
        # 旧线程超时后仍会等控件出现，可能在下一页补打文字；也不能退回任意 focused 节点（键盘也有）。
        selector = self.reader(classNameMatches=r".*(EditText|AutoCompleteTextView)$", focused=True).selector

        def set_text():
            self.reader.jsonrpc.setText(selector, kw, http_timeout=timeout)
        if attempt(set_text):
            return True
        if not self.edit_ready():
            return False
        clear()

        def paste():
            self.reader.jsonrpc.setClipboard(None, kw, http_timeout=timeout)
            self.reader.shell("input keyevent KEYCODE_PASTE", timeout=timeout)
        if attempt(paste):
            return True
        clear()
        return False

    def _search_page(self):
        """直接打开系统设置搜索页的动作（沿用 #650 的直达动作）。打得开返回真，否则交回设置首页那条老路。"""
        res = self.conn.reader.shell(f"am start -f 0x10008000 -a {SEARCH_ACTION}")
        out = str(getattr(res, "output", "") or "")
        if getattr(res, "exit_code", 0) or "Error" in out or "unable to resolve" in out.lower():
            return False
        return bool(wait.until(self.edit_ready, timeout=2.5, poll=0.15, now=time.time, sleep=time.sleep))

    def _leave_search(self):
        """离开设置搜索页并回到设置首页（沿用 #639 的退场做法）：按 BACK 收起键盘、退出搜索页，
        再拉起设置首页——直达搜索页时它是新任务根，BACK 会落到桌面而不是设置首页。
        搜索失败的各条路径共用这一处退场。"""
        if not self.edit_ready():
            return True
        for _ in range(3):
            self.screen.back()
            if not self.edit_ready():
                break
        else:
            return False
        self.conn.reader.shell("am start -f 0x10008000 -a android.settings.SETTINGS")
        time.sleep(0.5)
        return True

    def setting(self, kw, entry=None, box=None, path=None):
        """系统设置里搜 kw，点结果 entry（默认就是 kw）。
        box：搜索框文字，不给就自动认（小米「搜索系统设置项」、OPPO「搜索设置项」等）。
        path：结果下一行的位置文字（如「隐私与安全 > 隐私 > 设备标识与广告」）。同名结果有好几条时按它挑。
        先试直达搜索页的动作（ColorOS），没有就回设置首页点搜索框。
        设置首页刚打开时点搜索框会被忽略（小米 18 Pro Max 实测）：点完要看到输入框才往下走，没打开就再点。"""
        self.lost_note.miss = 0

        def box_at():
            for t, (l, tp, r, b), _ in self.screen.texts():
                if (box and box in t) or (not box and BOX.search(t)):
                    return ((l + r) // 2, (tp + b) // 2)
            return None

        def result_at():
            # 输入框里也有同一段文字；只认非输入框的结果，不能点回搜索框后假报成功。
            items = self.screen.texts()
            for i, (t, (l, tp, r, b), n) in enumerate(items):
                if t != (entry or kw) or EDIT.search(n.get("class", "")):
                    continue
                if path and not (i + 1 < len(items) and items[i + 1][0] == path):
                    continue
                return ((l + r) // 2, (tp + b) // 2)
            return None

        def give_up(msg):
            # 失败前把页面退回设置首页：留在搜索页上，调用方后续的滚屏会全落在输入法上（沿用 #639 的判据）
            self.screen.say(msg)
            if not self._leave_search():
                self.screen.say(f"  · 设置搜索页退不出去，当前停在 {self.screen.focus()}")
            return False

        opened = self._search_page()
        if not opened:
            self.conn.reader.shell("am start -f 0x10008000 -a android.settings.SETTINGS")
            for _ in range(4):
                xy = wait.until(box_at, timeout=3, poll=0.15, now=time.time, sleep=time.sleep)
                if not xy:
                    break
                time.sleep(0.4)                      # 首页还在加载时点击会被吞
                self.screen.click(*xy)
                opened = bool(wait.until(self.edit_ready, timeout=2, poll=0.15,
                                         now=time.time, sleep=time.sleep))
                if opened:
                    break
        if not opened:
            return give_up(f"  ✗ 设置搜索框没打开，跳过「{kw}」")
        if not self.type_text(kw):
            return give_up(f"  ✗ 设置搜索框输入「{kw}」失败，跳过")
        xy = wait.until(result_at, timeout=3, poll=0.15, now=time.time, sleep=time.sleep)
        if not xy:
            return give_up(f"  ✗ 没搜到「{entry or kw}」，跳过")
        before = self.screen.focus()
        self.screen.click(*xy)

        def left_search():
            return self.screen.focus() != before or not self.edit_ready()

        if not wait.until(left_search, timeout=3, poll=0.15, now=time.time, sleep=time.sleep):
            return give_up(f"  ✗ 搜索结果「{entry or kw}」没有打开，跳过")
        time.sleep(0.3)                      # 结果页起来了，给它的内容留一拍
        return True
