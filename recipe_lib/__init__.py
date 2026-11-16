"""机型库：库实现名字的唯一 owner（ADR-0040）。

一个家族一个文件（`huawei` / `samsung` 目前没有实现，就不建文件）；文件内分「词汇 / 策略」两节。
归属按家族数算：只被一个家族用到的进 `recipe_lib/<家族>.py`，被 ≥2 个家族用到的进 `shared.py`。

名字集合是显式三层：六个模块的 `__all__` 并集是「数据 `lib:` 能点名」的词汇，`LIBRARY` 就是它；
`__all__` 再加 `HELPERS` 里的面助手，才轮到「能从稳定 import 面取到」的名字。三层各有多少个以
实算为准（`tests/test_recipe_nav.py::SurfaceTests`），别在文档里抄死数。
`tool/recipe_nav.py` / `recipe_strategies.py` / `recipe_steps.py` 只剩转发，真身都在这里。
"""

from . import shared
from . import xiaomi
from . import oppo
from . import vivo
from . import honor
from . import meizu

from .shared import (
    app_settings as app_settings, browser_settings as browser_settings, close_named as close_named,
    direct_page as direct_page, direct_start as direct_start, enter as enter, gear as gear,
    gear_top as gear_top, goto as goto,
    my_tab as my_tab,
    open_page as open_page, open_settings as open_settings, opened as opened,
    page_activity as page_activity, read_switches as read_switches,
    switch_signature as switch_signature, switch_top as switch_top, tap as tap,
    tap_text as tap_text, wait_page as wait_page, wait_switches as wait_switches, maybe as maybe,
    close_named_step as close_named_step,
)
from .xiaomi import (
    bottom_tab as bottom_tab, browser_settings_xiaomi as browser_settings_xiaomi,
    browser_start as browser_start, by_id as by_id, close_with_plain_tap as close_with_plain_tap,
    direct_settings as direct_settings, downloads as downloads, downloads_probe as downloads_probe,
    downloads_tap as downloads_tap, gear_tap as gear_tap, global_search as global_search,
    menu_settings as menu_settings, mine_settings as mine_settings,
    mine_tab_low as mine_tab_low, negative_screen as negative_screen, popup_row as popup_row,
    security_center as security_center, security_tab as security_tab,
    settings_icon_visible as settings_icon_visible, store as store,
    store_mode as store_mode, store_mode_step as store_mode_step,
    store_privacy_nested as store_privacy_nested, store_privacy_sub as store_privacy_sub,
    system_ads_menu as system_ads_menu, system_ads_security as system_ads_security, tab as tab,
    tab_bot as tab_bot, tap_any as tap_any, tap_bottom_tab as tap_bottom_tab, tap_low as tap_low,
    tap_tab as tap_tab, theme as theme, theme_settings as theme_settings,
    wait_bottom_tab as wait_bottom_tab, weather_calendar_probe as weather_calendar_probe,
    weather_calendar_tap as weather_calendar_tap,
)
from .oppo import (
    ad_id_page as ad_id_page, ad_tracking_close_all as ad_tracking_close_all,
    ad_tracking_close_paged as ad_tracking_close_paged, assistant_advice_rows as assistant_advice_rows,
    assistant_advice_search as assistant_advice_search, assistant_icon as assistant_icon,
    assistant_screen as assistant_screen, assistant_settings as assistant_settings,
    assistant_swipe_in as assistant_swipe_in, at_assistant as at_assistant, browser_ads as browser_ads,
    browser_home as browser_home,
    browser_personalized as browser_personalized,
    browser_settings_direct as browser_settings_direct, carousel_choices as carousel_choices,
    close_all as close_all, close_all_listed as close_all_listed, close_group as close_group,
    close_named_expect as close_named_expect, close_named_optional as close_named_optional,
    close_named_plain as close_named_plain, close_rows as close_rows, close_titles as close_titles,
    enter_privacy as enter_privacy, enter_settings as enter_settings,
    game_center_direct as game_center_direct, game_center_taps as game_center_taps,
    game_settings_direct as game_settings_direct, game_settings_entry as game_settings_entry,
    game_settings_via_mine as game_settings_via_mine, has_row as has_row,
    hide_carousel as hide_carousel, menu_state as menu_state, more_menu as more_menu,
    navigate as navigate, off_exact as off_exact, off_exact_paged as off_exact_paged,
    off_exact_paged_optional as off_exact_paged_optional, open_app_settings as open_app_settings,
    open_search_setting as open_search_setting, open_search_settings as open_search_settings,
    open_search_sub as open_search_sub, open_switch_page as open_switch_page,
    read_on_page as read_on_page, row as row, search_settings as search_settings,
    search_settings_direct as search_settings_direct,
    search_settings_ready as search_settings_ready, search_settings_swipe as search_settings_swipe,
    settings_page as settings_page, store_privacy as store_privacy,
    store_promotions as store_promotions, system_settings as system_settings,
    tap_by_scroll as tap_by_scroll, tap_page as tap_page,
    theme_shop_settings as theme_shop_settings, theme_store_settings as theme_store_settings,
    video_direct as video_direct, wait_search_settings as wait_search_settings,
    MenuState as MenuState, off_exact_step as off_exact_step,
    require_installed as require_installed, _labelled as _labelled,
)
from .vivo import (
    browser_recommendations as browser_recommendations,
    browser_settings_vivo as browser_settings_vivo, by_desc as by_desc,
    close_named_vivo as close_named_vivo, confirm2 as confirm2, dialog_open as dialog_open,
    global_search_ads as global_search_ads, global_search_entry as global_search_entry,
    hiboard_panel_v2547a as hiboard_panel_v2547a,
    hiboard_panel as hiboard_panel, i_manager_ads as i_manager_ads,
    lock_screen_magazine as lock_screen_magazine, off as off, off_one as off_one,
    off_unnamed as off_unnamed, result_xy as result_xy, row_switch as row_switch, rows as rows,
    search_setting as search_setting, setting_search as setting_search,
    settings_home as settings_home, store_personalization as store_personalization,
    store_settings_direct as store_settings_direct,
    switch_off as switch_off, system_ads_branch as system_ads_branch,
    system_ads_chain as system_ads_chain, tap_row as tap_row, weather_service as weather_service,
    title_key as title_key, verify as verify,
)
from .honor import (
    baidu_browser as baidu_browser, browser_gear as browser_gear,
    close_named_honor as close_named_honor, launch as launch,
    no_agreement as no_agreement, scan_switches as scan_switches, labels as labels,
    search_more as search_more, settle_page as settle_page, wait_home as wait_home,
)
from .meizu import (
    assert_no_other_window as assert_no_other_window, safe_switches as safe_switches,
)

