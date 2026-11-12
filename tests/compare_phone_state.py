"""纯重构的对拍驱动：同一份页面样本喂给两份 `tool/`，比较可观察输出。

基线取改动前的提交，样本取本仓库 `tests/` 里的 `<hierarchy>` 字面量。驱动自己拉临时
worktree、跑完删掉：

    python tests/compare_phone_state.py --baseline <改动前的提交>

也可以手工备好一份 worktree，把它的 tool 目录传进来：

    git worktree add /tmp/aac-baseline <改动前的提交>
    python tests/compare_phone_state.py /tmp/aac-baseline/tool

比九处：`Phone.texts()`（页面 × 两种屏尺寸 × 读屏策略开 / 关）、
`explore.entries()`（页面 × 包名）、`Phone.off()`（两种屏尺寸 × 安全模式 × 三档 `only`）、
`Phone.tap()` / `Phone._promoted_click()`（丢失记录与推广位已带前置状态的几条路径）、
`Screen.confirm_target()`（改前是 `Phone._confirm_target()`）/ `residual_confirm()` / `residual_note()`（确认框判定与残留提示）、
`Phone.start()`（启动与落点）、`Phone.setting()` / `Phone.type_text()`（设置搜索的往返与打字退化链）、
`Phone.dismiss()`（四条弹窗退化链与推广位退回，另加全仓页面样本的扫描）、
`Phone.tap()` / `go()` / `enter()` / `entry()` / `tab()` / `tap_icon()` / `top()` /
`await_page()` / `in_settings_page()`（导航的命中、失败语义、换页校验、底栏带与回顶）。
两边必须各起一个子进程：模块名相同，同进程里 import 不了两份 `fast`。

结论不只看「相等」——驱动同时打印守卫数字（策略 / 包名 / `off` 每个场景点到了哪些标题，
会话样本真的走到了「快速放弃」与「推广位退回」两支，确认框样本真的认出了弹窗），
全是 0 或某一支退化了就说明对拍什么也没测到。
"""
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tool"))
from stdio import use_utf8_console  # noqa: E402  出口取当前副本的，不对拍基线的那一份

use_utf8_console()

TESTS = Path(__file__).resolve().parent

SIZES = ((1080, 2340), (720, 1600))

# 推广位样本的焦点轴：点击（0.05 秒）加 sleep(0.6) 之后前台已经换成商店，
# back 一次（0.05 秒）加 sleep(0.4) 之后回到原 App —— `_promoted_click()` 的判据两段都走得到。
PROMO_FOCUS = ((0.0, "com.promo/Main"), (0.06, "com.shop/Promo"), (0.72, "com.promo/Main"))

# 启动样本的包与页面：底栏带判据词「我的」，推广页只有推荐卡片、没有它（#420 的两种落点）。
LAUNCH_PKG = "com.example.target"
LAUNCH_APP = LAUNCH_PKG + "/.MainActivity"
LAUNCH_OTHER = "com.example.other/.Account"
LAUNCH_HOME = f'''<hierarchy rotation="0"><node package="{LAUNCH_PKG}" bounds="[0,0][1080,2340]">
  <node class="android.widget.TextView" text="首页" bounds="[60,300][600,380]"/>
  <node class="android.widget.TextView" text="我的" clickable="true" bounds="[860,2180][1020,2260]"/>
</node></hierarchy>'''
LAUNCH_PROMO = f'''<hierarchy rotation="0"><node package="{LAUNCH_PKG}" bounds="[0,0][1080,2340]">
  <node class="android.widget.TextView" text="推荐 1 款应用" bounds="[60,300][900,380]"/>
  <node class="android.widget.TextView" text="推荐 2 款应用" bounds="[60,420][900,500]"/>
</node></hierarchy>'''

# 弹窗样本（#1043）：权限页的两支、✕ 图标的四道守卫、更新标题、拒绝类按钮，以及形状像设置页的反例。
PERMISSION_DENY = '''<hierarchy rotation="0">
  <node package="com.android.permissioncontroller" bounds="[0,0][1080,2340]">
    <node package="com.android.permissioncontroller" class="android.widget.Button" text="允许" bounds="[100,1800][500,1940]"/>
    <node package="com.android.permissioncontroller" class="android.widget.Button" text="拒绝" bounds="[580,1800][980,1940]"/>
  </node>
</hierarchy>'''
PERMISSION_ALLOW_ONLY = '''<hierarchy rotation="0">
  <node package="com.android.permissioncontroller" bounds="[0,0][1080,2340]">
    <node package="com.android.permissioncontroller" class="android.widget.Button" text="允许" bounds="[100,1800][500,1940]"/>
  </node>
</hierarchy>'''
# 纯图标的广告弹窗：desc 读作「关闭」，页面上没有开关、也没有可滚动列表
POPUP_CLOSE = '''<hierarchy rotation="0">
  <node package="com.vivo.browser" bounds="[0,0][1080,2340]">
    <node class="android.widget.TextView" text="推荐内容" bounds="[140,660][900,720]"/>
    <node class="android.widget.ImageView" content-desc="关闭" clickable="true"
          resource-id="com.vivo.browser:id/iv_close" bounds="[900,600][990,690]"/>
  </node>
</hierarchy>'''
# 守卫一：desc 精确读作「返回」的是浮层自己的返回键，点了是导航（沿用 #753）
POPUP_BACK_LABEL = POPUP_CLOSE.replace('content-desc="关闭"', 'content-desc="返回"')
# 守卫二：列表里卡片的 ✕ 点了会打开别的页面
POPUP_IN_LIST = '''<hierarchy rotation="0">
  <node package="com.android.settings" bounds="[0,0][1080,2340]">
    <node class="android.widget.ListView" scrollable="true" bounds="[0,300][1080,2200]">
      <node class="android.widget.ImageView" content-desc="关闭" clickable="true"
            resource-id="com.android.settings:id/close_hint" bounds="[900,600][990,690]"/>
    </node>
  </node>
</hierarchy>'''
# 守卫三：含「关闭」的说明行本身就是开关，点它等于替用户拨一次（沿用 #378）
POPUP_SWITCH_ROW = '''<hierarchy rotation="0">
  <node package="com.android.settings" bounds="[0,0][1080,2340]">
    <node text="个性化广告推荐" bounds="[60,300][900,380]"/>
    <node class="android.widget.LinearLayout" content-desc="关闭后，广告内容的相关性会降低" clickable="true"
          bounds="[900,420][1060,560]">
      <node class="android.widget.Switch" checkable="true" checked="true" bounds="[920,440][1040,540]"/>
    </node>
  </node>
</hierarchy>'''
# 守卫四：尺寸越界的图标不点（整行 / 整块卡片会进别的页面）
POPUP_TOO_WIDE = POPUP_CLOSE.replace('bounds="[900,600][990,690]"', 'bounds="[100,600][980,690]"')
# 更新弹窗：标题在可滚动容器里，下面的「带滚动列表」守卫会漏掉它，所以先按标题认（沿用 #286）
UPDATE_POPUP = '''<hierarchy rotation="0">
  <node package="com.heytap.themestore" bounds="[0,0][1080,2340]">
    <node class="android.widget.ScrollView" scrollable="true" bounds="[0,300][1080,2000]">
      <node class="android.widget.TextView" text="检测到新版本" bounds="[140,660][900,720]"/>
      <node class="android.widget.TextView" text="修复了一些问题" bounds="[140,760][900,820]"/>
    </node>
    <node class="android.widget.Button" text="取消" clickable="true" bounds="[100,2100][500,2240]"/>
  </node>
</hierarchy>'''
# 拒绝类按钮：小弹窗、没有开关也没有滚动列表
REFUSE_POPUP = '''<hierarchy rotation="0">
  <node package="com.some.app" bounds="[0,0][1080,2340]">
    <node class="android.widget.TextView" text="要开启通知吗" bounds="[140,660][900,720]"/>
    <node class="android.widget.Button" text="同意" clickable="true" bounds="[100,1100][500,1240]"/>
    <node class="android.widget.Button" text="不同意" clickable="true" bounds="[580,1100][980,1240]"/>
  </node>
</hierarchy>'''
# 反例一：文字太多，像一个正常页面，不当弹窗
MANY_TEXTS_POPUP = ('<hierarchy rotation="0"><node package="com.some.app" bounds="[0,0][1080,2340]">'
                    + "".join(f'<node class="android.widget.TextView" text="第 {i} 项" bounds="[60,{200 + i * 100}][900,{280 + i * 100}]"/>'
                              for i in range(17))
                    + '<node class="android.widget.Button" text="取消" clickable="true" bounds="[100,2100][500,2240]"/>'
                    + '</node></hierarchy>')
