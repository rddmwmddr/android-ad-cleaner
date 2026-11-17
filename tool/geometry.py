"""判定用的屏幕几何比例的唯一 owner。

「这一行在不在屏带内」「这个控件算不算图标命中」「是不是底部标签」「是不是对话框按钮」
「哪些行可拨」这些判定用的比例只在这里定义（#1431）：同一个顶部带曾在认行、渠道引擎与诊断里
各写一份，屏幕带比例要变时满仓找不到同一个数。调用方从这取，别在自己模块里写字面量；
`tests/test_rules_guards.py` 的 `GeometryGuards` 守着「比例字面量只许出现在这个文件」。

纯数据模块：不读屏、不点击、不 import 引擎里的别处。数值与它原本控制的判定逐条对应在
各常量的注释里（#1431 之前各住一份，这里是搬移后的唯一家）。
"""

# 页面顶部这一段里的同名文字是页眉 / 顶栏标题，不是列表里的候选行（`row.named_nodes`）；
# 渠道引擎认「标题还在页面顶部」也用它。
TOP_BAND = 0.22

# `row.title_label()`：容器高度不超过屏高的这个比例就算「矮容器（就是一行）」，标题取最上面那段。
SHORT_CONTAINER_MAX = 0.18

# `chan_fast.ChannelPage._recognise()`：三星 One UI 把渠道名放进页眉控件（`HEADER_IDS`），
# 位置低于 TOP_BAND 时只认这几个页眉 id；这条放宽带的上界。
HEADER_BAND = 0.4

# `chan_fast.top_title()` 的兜底（Funtouch 13 顶栏没有 resource-id）：顶部这个比例以内、
# 宽度超过屏宽这个比例的整段文字才算顶栏标题；半屏宽的多半是行内标签。
TOP_TITLE_BAND = 0.15
TOP_TITLE_WIDTH = 0.8

# `chan_fast.ChannelPage._recognise_inline()`：应用通知页里渠道行自带开关时，行高不超过屏高的这个比例。
INLINE_ROW_MAX = 0.2

# `Screen.confirm_target()` 的兜底档：可点击的 TextView 要窄于屏宽这个比例、矮于屏高这个比例，
# 才排除掉整行与 ColorOS 开关旁的状态文字。
CONFIRM_BUTTON_MAX_W = 0.5
CONFIRM_BUTTON_MAX_H = 0.12

# `Screen.find()`：行中心低于屏高这个比例就算进了底部带，不点；已到页底翻不上来时
# 按第二个比例放进来的行才点它的上沿。
FIND_VISIBLE_BOTTOM = 0.92
FIND_EDGE_BOTTOM = 0.975

# `Screen.scroll()`：从 0.80H 起往上拖，最多拖 0.58H（落在 0.22H 以上），避开标题栏和底栏。
# `frac` 的默认值同样是比例；调用签名里的参数名与顺序不变。
SCROLL_BOTTOM = 0.80
SCROLL_MAX_FRAC = 0.58
SCROLL_FRAC = 0.45

# `Screen.icon_candidates()` 的默认取样区（右上角），与「整块卡片 / 列表项」的尺寸上界：
# 更大的可点节点点进去是别的页面，不是图标命中。
ICON_AREA = (0.72, 0.0, 1.0, 0.16)
ICON_MAX_W = 0.25
ICON_MAX_H = 0.10

# `Dismisser.dismiss()`：弹窗 ✕ 图标的尺寸上界；更大的多半是页面卡片或整行，点了会进别的页面。
DISMISS_ICON_MAX_W = 0.3
DISMISS_ICON_MAX_H = 0.12

# `Navigator._tab_xy()`：底部标签带的上界（节点上沿超过屏高的这个比例才算标签）。
TAB_BAND = 0.85

# `toggler.in_band()`：可拨的行落在屏高的这一段里，避开顶部标题栏与底部栏。
TAPPABLE_BAND = (0.08, 0.985)