MODULES = (shared, xiaomi, oppo, vivo, honor, meizu)

# 数据可点名的名字：家族 `__all__` 的并集，派生不手抄。
LIBRARY = {name: getattr(module, name) for module in MODULES for name in module.__all__}

# 稳定 import 面能取到、但数据 `lib:` 不许点名的面助手：判据是「只读前台 / 页面树给段体用」
# （不自己走读屏与等待）。`settle_page` 自己走读屏与等待，与 `wait_page` 同档，已在家族词汇里（#1371）。
HELPERS = (
    "maybe", "labels", "MenuState", "close_named_step", "off_exact_step",
    "require_installed", "title_key", "verify", "_labelled",
)

# 字面量：mypy 要靠它解析 `from recipe_nav import <名字>`，算出来的并集不算（ADR-0040）。
__all__ = (
    "MenuState", "_labelled", "ad_id_page", "ad_tracking_close_all", "ad_tracking_close_paged",
    "app_settings", "assert_no_other_window", "assistant_advice_rows", "assistant_advice_search", "assistant_icon",
    "assistant_screen", "assistant_settings", "assistant_swipe_in", "at_assistant", "baidu_browser",
    "bottom_tab",
    "browser_ads", "browser_gear", "browser_home", "browser_personalized", "browser_recommendations",
    "browser_settings", "browser_settings_direct", "browser_settings_vivo",
    "browser_settings_xiaomi", "browser_start", "by_desc", "by_id", "carousel_choices", "close_all",
    "close_all_listed", "close_group", "close_named", "close_named_expect", "close_named_honor",
    "close_named_optional", "close_named_plain", "close_named_step", "close_named_vivo",
    "close_rows", "close_titles", "close_with_plain_tap", "confirm2", "dialog_open",
    "direct_page", "direct_settings", "direct_start", "downloads", "downloads_probe",
    "downloads_tap", "enter",
    "enter_privacy",
    "enter_settings", "game_center_direct", "game_center_taps", "game_settings_direct",
    "game_settings_entry", "game_settings_via_mine", "gear", "gear_tap", "gear_top",
    "global_search", "global_search_ads", "global_search_entry", "goto", "has_row", "hiboard_panel",
    "hiboard_panel_v2547a", "hide_carousel", "i_manager_ads", "labels", "launch", "lock_screen_magazine",
    "maybe", "menu_settings", "menu_state", "mine_settings", "mine_tab_low", "more_menu", "my_tab",
    "navigate",
    "negative_screen", "no_agreement", "off", "off_exact", "off_exact_paged",
    "off_exact_paged_optional", "off_exact_step", "off_one", "off_unnamed", "open_app_settings",
    "open_page", "open_search_setting", "open_search_settings", "open_search_sub", "open_settings",
    "open_switch_page", "opened", "page_activity", "popup_row", "read_on_page", "read_switches",
    "require_installed", "result_xy", "row", "row_switch", "rows", "safe_switches", "scan_switches",
    "search_more", "search_setting", "search_settings", "search_settings_direct", "search_settings_ready",
    "search_settings_swipe", "security_center", "security_tab", "setting_search", "settings_home",
    "settings_icon_visible", "settings_page", "settle_page", "store", "store_mode", "store_mode_step",
    "store_personalization", "store_privacy", "store_privacy_nested", "store_privacy_sub",
    "store_promotions", "store_settings_direct", "switch_off", "switch_signature",
    "switch_top", "system_ads_branch", "system_ads_chain", "system_ads_menu", "system_ads_security",
    "system_settings",
    "tab", "tab_bot", "tap", "tap_any", "tap_bottom_tab", "tap_by_scroll", "tap_low", "tap_page",
    "tap_row", "tap_tab", "tap_text", "theme", "theme_settings", "theme_shop_settings",
    "theme_store_settings", "title_key", "verify", "video_direct", "wait_bottom_tab", "wait_home",
    "wait_page",
    "wait_search_settings", "wait_switches", "weather_calendar_probe", "weather_calendar_tap",
    "weather_service",
)