# 反例二：正常设置面板也有「取消」，带开关或滚动列表的页面不能仅凭文字当弹窗关掉
SETTINGS_WITH_SWITCH = '''<hierarchy rotation="0">
  <node package="com.android.settings" bounds="[0,0][1080,2340]">
    <node class="android.widget.TextView" text="自动更新" bounds="[60,300][900,380]"/>
    <node class="android.widget.Switch" checkable="true" checked="true" bounds="[900,300][1060,400]"/>
    <node class="android.widget.Button" text="取消" clickable="true" bounds="[100,2100][500,2240]"/>
  </node>
</hierarchy>'''

# 挂在屏上的确认框：没有「取消」这类 DISMISS 词，`dismiss()` 关不掉它，才叫「残留」。
DIALOG_PAGE = '''<hierarchy rotation="0">
  <node package="com.vivo.appstore" bounds="[0,0][1080,2340]">
    <node text="个性化推荐" bounds="[60,300][700,400]"/>
    <node class="android.widget.Switch" checkable="true" checked="true" bounds="[900,300][1060,400]"/>
    <node class="android.widget.Button" content-desc="确认关闭" clickable="true" bounds="[270,1900][810,2040]"/>
  </node>
</hierarchy>'''

TWO_WINDOWS = '''<hierarchy rotation="0">
  <node package="com.android.settings" text="隐私" bounds="[60,300][400,360]"/>
  <node package="com.example.overlay" text="别的窗口" bounds="[60,420][400,480]"/>
  <node package="com.android.settings" text="广告" bounds="[60,540][400,600]"/>
</hierarchy>'''

# 导航的样本（#1044）：内容区一行「设置」+ 底栏一个「我的」+ 一个可滚动列表。
# 两种屏尺寸都按 `fit()` 缩放，底栏那行的上沿仍在 85% 屏高之下（2180/2340 = 0.93）。
NAV_PAGE = '''<hierarchy rotation="0">
  <node package="com.example.app" bounds="[0,0][1080,2340]">
    <node class="android.widget.ListView" scrollable="true" bounds="[0,300][1080,2100]">
      <node class="android.widget.TextView" text="设置" clickable="true" bounds="[60,400][900,500]"/>
    </node>
    <node class="android.widget.TextView" text="我的" clickable="true" bounds="[860,2180][1020,2260]"/>
  </node>
</hierarchy>'''
# 内容区有同名的「我的」，底栏那个带角标：底栏带外的那一个不能被点
NAV_DUP_TAB = NAV_PAGE.replace(
    '<node class="android.widget.TextView" text="我的" clickable="true" bounds="[860,2180][1020,2260]"/>',
    '<node class="android.widget.TextView" text="我的奇妙小镇" clickable="true" bounds="[60,900][900,1000]"/>\n'
    '    <node class="android.widget.TextView" text="我的, 2个应用待更新, 共5个" clickable="true"'
    ' bounds="[860,2180][1020,2260]"/>')
# 底栏带边界：0.85 屏高处换一个像素就换结论（常量被搬动时边界样本才会变红）
def nav_tab_at(top):
    return NAV_PAGE.replace('bounds="[860,2180][1020,2260]"', f'bounds="[860,{top}][1020,{top + 80}]"')


NAV_TAB_BELOW = nav_tab_at(1985)      # 1985/2340 = 0.848：带外，不点
NAV_TAB_INSIDE = nav_tab_at(1995)     # 1995/2340 = 0.853：带内，要点
# 没有底栏（开屏推荐页的样子）：`tab()` 找不到就返回假，`tap(scrolls=0)` 一直等到 6 秒
NAV_NO_TAB = '''<hierarchy rotation="0">
  <node package="com.example.app" bounds="[0,0][1080,2340]">
    <node class="android.widget.TextView" text="推荐 1 款应用" bounds="[60,300][900,380]"/>
    <node class="android.widget.TextView" text="推荐 2 款应用" bounds="[60,420][900,500]"/>
  </node>
</hierarchy>'''
# 右上角两个没有文字的图标（#292）：点第一个就开出带「设置」的新页
NAV_ICONS = '''<hierarchy rotation="0">
  <node package="com.example.app" bounds="[0,0][1080,2340]">
    <node class="android.widget.ImageView" clickable="true" bounds="[900,120][990,210]"/>
    <node class="android.widget.ImageView" clickable="true" bounds="[1000,120][1070,210]"/>
    <node class="android.widget.TextView" text="我的游戏" bounds="[60,600][900,700]"/>
  </node>
</hierarchy>'''
# 换页后的页面：`enter()` 与 `go()` 拿它当落点
NAV_NEXT = '''<hierarchy rotation="0">
  <node package="com.example.app" bounds="[0,0][1080,2340]">
    <node class="android.widget.TextView" text="隐私" clickable="true" bounds="[60,400][900,500]"/>
    <node class="android.widget.TextView" text="我的" clickable="true" bounds="[860,2180][1020,2260]"/>
  </node>
</hierarchy>'''
# 翻到底才找得到的一行：中心在 0.92H 之下，直接找落空，`edge_ok` 兜底才命中（#286 的兜底支）
NAV_EDGE = '''<hierarchy rotation="0">
  <node package="com.example.app" bounds="[0,0][1080,2340]">
    <node class="android.widget.ListView" scrollable="true" bounds="[0,300][1080,2100]">
      <node class="android.widget.TextView" text="第一条" clickable="true" bounds="[60,400][900,500]"/>
    </node>
    <node class="android.widget.TextView" text="底部条目" clickable="true" bounds="[60,2176][900,2280]"/>
  </node>
</hierarchy>'''
# 单屏面板：没有可滚动节点，`top()` 一次也不滑
NAV_FLAT = NAV_PAGE.replace('class="android.widget.ListView" scrollable="true"',
                            'class="android.widget.FrameLayout"')
NAV_FOCUS = ((0.0, "com.example.app/.SettingsActivity"),)

# 设置搜索的样本（#1042）：首页的搜索框、搜索页（输入框 + 结果行）、点开结果后的子页。
SEARCH_HOME = '''<hierarchy rotation="0"><node package="com.android.settings" bounds="[0,0][1080,2340]">
  <node class="android.widget.TextView" text="搜索设置项" clickable="true" bounds="[50,100][1030,200]"/>
</node></hierarchy>'''
# 首页的搜索框文案不匹配 BOX（「查找设置」而不是「搜索…设置」）：样本用 `box=` 显式指认它
FIND_HOME = SEARCH_HOME.replace("搜索设置项", "查找设置")
NO_BOX_HOME = '''<hierarchy rotation="0"><node package="com.android.settings" bounds="[0,0][1080,2340]">
  <node class="android.widget.TextView" text="网络与互联网" bounds="[50,300][1030,400]"/>
</node></hierarchy>'''
RESULT_PAGE = '''<hierarchy rotation="0"><node package="com.android.settings" bounds="[0,0][1080,2340]">
  <node class="android.widget.TextView" text="设备标识与广告" bounds="[50,300][1030,400]"/>
</node></hierarchy>'''


