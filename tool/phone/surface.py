"""脚本可以碰的门面名字（rule:dev.phone.script-surface、#1477）。

`Phone` 的公开面比脚本该看到的宽：`ls` / `close` / `wait_unlocked` / `check_alive` /
`icon_candidates` 这些是引擎自己的操作，`home` / `app_stop` 是引擎阶段的动作。脚本面是其中
**声明过的那一份**，不是「门面上有什么就能用什么」——新增一个公开名字时先回答「它是不是这台
手机这个概念的一部分、脚本该不该碰它」，再决定加不加进来。

单一来源：守卫（`devtools/script_surface.py`，由 `tests/test_phone_facade.py` 的
`ScriptSurfaceTests` 代跑）读的就是这里，别在别处再抄一份名单。

`app` 是 `recipe_lib/honor.py` 的 `launch()` 在写（它自己做裸 `am start`、不走 `Phone.start`）：
「这台手机现在拉起的是哪个 App」是设备概念，留在脚本面。`promoted` 不在这里——换 App 时清空
推广位记忆已经收进 `LaunchSession.set_app()`，脚本不必再碰那个集合（#1479）。
"""

# 设备概念属性：都是「这台手机现在是什么样」的读数，脚本直接读、少数直接写。
DEVICE_PROPERTIES = frozenset({
    "W", "H",                 # 屏幕宽高：脚本按比例算坐标
    "changed",                # 本次关掉的 (页面, 标题)
    "safe_mode",              # 只关点名的开关，不做整页全关
    "miss", "missed",         # 本段没找到几次 / 本次没拨到的开关
    "lost",                   # 本轮是否已确认断线
    "app",                    # 最近拉起的 App
})

# 门面动词与查询：动作原语（`shell` / `swipe` / `press` / `tap_id` …）、页面查询、整页拨动。
DEVICE_VERBS = frozenset({
    # 动作原语
    "click", "back", "scroll", "swipe", "shell", "press", "window_size",
    "tap_id", "tap_id_if_present", "set_text",
    # 页面查询与等待
    "texts", "tree", "focus", "sig", "on_screen", "switches", "has_text",
    # 绕过段内包装器的引擎读法：自绘开关只有「仅阅读」那一档允许读，`honor.close_named_honor(drawn=True)` 用
    "switches_raw",
    "find", "settle", "await_page", "expect_page", "locked", "in_settings_page",
    "page_text", "page_evidence", "note_miss", "scroll_more", "say",
    # 导航、拨动与设置搜索
    "tap", "tap_icon", "entry", "enter", "go", "tab", "top", "off", "setting",
    # 弹窗与启动
    "dismiss", "confirm", "start",
})

SCRIPT_SURFACE = DEVICE_PROPERTIES | DEVICE_VERBS