def fit(page, size):
    """按比例把按 1080×2340 画的样本缩到目标屏尺寸（对拍标准：样本几何在每种尺寸下都要可达）。"""
    width, height = size
    base_w, base_h = SIZES[0]

    def scale(match):
        l, t, r, b = (int(v) for v in match.groups())
        return f'bounds="[{l * width // base_w},{t * height // base_h}][{r * width // base_w},{b * height // base_h}]"'
    return page if size == SIZES[0] else re.sub(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', scale, page)


def search_page(text="广告", rows=(("广告服务", 400),)):
    """搜索页：获得焦点的输入框（文字由 text 给）+ 结果行。"""
    body = "".join(f'<node class="android.widget.TextView" text="{t}" bounds="[50,{y}][1000,{y + 100}]"/>'
                   for t, y in rows)
    return ('<hierarchy rotation="0"><node package="com.android.settings" bounds="[0,0][1080,2340]">'
            f'<node class="android.widget.EditText" text="{text}" focused="true" bounds="[50,100][1000,200]"/>'
            f'{body}</node></hierarchy>')

def switch_page(w, h):
    """按屏宽高参数化的开关页：普通、保护、带外都有，两种尺寸下都可达。

    带内两行贴着 8% / 98.5% 边界放（0.077 / 0.929），常量一改分类就变；
    带外两行完全在屏内，只有中心越界——否则「没点」分不清是被过滤还是没读到。
    守卫按标题回认点击坐标，所以这里同时交回每行开关的中心点。
    """
    rows = [("顶部广告", True, 0.02), ("上边缘广告", True, 0.077), ("广告推荐", True, 0.20),
            ("猜你喜欢", False, 0.35), ("限制广告跟踪", False, 0.50), ("防止广告追踪", True, 0.65),
            ("下边缘广告", True, 0.929), ("底部广告", True, 0.985)]
    row_h = max(12, h // 60)
    nodes, coords = [], {}
    for title, checked, ratio in rows:
        y0 = min(int(h * ratio), h - row_h)
        y1 = y0 + row_h
        l, r = int(w * 0.88), int(w * 0.98)
        nodes.append(
            f'  <node package="com.android.settings" clickable="true" bounds="[0,{y0}][{w},{y1}]">\n'
            f'    <node text="{title}" bounds="[{int(w * 0.05)},{y0 + 2}][{int(w * 0.4)},{y1 - 2}]"/>\n'
            f'    <node class="android.widget.Switch" checkable="true" checked="{str(checked).lower()}"'
            f' bounds="[{l},{y0}][{r},{y1}]"/>\n'
            f'  </node>')
        coords[title] = ((l + r) // 2, (y0 + y1) // 2)
    return '<hierarchy rotation="0">\n' + "\n".join(nodes) + '\n</hierarchy>', coords


def dump(tool_dir):
    """跑一份 `tool/`，把三处可观察输出整理成 JSON。"""
    sys.path.insert(0, str(TESTS))
    sys.path.insert(0, tool_dir)
    import fast
    import explore
    import fixtures

    def page_phone(xml, size):
        p = fixtures.phone_stub("test", fast_mod=fast)
        p.W, p.H = size
        p.d = fixtures.Device(fixtures.Timeline([(0.0, xml)]), size, fixtures.Clock())
        return p

    def texts():
        out = []
        for label, xml in fixtures.all_pages(str(TESTS)):
            for size in SIZES:
                for flag in (False, True):
                    p = page_phone(xml, size)
                    p.sysui = flag            # 改前的名字
                    p.systemui_text = flag    # 改后的名字
                    try:
                        got = [(t, b) for t, b, _ in p.texts(ET.fromstring(xml))]
                    except Exception as e:
                        got = ["ERROR", type(e).__name__]
                    out.append({"id": f"{label}|{size}|{flag}", "got": got})
        return out

    def entries():
        takes_pkg = explore.entries.__code__.co_argcount == 2      # 改前 1 个参数，改后 2 个
        out = []
        for label, xml in [("two-windows", TWO_WINDOWS)] + fixtures.all_pages(str(TESTS)):
            p = page_phone(xml, SIZES[0])
            for pkg in ("com.android.settings", ""):
                try:
                    if takes_pkg:
                        got = explore.entries(p, pkg)
                    else:
                        p.pkg_now = pkg
                        got = explore.entries(p)
                except Exception as e:
                    got = ["ERROR", type(e).__name__]
                out.append({"id": f"{label}|{pkg}", "got": got})
        return out

    def off():
        out = []
        for size in SIZES:
            page, _ = switch_page(*size)
            for safe in (True, False):
                for only in (None, ["运营任务"], ["广告推荐"]):
                    clock = fixtures.Clock()
                    fixtures.install_clock(fast, clock)
                    lines, clicked = [], []
                    p = fixtures.fake_phone(clock=clock, size=size, stages=[(0.0, page)], fast_mod=fast,
                                            say=lines.append)
                    p.safe_mode = safe
                    click = lambda x, y, _c=clock, _a=clicked: (_c.click(), _a.append((x, y)))  # noqa: E731
                    p.click = p.screen.click = click    # 改前 off() 走门面、改后走观测基座
                    label = "None" if only is None else only[0]
                    previous = os.environ.pop("AAC_REF", None)
                    try:
                        if safe:
                            os.environ["AAC_REF"] = "1"   # 更早的实现靠环境变量；当前两版都忽略它
                        done = p.off(page="系统·广告服务", only=only)
                    finally:
                        os.environ.pop("AAC_REF", None)
                        if previous is not None:
                            os.environ["AAC_REF"] = previous
                    out.append({"id": f"{size[0]}x{size[1]}|safe={safe}|only={label}",
                                "done": done, "clicks": clock.clicks, "clicked": clicked,
                                "changed": p.changed, "lines": lines})
        return out

    def sessions():
        """三个会话对象的读写面（#1039）：`off()` 的样本每行都找得到、`miss` 恒 0，
        走不到 `tap` 按 `miss` 分流的那一支；`_promoted_click()` 也从没被对拍到过。
        状态换了归属之后，这两条路径要与改前逐一相同。"""
        out = []

        def tap_after_miss(miss):
            clock = fixtures.Clock()
            fixtures.install_clock(fast, clock)
            lines = []
            p = fixtures.fake_phone(clock=clock, fast_mod=fast, say=lines.append)
            p.miss = miss
            got = p.tap("页面上没有的文字")
            out.append({"id": f"tap|miss={miss}", "got": got, "miss": p.miss,
                        "missed": [list(x) for x in p.missed], "lines": lines})

        for miss in (0, 1):
            tap_after_miss(miss)

        for label, promoted in (("fresh", ()), ("seen", (("com.promo", "close icon"),))):
            clock = fixtures.Clock()
            fixtures.install_clock(fast, clock)
            lines, backs = [], []
            p = fixtures.fake_phone(clock=clock, fast_mod=fast, focus=PROMO_FOCUS, say=lines.append)
            p.app = "com.promo"
            p.promoted = set(promoted)
            fixtures.stub(p, "back", lambda *a, _c=clock, _b=backs, **k: (_c.click(), _b.append(round(_c.t, 3))))
            got = p._promoted_click(10, 20, "close icon")
            out.append({"id": f"promoted|{label}", "got": got, "backs": backs,
                        "promoted": sorted(p.promoted), "lines": lines})

        p = fixtures.phone_stub("test", fast_mod=fast)
        p.vivo_seen, p.skeleton_count, p.mismatch_probes = True, 1, 2
        p.skeleton_sigs.add("layout-a")
        out.append({"id": "channel|write-then-read",
                    "got": [p.vivo_seen, sorted(p.skeleton_sigs), p.skeleton_count, p.mismatch_probes]})
        return out

    def toggling():
        """确认框判定与残留提示（#1040）：判定搬进观测基座、句子降成 `row.residual_note()` 纯函数，
        两边对同一批页面要逐字相同。改前判定叫 `_confirm_target`，改后在基座上叫 `confirm_target`。"""
        out = []
        for label, xml in [("empty", fixtures.EMPTY_PAGE), ("dialog", DIALOG_PAGE)] \
                + fixtures.all_pages(str(TESTS)):
            for size in SIZES:
                p = page_phone(xml, size)
                root = ET.fromstring(xml)
                screen = getattr(p, "screen", p)     # noqa: B009 - 拆分前的树没有这个基座
                finder = screen.confirm_target if hasattr(screen, "confirm_target") else p._confirm_target
                target = finder()
                out.append({"id": f"target|{label}|{size}", "got": target})
                out.append({"id": f"confirm|{label}|{size}", "got": p.residual_confirm(root)})
                out.append({"id": f"note|{label}|{size}", "got": p.residual_note("；", root)})
        return out

    def launch():
        """启动与落点（#1041）：这段的对外可观察面是「启动后算不算还在目标 App」与「落点不对时报
        什么」，所以样本按分支铺开——正常进入、空焦点顺延（8 秒硬停）、确知外占（5 秒预算）、
        持续被外占、落点可恢复、落点不可恢复，以及启动命令失败的断线与缺包两支。
        每条都记抛没抛、抛的原文、诊断行与耗时，两边逐字比。"""
        out = []

        def case(label, stages, focus, expect=("我的",), prepare=None):
            clock = fixtures.Clock()
            fixtures.install_clock(fast, clock)
            lines = []
            p = fixtures.fake_phone(clock=clock, stages=stages, focus=focus, fast_mod=fast,
                                    say=lines.append)
            if prepare:
                prepare(p, clock)
            err = None
            try:
                p.start(LAUNCH_PKG, settle=0, expect=expect)
            except Exception as e:                   # noqa: BLE001 - 对拍要的是原文，不是分类
                err = f"{type(e).__name__}: {e}"
            out.append({"id": label, "err": err, "lines": lines, "t": round(clock.t, 2),
                        "reads": clock.page_reads, "clicks": clock.clicks,
                        "promoted": sorted(p.promoted)})

        case("enter", [(0.0, fixtures.EMPTY_PAGE), (0.6, LAUNCH_HOME)],
             focus=((0.0, ""), (0.6, LAUNCH_APP)))
        case("empty-focus-6s", [(0.0, fixtures.EMPTY_PAGE), (6.0, LAUNCH_HOME)],
             focus=((0.0, ""), (6.0, LAUNCH_APP)))
        case("never-enters", [(0.0, fixtures.EMPTY_PAGE)], focus=((0.0, ""),), expect=None)
        case("foreign-sustained", [(0.0, fixtures.EMPTY_PAGE), (1.0, LAUNCH_HOME)],
             focus=((0.0, ""), (0.3, LAUNCH_APP), (0.6, LAUNCH_OTHER)))
        case("landing-fail", [(0.0, LAUNCH_PROMO)], focus=((0.0, LAUNCH_APP),))
        case("landing-recovered", [(0.0, LAUNCH_PROMO), (30.0, LAUNCH_HOME)],
             focus=((0.0, LAUNCH_APP),),
             prepare=lambda p, clock: fixtures.stub(p, "back", lambda *a, **k: clock.sleep(30)))
        # 确知外占的 5 秒预算：与空焦点的 8 秒硬停是两条路径（#581），只有确知不是目标 App 才计数
        case("stuck-in-other", [(0.0, LAUNCH_HOME)], focus=((0.0, LAUNCH_OTHER),), expect=None)

        def shell_reply(output, rc, only=None):
            """启动命令返回什么。`only` 给子串时只让命中的那条命令失败，其余照常成功
            （缺包样本要让 `am start` 失败、`pm path` 返回空，而不是整条传输都坏）。"""
            def shell(cmd, timeout=60):
                failed = only is None or only in cmd
                return SimpleNamespace(output=output if failed else "", exit_code=rc if failed else 0)
            return shell

        # 启动命令失败的两支（#293 / #908）：断线要报断线，包不在要按跳过收尾。
        # `detached()` 会跑真 adb，样本里按「没有 adb」处理，否则假序列号一律被判成断线。
        real_adb = fast.adb_link.detached
        fast.adb_link.detached = lambda serial, adb=None: False
        try:
            case("link-lost", [(0.0, LAUNCH_HOME)], focus=((0.0, LAUNCH_APP),), expect=None,
                 prepare=lambda p, clock: setattr(p.d, "shell",
                                                  shell_reply("error: device 'x' not found", 1)))
            case("missing-package", [(0.0, LAUNCH_HOME)], focus=((0.0, LAUNCH_APP),), expect=None,
                 prepare=lambda p, clock: setattr(p.d, "shell",
                                                  shell_reply("monkey aborted", 1, only="monkey")))
        finally:
            fast.adb_link.detached = real_adb
        return out

    def search():
        """设置搜索的往返（#1042）：开搜索页（直达动作 / 回设置首页两条路）、打字的三级退化、
        找结果、点开、退场。对外语义是「找不到就只返回假」——每个失败样本都记返回假、退场命令
        与那句说明，两边逐字比。

        每条样本在两种屏尺寸下各跑一遍：样本按 1080×2340 画，`fit()` 缩到另一档，
        坐标与识别都不许只在一种宽度下成立。目标分支按标准各配一条：断线（读屏抛 `DeviceLost`）、
        清空输入框抛错、输入失败后已不在搜索页、退场三次 BACK 仍不退。
        """
        out = []
        ok = lambda cmd=None: SimpleNamespace(exit_code=0, output="Starting: Intent")           # noqa: E731
        no_action = lambda: SimpleNamespace(exit_code=1, output="Error: Activity not started,"  # noqa: E731
                                            " unable to resolve Intent")

        def build(size, *, page, replies=None, after_box=None, after_result=None,
                  fail_set=False, fail_paste=False, fail_clear=False, set_fail_page=None,
                  paste_page=None, back_works=True, lost=False):
            """一套假手机：页面按 `state` 切换，点击与返回只记账。两种树都吃同一份输入。"""
            clock = fixtures.Clock()
            fixtures.install_clock(fast, clock)
            commands, posts, clicks, backs, lines = [], [], [], [], []
            p = fixtures.phone_stub("search", fast_mod=fast)
            p.W, p.H = size
            p.d = fixtures.Device(fixtures.Timeline([(0.0, fixtures.EMPTY_PAGE)]), size, clock)
            state = {"page": fit(page, size)}
            p.d.shell = lambda cmd, timeout=60: (commands.append(cmd), (replies or ok)(cmd))[1]

            def set_text(selector, text, http_timeout=None):
                posts.append(["setText", text])
                if fail_set:
                    if set_fail_page:
                        state["page"] = fit(set_fail_page, size)
                    raise TimeoutError()

            def clear_field(*a, **k):
                posts.append(["clear"])
                if fail_clear:
                    raise RuntimeError("清不掉输入框")

            def clipboard(label, text, http_timeout=None):
                posts.append(["paste", text])
                if fail_paste:
                    raise TimeoutError()
                if paste_page:
                    state["page"] = fit(paste_page, size)

            p.d.jsonrpc = SimpleNamespace(setText=set_text, clearTextField=clear_field,
                                          setClipboard=clipboard)

            def tree():
                if lost:
                    clock.read()
                    raise fast.adb_link.DeviceLost("手机断线了")
                clock.read()
                return ET.fromstring(state["page"])
            p.screen.tree = tree

            def click(x, y):
                searching = "android.widget.EditText" in state["page"]
                clicks.append([x, y, "result" if searching else "box"])
                clock.click()
                if searching and after_result:
                    state["page"] = fit(after_result, size)
                elif not searching and after_box:
                    state["page"] = fit(after_box, size)
            p.screen.click = click

            def back(*a, **k):
                clock.click()
                backs.append(round(clock.t, 2))
                if back_works:
                    state["page"] = fit(SEARCH_HOME, size)
            p.screen.back = back
            fixtures.stub(p, "say", lambda *a: lines.append(" ".join(str(x) for x in a)))
            return p, clock, {"commands": commands, "posts": posts, "clicks": clicks,
                              "backs": backs, "lines": lines}

        def record(label, call, **kw):
            recs = []
            for size in SIZES:
                p, clock, rec = build(size, **kw)
                try:
                    rec["got"] = call(p)
                except Exception as e:                   # noqa: BLE001 - 对拍要的是原文，不是分类
                    rec["err"] = f"{type(e).__name__}: {e}"
                rec.update({"id": f"{label}|{size[0]}x{size[1]}", "t": round(clock.t, 2),
                            "reads": clock.page_reads})
                out.append(rec)
                recs.append(rec)
            return recs

        record("setting|direct", lambda p: p.setting("广告", entry="广告服务"),
               page=search_page(), after_result=RESULT_PAGE)
        record("setting|fallback", lambda p: p.setting("广告", entry="广告服务"),
               page=SEARCH_HOME, after_box=search_page(), after_result=RESULT_PAGE,
               replies=lambda cmd: no_action() if "MAIN_SEARCH" in cmd else ok())
        record("setting|no-box", lambda p: p.setting("广告", entry="广告服务"), page=NO_BOX_HOME,
               replies=lambda cmd: no_action() if "MAIN_SEARCH" in cmd else ok())
        record("setting|type-fail", lambda p: p.setting("广告", entry="广告服务"),
               page=search_page(text=""), fail_set=True, fail_paste=True)
        record("setting|no-result", lambda p: p.setting("广告", entry="广告服务"),
               page=search_page(rows=()))
        record("setting|not-opened", lambda p: p.setting("广告", entry="广告服务"), page=search_page())
        record("setting|leave-stuck", lambda p: p.setting("广告", entry="广告服务"),
               page=search_page(rows=()), back_works=False)
        record("setting|link-lost", lambda p: p.setting("广告", entry="广告服务"),
               page=search_page(), lost=True)
        # 不带 path 会点第一行「广告」（400 起，中心 450）；带 path 要跳过它，点第三行（600 起，中心 650）
        record("setting|path-picks-row", lambda p: p.setting("广告", entry="广告",
                                                             path="隐私 > 广告"),
               page=search_page(rows=(("广告", 400), ("其他 > 广告", 450),
                                      ("广告", 600), ("隐私 > 广告", 650))),
               after_result=RESULT_PAGE)
        record("setting|box-hint", lambda p: p.setting("广告", entry="广告服务", box="查找设置"),
               page=FIND_HOME, after_box=search_page(), after_result=RESULT_PAGE,
               replies=lambda cmd: no_action() if "MAIN_SEARCH" in cmd else ok())

        # 打字的三级退化：setText → 清掉 → 剪贴板粘贴 → 返回假
        record("type|set-text", lambda p: p.type_text("广告", timeout=0.5), page=search_page())
        record("type|clipboard", lambda p: p.type_text("广告", timeout=0.5),
               page=search_page(text=""), fail_set=True, paste_page=search_page())
        record("type|clear-raises", lambda p: p.type_text("广告", timeout=0.5),
               page=search_page(text=""), fail_set=True, fail_clear=True, paste_page=search_page())
        record("type|unverified", lambda p: p.type_text("广告", timeout=0.5),
               page=search_page(text="%%"), fail_set=True, fail_paste=True)
        record("type|left-search-after-fail", lambda p: p.type_text("广告", timeout=0.5),
               page=search_page(), fail_set=True, set_fail_page=SEARCH_HOME)
        record("type|not-ready", lambda p: p.type_text("广告", timeout=0.5), page=SEARCH_HOME)
        return out

    def dismiss():
        """弹窗与推广位（#1043）：四条退化链各自要走到，四道守卫各自要挡下，推广位退回还要退回原 App。
        每条样本记返回值、点击坐标、返回次数、诊断行与耗时，两边逐字比；最后把全仓页面样本也扫一遍，
        防「只在造出来的页面上对得上」。"""
        out = []
        settings = "com.android.settings/.Settings"
        permission = "com.android.permissioncontroller/.permission.ui.GrantPermissionsActivity"

        def run(label, page, focus=settings, app="", promote=False):
            for size in SIZES:
                clock = fixtures.Clock()
                fixtures.install_clock(fast, clock)
                lines, clicks, backs = [], [], []
                axis = ((0.0, focus),) if not promote else PROMO_FOCUS
                p = fixtures.fake_phone(clock=clock, size=size, stages=[(0.0, fit(page, size))],
                                        focus=axis, fast_mod=fast, say=lines.append)
                p.app = app
                p.__dict__.pop("dismiss", None)      # `fake_phone()` 默认把 dismiss 桩成空：这一段要真的跑它
                click = lambda x, y, _c=clock, _a=clicks: (_c.click(), _a.append((x, y)))  # noqa: E731
                p.click = p.screen.click = click     # 改前 dismiss() 走门面、改后走观测基座
                p.screen.back = lambda *a, _c=clock, _b=backs, **k: (_c.click(), _b.append(round(_c.t, 2)))
                try:
                    got = p.dismiss()
                except Exception as e:                   # noqa: BLE001 - 对拍要的是原文，不是分类
                    got = f"{type(e).__name__}: {e}"
                out.append({"id": f"{label}|{size[0]}x{size[1]}", "got": got, "clicks": clicks,
                            "backs": backs, "promoted": sorted(p.promoted), "lines": lines,
                            "t": round(clock.t, 2), "reads": clock.page_reads})

        run("permission|deny", PERMISSION_DENY, focus=permission)
        run("permission|allow-only", PERMISSION_ALLOW_ONLY, focus=permission)
        run("close|icon", POPUP_CLOSE)
        run("close|back-label", POPUP_BACK_LABEL)
        run("close|in-list", POPUP_IN_LIST)
        run("close|switch-row", POPUP_SWITCH_ROW)
        run("close|too-wide", POPUP_TOO_WIDE)
        run("update|title", UPDATE_POPUP)
        run("refuse|word", REFUSE_POPUP)
        run("guard|many-texts", MANY_TEXTS_POPUP)
        run("guard|page-with-switch", SETTINGS_WITH_SWITCH)
        # 推广位：点的是目标 App 里的 ✕，点完前台换成商店，退回原 App 并记下这一处
        run("promoted|fallback", POPUP_CLOSE.replace('package="com.vivo.browser"', 'package="com.promo"')
            .replace("com.vivo.browser:id/iv_close", "com.promo:id/iv_close"),
            app="com.promo", promote=True)
        for label, xml in fixtures.all_pages(str(TESTS)):
            run(f"page|{label}", xml)
        return out

    def navigation():
        """导航（#1044）：命中、失败语义、换页校验、底栏带与回顶各走一遍。
        每条样本记返回值 / 异常原文、点击坐标、返回次数、滑动次数、诊断行、丢失记录与耗时，
        两边逐字比；走没走到目标分支由 `navigation_guards()` 核对。"""
        out = []

        def lost_tree(phone, after=0):
            """读屏替身：读满 `after` 次之后抛断线（0 = 第一读就断）。"""
            real, seen = phone.screen.tree, {"n": 0}

            def tree():
                seen["n"] += 1
                if seen["n"] > after:
                    raise fast.adb_link.DeviceLost("手机断线了")
                return real()
            return tree

        def run(label, call, stages=((0.0, NAV_PAGE),), focus=NAV_FOCUS, miss=0, setup=None):
            for size in SIZES:
                clock = fixtures.Clock()
                fixtures.install_clock(fast, clock)
                lines, clicks, backs, scrolls = [], [], [], []
                p = fixtures.fake_phone(clock=clock, size=size,
                                        stages=[(t, fit(xml, size)) for t, xml in stages],
                                        focus=focus, fast_mod=fast)
                p.miss = miss
                click = lambda x, y, _c=clock, _a=clicks: (_c.click(), _a.append([x, y]))  # noqa: E731
                p.click = p.screen.click = click     # 改前导航走门面、改后走观测基座
                back = lambda *a, _c=clock, _b=backs, **k: (_c.click(), _b.append(round(_c.t, 2)))  # noqa: E731
                p.back = p.screen.back = back
                p.screen.scroll = lambda *a, _s=scrolls, **k: _s.append(list(a))
                fixtures.stub(p, "say", lambda *a, _l=lines: _l.append(" ".join(str(x) for x in a)))
                if setup is not None:
                    setup(p, clock)
                try:
                    got, err = call(p), None
                except Exception as e:                   # noqa: BLE001 - 对拍要的是原文，不是分类
                    got, err = None, f"{type(e).__name__}: {e}"
                out.append({"id": f"{label}|{size[0]}x{size[1]}", "got": got, "err": err,
                            "clicks": clicks, "backs": backs, "scrolls": len(scrolls),
                            "miss": p.miss, "lines": lines,
                            "t": round(clock.t, 2), "reads": clock.page_reads})

        run("tab|hit", lambda p: p.tab("我的"))
        run("tab|content-same-name", lambda p: p.tab("我的"), stages=((0.0, NAV_DUP_TAB),))
        run("tab|missing", lambda p: p.tab("我的", maxwait=0), stages=((0.0, NAV_NO_TAB),))
        run("tab|below-band", lambda p: p.tab("我的", maxwait=0), stages=((0.0, NAV_TAB_BELOW),))
        run("tab|inside-band", lambda p: p.tab("我的"), stages=((0.0, NAV_TAB_INSIDE),))
        run("tab|late", lambda p: p.tab("我的"),
            stages=((0.0, fixtures.EMPTY_PAGE), (1.0, NAV_PAGE)))
        run("tap|found", lambda p: p.tap("设置"))
        run("tap|bottom-bar-late", lambda p: p.tap("我的", exact=True, scrolls=0),
            stages=((0.0, NAV_NO_TAB), (4.4, NAV_PAGE)))
        run("tap|bottom-bar-timeout", lambda p: p.tap("我的", exact=True, scrolls=0),
            stages=((0.0, NAV_NO_TAB),))
        run("tap|missing", lambda p: p.tap("没有的字", scrolls=2))
        run("tap|after-miss", lambda p: p.tap("设置"), miss=1)
        run("tap|miss-then-give-up", lambda p: p.tap("没有的字", scrolls=2), miss=1)
        run("entry|found", lambda p: p.entry("设置"))
        run("entry|missing", lambda p: p.entry("没有的字"))
        run("enter|lands", lambda p: p.enter("设置"),
            stages=((0.0, NAV_PAGE), (0.6, NAV_NEXT)))
        run("enter|no-change", lambda p: p.enter("设置"))
        run("enter|missing", lambda p: p.enter("没有的字"))
        run("go|lands", lambda p: p.go("设置", "隐私"),
            stages=((0.0, NAV_PAGE), (0.6, NAV_NEXT)))
        run("go|misses", lambda p: p.go("设置", "不存在的字"))
        run("tap_icon|first", lambda p: p.tap_icon("隐私"),
            stages=((0.0, NAV_ICONS), (0.6, NAV_NEXT)))
        run("tap_icon|none", lambda p: p.tap_icon("设置"), stages=((0.0, NAV_ICONS),))
        run("tap|edge-fallback", lambda p: p.tap("底部条目", scrolls=1), stages=((0.0, NAV_EDGE),))
        # 断线两种各一条：开跑前就断（tap 的第一读）与跑到一半断（entry 等完页、找入口时才掉）
        run("tap|link-lost", lambda p: p.tap("设置"),
            setup=lambda p, c: setattr(p.screen, "tree", lost_tree(p)))
        run("entry|link-lost", lambda p: p.entry("设置"),
            setup=lambda p, c: setattr(p.screen, "tree", lost_tree(p, after=4)))
        run("top|leaves-page", lambda p: p.top(),
            setup=lambda p, c: fixtures.stub(p, "focus", iter(["com.example.app/.Settings",
                                                              "com.other/.Main"]).__next__))
        run("top|stops-at-top", lambda p: p.top())
        run("top|no-scrollable", lambda p: p.top(), stages=((0.0, NAV_FLAT),))
        run("page|in-settings", lambda p: p.in_settings_page())
        run("page|not-settings", lambda p: p.in_settings_page(),
            focus=((0.0, "com.example.app/.MainActivity"),))
        run("await|budget", lambda p: p.await_page(budget=1.2),
            stages=((0.0, fixtures.EMPTY_PAGE),))
        return out

    return {"texts": texts(), "entries": entries(), "off": off(), "sessions": sessions(),
            "toggling": toggling(), "launch": launch(), "search": search(), "dismiss": dismiss(),
            "navigation": navigation()}


@contextmanager
def baseline_tool_dir(sha):
    """把 <sha> 解到临时 worktree，交出它的 tool/；退出时删掉 worktree 与临时目录。"""
    import fixtures
    with fixtures.baseline_worktree(sha, TESTS.parent) as tree:
        yield tree / "tool"


def collect(tool_dir):
    proc = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--dump", str(tool_dir)],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode:
        sys.exit(f"跑不通 {tool_dir}：\n{proc.stderr}")
    return json.loads(proc.stdout)


def off_guards(records):
    """每个场景断言它自己那条分支：点到哪些开关、核对几项、带外行一次不点、重试真的补点、
    补点两轮不动后回退到点行标题（ADR-0024，落点不是开关中心，按 None 认）。"""
    expected_clicks = {
        ("None", False): {"上边缘广告", "广告推荐", "下边缘广告", "限制广告跟踪"},
        ("None", True): {"限制广告跟踪"},
        ("运营任务", False): {"限制广告跟踪"},
        ("运营任务", True): {"限制广告跟踪"},
        ("广告推荐", False): {"广告推荐", "限制广告跟踪"},
        ("广告推荐", True): {"广告推荐", "限制广告跟踪"},
    }
    expected_checked = {
        ("None", False): 8, ("None", True): 2,
        ("运营任务", False): 2, ("运营任务", True): 2,
        ("广告推荐", False): 3, ("广告推荐", True): 3,
    }
    bad = 0
    for rec in records:
        size_s, safe_s, only_s = rec["id"].split("|")
        w, h = map(int, size_s.split("x"))
        _, coords = switch_page(w, h)
        by_xy = {xy: title for title, xy in coords.items()}
        title_x = (int(w * 0.05) + int(w * 0.4)) // 2      # 标题文字的列中心：回退时点的是这里
        clicked = [by_xy.get(tuple(xy)) for xy in rec["clicked"]]
        got = {c for c in clicked if c is not None}
        fallback = [tuple(xy) for xy in rec["clicked"] if tuple(xy) not in by_xy]
        key = (only_s.removeprefix("only="), safe_s == "safe=True")
        expected = expected_clicks[key]
        summary = f"核对 {expected_checked[key]} 项，调整 0 项"
        ok = (got == expected
              and rec["clicks"] > len(expected)          # 静态页回读不变，重试必须补点
              and "顶部广告" not in got and "底部广告" not in got
              and fallback and all(xy[0] == title_x for xy in fallback)   # 回退点在标题那一列
              and any(summary in line for line in rec["lines"]))
        bad += 0 if ok else 1
        print(f"守卫：{rec['id']} 点到 {sorted(got)}、标题回退 {len(fallback)} 次，"
              f"共 {rec['clicks']} 次，{'ok' if ok else 'FAIL'}")
    return bad


def session_guards(records):
    """会话样本必须真的走到两支：`miss=1` 走「快速放弃」、推广位样本真的换了前台并退回一次。
    走不到就说明样本退化了，那时「两边一样」是必然相等，不能当证据。"""
    by_id = {rec["id"]: rec for rec in records}
    quick = "快速放弃" in "".join(by_id["tap|miss=1"]["lines"])
    promo = bool(by_id["promoted|fresh"]["backs"]) and bool(by_id["promoted|fresh"]["promoted"])
    seen = by_id["promoted|seen"]["got"] is True and not by_id["promoted|seen"]["backs"]
    print(f"守卫：丢失记录走到「快速放弃」{'是' if quick else '否'}，"
          f"推广位退回 {'是' if promo else '否'}，已记过的推广位不再点 {'是' if seen else '否'}")
    return 0 if quick and promo and seen else 1


def toggling_guards(records):
    """确认框样本必须真的走两支：有一页认出确认框、有一页没有。全都认不出（或全都认出）
    说明样本退化了，那时「两边一样」是必然相等，不能当证据。"""
    by_id = {rec["id"]: rec["got"] for rec in records}
    targets = [v for k, v in by_id.items() if k.startswith("target|")]
    notes = [v for k, v in by_id.items() if k.startswith("note|")]
    found = sum(1 for v in targets if v)
    empty = sum(1 for v in targets if not v)
    print(f"守卫：认出确认框的样本 {found} 组，没认出的 {empty} 组，残留提示非空的 {sum(1 for v in notes if v)} 组")
    return 0 if found and empty else 1


def launch_guards(records):
    """启动样本必须真的走到六支：进入、空焦点顺延、进不去、被外占、落点失败、落点可恢复。
    任何一支退化（例如全都成功、或一条诊断行都没打）时「两边一样」是必然相等，不能当证据。"""
    by_id = {rec["id"]: rec for rec in records}
    entered = sum(1 for r in records if r["err"] is None)
    never = by_id["never-enters"]
    stuck = by_id["stuck-in-other"]
    landing = by_id["landing-fail"]
    lost = by_id["link-lost"]["err"] or ""
    missing = by_id["missing-package"]["err"] or ""
    notes = "".join(landing["lines"]).count("启动后没落在预期页面")
    recovered = "退出非预期页面重进后" in "".join(by_id["landing-recovered"]["lines"])
    ok = (entered == 3
          # 空焦点顺延到 8 秒硬停；确知外占按 5 秒预算先到期 —— 两条路径各自成立才算证据
          and "没有进入前台" in (never["err"] or "") and never["t"] > 7.0
          and "没有进入前台" in (stuck["err"] or "") and 5.0 <= stuck["t"] < 6.0
          and "离开前台" in (by_id["foreign-sustained"]["err"] or "")
          and "DeviceLost" in lost and "本机没有安装" in missing
          and "非预期页面" in (landing["err"] or "") and notes == 2
          and recovered)
    print(f"守卫：启动样本进入 {entered} 组，空焦点报在 {never['t']} 秒、确知外占报在 {stuck['t']} 秒，"
          f"断线与缺包各{'到位' if lost and missing else '没走到'}，"
          f"落点失败打了 {notes} 条诊断，落点恢复{'走通' if recovered else '没走到'}")
    return 0 if ok else 1


def search_guards(records):
    """设置搜索样本必须真的走完两条进场路、每种打字退化与每条失败出口，且两种屏尺寸下都成立。
    任何一支退化（例如全都成功、或一句说明都没打）时「两边一样」是必然相等，不能当证据。"""
    by = {(rec["id"].rsplit("|", 1)[0], rec["id"].rsplit("|", 1)[1]): rec for rec in records}
    said = lambda rec, word: any(word in line for line in rec["lines"])      # noqa: E731
    kinds = lambda rec: [kind for _, _, kind in rec["clicks"]]               # noqa: E731
    problems = []
    for size in SIZES:
        tag = f"{size[0]}x{size[1]}"
        get = lambda label, tag=tag: by[(label, tag)]                        # noqa: E731

        direct, fallback = get("setting|direct"), get("setting|fallback")
        if not (direct["got"] is True and any("MAIN_SEARCH" in c for c in direct["commands"])
                and not any("android.settings.SETTINGS" in c for c in direct["commands"])):
            problems.append(f"{tag} 直达搜索页没走通")
        if not (fallback["got"] is True
                and any("android.settings.SETTINGS" in c for c in fallback["commands"])
                and kinds(fallback) == ["box", "result"]):
            problems.append(f"{tag} 回设置首页那条路没走通")

        no_box, type_fail = get("setting|no-box"), get("setting|type-fail")
        no_result, not_opened = get("setting|no-result"), get("setting|not-opened")
        stuck, lost = get("setting|leave-stuck"), get("setting|link-lost")
        if not (no_box["got"] is False and said(no_box, "搜索框没打开") and not no_box["backs"]):
            problems.append(f"{tag} 搜索框没打开那条没走对")
        if not (type_fail["got"] is False and said(type_fail, "输入") and type_fail["backs"]):
            problems.append(f"{tag} 输入失败那条没走对")
        if not (no_result["got"] is False and said(no_result, "没搜到") and no_result["backs"]):
            problems.append(f"{tag} 没搜到那条没走对")
        if not (not_opened["got"] is False and said(not_opened, "没有打开") and not_opened["backs"]):
            problems.append(f"{tag} 结果没打开那条没走对")
        if not (stuck["got"] is False and said(stuck, "退不出去") and len(stuck["backs"]) == 3):
            problems.append(f"{tag} 退场失败那条没走对")
        if "DeviceLost" not in (lost.get("err") or ""):
            problems.append(f"{tag} 断线没冒泡")

        path, box_hint = get("setting|path-picks-row"), get("setting|box-hint")
        picked = [y for _, y, kind in path["clicks"] if kind == "result"]
        want_y = int(650 * size[1] // SIZES[0][1])      # 第三行（600~700）的中心才是带 path 的落点
        if not (path["got"] is True and picked == [want_y]):
            problems.append(f"{tag} 按 path 挑结果没走对")
        if not (box_hint["got"] is True and kinds(box_hint) == ["box", "result"]):
            problems.append(f"{tag} 显式搜索框文案没走对")

        typed = {label: get(f"type|{label}") for label in
                 ("set-text", "clipboard", "clear-raises", "unverified", "left-search-after-fail", "not-ready")}
        posts = lambda rec: [item[0] for item in rec["posts"]]               # noqa: E731
        if not (typed["set-text"]["got"] is True and posts(typed["set-text"]) == ["setText"]):
            problems.append(f"{tag} 打字第一级没走对")
        if not (typed["clipboard"]["got"] is True
                and posts(typed["clipboard"]) == ["setText", "clear", "paste"]):
            problems.append(f"{tag} 打字第二级没走对")
        if not (typed["clear-raises"]["got"] is True and posts(typed["clear-raises"]) ==
                ["setText", "clear", "paste"]):
            problems.append(f"{tag} 清空抛错的收容没走对")
        if typed["unverified"]["got"] is not False:
            problems.append(f"{tag} 打字返回假没走对")
        if not (typed["left-search-after-fail"]["got"] is False
                and posts(typed["left-search-after-fail"]) == ["setText"]):
            problems.append(f"{tag} 输入失败后离开搜索页那条没走对")
        if not (typed["not-ready"]["got"] is False and not typed["not-ready"]["posts"]):
            problems.append(f"{tag} 不在搜索页那条没走对")
    print("守卫：设置搜索样本 " + ("两种屏尺寸下全部到位" if not problems else "；".join(problems)))
    return 0 if not problems else 1


def dismiss_guards(records):
    """弹窗样本必须真的走完四条退化链与四道守卫：每一支的返回值、点击次数与返回次数逐一核对，
    推广位样本还要真的换了前台、退回原 App 并记下那一处。任何一支退化（全都关不掉、或全都关掉）
    时「两边一样」是必然相等，不能当证据。"""
    by = {rec["id"]: rec for rec in records}
    problems = []
    for size in SIZES:
        tag = f"{size[0]}x{size[1]}"

        def check(label, got, clicks=0, backs=0, promoted=None, tag=tag):
            rec = by.get(f"{label}|{tag}")
            if rec is None:
                problems.append(f"{tag} 缺样本 {label}")
                return
            if (rec["got"] != got or len(rec["clicks"]) != clicks
                    or len(rec["backs"]) != backs
                    or (promoted is not None and rec["promoted"] != promoted)):
                problems.append(f"{tag} {label} 走成了 {rec['got']!r}／点击 {len(rec['clicks'])}"
                                f"／返回 {len(rec['backs'])}／推广位 {rec['promoted']}")

        check("permission|deny", "拒绝权限", clicks=1)
        check("permission|allow-only", None)
        check("close|icon", "✕", clicks=1)
        check("close|back-label", None)          # 返回键不是弹窗 ✕（沿用 #753）
        check("close|in-list", None)             # 列表里卡片的 ✕ 点了会打开别的页面
        check("close|switch-row", None)          # 含「关闭」的说明行是开关（沿用 #378）
        check("close|too-wide", None)            # 整行/整块尺寸的候选不点
        check("update|title", "取消", clicks=1)   # 标题在滚动容器里也先按标题认（沿用 #286）
        check("refuse|word", "不同意", clicks=1)
        check("guard|many-texts", None)          # 文字多得像正常页面
        check("guard|page-with-switch", None)    # 带开关的页面不当弹窗
        check("promoted|fallback", None, clicks=1, backs=1,
              promoted=[["com.promo", "关闭 com.promo:id/iv_close"]])
        hit = {rec["got"] for rec in records if rec["id"].endswith(f"|{tag}")}
        if not ({"✕", "取消", "不同意", "拒绝权限"} <= hit):
            problems.append(f"{tag} 四种关掉弹窗的结局没都走到：{sorted(str(x) for x in hit)}")
    print("守卫：弹窗样本 " + ("两种屏尺寸下四条退化链与四道守卫全部到位"
                             if not problems else "；".join(problems)))
    return 0 if not problems else 1


def navigation_guards(records):
    """导航样本必须真的走到每一条分支：命中与失手、底栏带内外、换页成与没换、回顶滑与不滑。
    任何一支退化（全都成功或全都失败）时「两边一样」是必然相等，不能当证据。"""
    by = {rec["id"]: rec for rec in records}
    problems = []
    for size in SIZES:
        tag = f"{size[0]}x{size[1]}"

        def get(label, tag=tag):
            rec = by.get(f"{label}|{tag}")
            if rec is None:
                problems.append(f"{tag} 缺样本 {label}")
            return rec or {}

        said = lambda rec, word: any(word in line for line in rec.get("lines", []))  # noqa: E731
        band_y = size[1] * 0.85

        for label in ("tab|hit", "tab|content-same-name", "tab|late"):
            rec = get(label)
            if not (rec.get("got") is True and len(rec.get("clicks", [])) == 1
                    and rec["clicks"][0][1] > band_y):
                problems.append(f"{tag} {label} 没点到底栏带内那一行：{rec.get('clicks')}")
        missing = get("tab|missing")
        if missing.get("got") is not False or missing.get("clicks"):
            problems.append(f"{tag} 底栏没有时的收尾走成了 {missing.get('got')!r}／点击 {missing.get('clicks')}")
        below, inside = get("tab|below-band"), get("tab|inside-band")
        if below.get("got") is not False or below.get("clicks"):
            problems.append(f"{tag} 85% 带下沿外那一行被点或没判假：{below.get('got')!r}／{below.get('clicks')}")
        if inside.get("got") is not True or len(inside.get("clicks", [])) != 1:
            problems.append(f"{tag} 85% 带内那一行没点：{inside.get('got')!r}／{inside.get('clicks')}")

        if not (get("tap|found").get("got") is True and len(get("tap|found").get("clicks", [])) == 1):
            problems.append(f"{tag} 按文字点没命中")
        late, timeout = get("tap|bottom-bar-late"), get("tap|bottom-bar-timeout")
        if late.get("got") is not True or late.get("t", 0) < 4.4:
            problems.append(f"{tag} 底栏等晚到弹窗那一支没走对：{late.get('got')!r}，{late.get('t')} 秒")
        if timeout.get("got") is not False or timeout.get("t", 0) < 6.0:
            problems.append(f"{tag} 底栏 6 秒超时那一支没走对：{timeout.get('got')!r}，{timeout.get('t')} 秒")
        miss, after, gave_up = get("tap|missing"), get("tap|after-miss"), get("tap|miss-then-give-up")
        if not (miss.get("got") is False and miss.get("miss") == 1 and said(miss, "没找到")):
            problems.append(f"{tag} 找不到时没记丢失：{miss.get('got')!r}／miss={miss.get('miss')}")
        if not (after.get("got") is True and after.get("miss") == 0 and not after.get("lines")):
            problems.append(f"{tag} 走丢之后找回那一支没走对：{after.get('got')!r}／miss={after.get('miss')}")
        if not (gave_up.get("got") is False and gave_up.get("miss") == 2
                and said(gave_up, "快速放弃")):
            problems.append(f"{tag} 走丢之后只看这一屏那一支没走对：{gave_up.get('miss')}／{gave_up.get('lines')}")

        if get("entry|found").get("got") is not True:
            problems.append(f"{tag} 可选入口命中那一支没走对")
        gone = get("entry|missing")
        if not (gone.get("got") is False and said(gone, "没找到")):
            problems.append(f"{tag} 可选入口失手时没留现场")

        if get("enter|lands").get("err") is not None:
            problems.append(f"{tag} 换页确认那一条走成了 {get('enter|lands').get('err')}")
        if "页面没有变化" not in (get("enter|no-change").get("err") or ""):
            problems.append(f"{tag} 页面没换时不抛：{get('enter|no-change').get('err')}")
        if "未找到入口" not in (get("enter|missing").get("err") or ""):
            problems.append(f"{tag} 入口没找到时不抛：{get('enter|missing').get('err')}")

        if get("go|lands").get("got") is not True or get("go|misses").get("got") is not False:
            problems.append(f"{tag} 前往的成功 / 失手两支没走对")

        first, none = get("tap_icon|first"), get("tap_icon|none")
        if first.get("got") is not True or len(first.get("clicks", [])) != 1:
            problems.append(f"{tag} 图标入口命中那一支没走对")
        if none.get("got") is not False or len(none.get("clicks", [])) != 2:
            problems.append(f"{tag} 图标入口失手那一支没走对：{none.get('got')!r}／{none.get('clicks')}")

        edge = get("tap|edge-fallback")
        if not (edge.get("got") is True and len(edge.get("clicks", [])) == 1
                and edge["clicks"][0][1] < size[1] * 0.94):
            problems.append(f"{tag} 翻到底的兜底落点没走对：{edge.get('got')!r}／{edge.get('clicks')}")
        for label in ("tap|link-lost", "entry|link-lost"):
            if not (get(label).get("err") or "").startswith("DeviceLost"):
                problems.append(f"{tag} {label} 断线没冒泡：{get(label).get('err')}")
        if "回到页顶时离开了当前设置页" not in (get("top|leaves-page").get("err") or ""):
            problems.append(f"{tag} 回顶时换了页却不报错：{get('top|leaves-page').get('err')}")

        up, flat = get("top|stops-at-top"), get("top|no-scrollable")
        if up.get("scrolls") != 1:
            problems.append(f"{tag} 回顶没滑到页顶就停：滑了 {up.get('scrolls')} 次")
        if flat.get("scrolls") != 0:
            problems.append(f"{tag} 单屏面板上回顶不该滑：滑了 {flat.get('scrolls')} 次")

        if get("page|in-settings").get("got") is not True:
            problems.append(f"{tag} 设置页没认出来")
        if get("page|not-settings").get("got") is not False:
            problems.append(f"{tag} 普通页被认成设置页")

        await_ = get("await|budget")
        if not (await_.get("got") is None and 1.1 <= await_.get("t", 0) <= 1.6):
            problems.append(f"{tag} 等页预算没走满：{await_.get('got')!r}，{await_.get('t')} 秒")
    print("守卫：导航样本 " + ("两种屏尺寸下命中、失手、换页校验与回顶全部到位"
                             if not problems else "；".join(problems)))
    return 0 if not problems else 1


def compare(baseline_tool):
    before, after = collect(str(baseline_tool)), collect(str(TESTS.parent / "tool"))
    bad = 0
    for key in before:
        bm, am = {x["id"]: x for x in before[key]}, {x["id"]: x for x in after[key]}
        diff = [i for i in bm if bm[i] != am.get(i)]
        bad += len(diff)
        print(f"{key}: {len(bm)} 组，一致 {len(bm) - len(diff)}，不一致 {len(diff)}")
        for i in diff[:5]:
            print(f"  {i}\n    改前 {json.dumps(bm[i], ensure_ascii=False)}\n    改后 {json.dumps(am.get(i), ensure_ascii=False)}")
    # 守卫：对拍必须真的走到目标分支，否则「两边一样」是必然的
    t = {x["id"]: x["got"] for x in after["texts"]}
    flipped = sum(1 for k in t if k.endswith("|True") and t[k] != t[k[:-5] + "|False"])
    e = {x["id"]: x["got"] for x in after["entries"]}
    filtered = sum(1 for k, v in e.items() if k.rsplit("|", 1)[1] == "com.android.settings"
                   and v != e[k.rsplit("|", 1)[0] + "|"])
    print(f"守卫：读屏策略改变输出的组数 {flipped}，包名过滤改变输出的页数 {filtered}")
    bad += off_guards(after["off"])
    bad += session_guards(after["sessions"])
    bad += toggling_guards(after["toggling"])
    bad += launch_guards(after["launch"])
    bad += search_guards(after["search"])
    bad += dismiss_guards(after["dismiss"])
    bad += navigation_guards(after["navigation"])
    return 1 if bad else 0


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--dump":
        print(json.dumps(dump(sys.argv[2]), ensure_ascii=False, sort_keys=True))
        return
    if len(sys.argv) == 3 and sys.argv[1] == "--baseline":
        with baseline_tool_dir(sys.argv[2]) as tool_dir:
            bad = compare(tool_dir)
        sys.exit(bad)
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.exit(compare(sys.argv[1]))


if __name__ == "__main__":
    main()
