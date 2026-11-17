"""catalog 族的用例表（沿用 #1398 的族承载，结构反推补齐 #1399）：装载期拒绝非法形状，一行一条。

每行是 `data`（`catalog.validate` 必须拒绝的一份数据）加 `needle`（报错里必须出现的子串）。
这些行原先一条一个 `def`，owner 是票号；现在 owner 是它们依赖的结构项，结构项退场，行跟着退场。

句柄（`handles`）全部从行自己的 `data` 现算，不写字符串字面量句柄——手写句柄等于给 `OPS`
造第二个 owner。四类：哪个 kind、哪个必填键缺了、顶层字段、段字段。

拒绝「结构里根本没有的东西」的行（`kind = "explode"`、顶层 `surprise`）句柄为空：它们测的就是
那个名字不在结构里，给任何句柄都会说成「这条行依赖某个结构项」，与它要断言的事相反。

`expected`（#1399）从 `OPS` 反推缺键句柄 `("required", kind, key)`：每个 op 的每个必填键都要有
一条「缺这个键」的 case，否则 `gap_violations()` 点名缺哪条。`OPS` 里加一个必填键，这里立刻要求
配套 case；删一条缺键行，句柄检查与 gap 检查一起红。这些缺键 path 此前只覆盖 63 个必填键里的 6 个。

`produce` 跑一次校验器并留下报错原文；不再被拒时留下 `<accepted>`，这样「丢掉一条拒绝」也会在
快照 diff 里显形。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tool"))
import catalog  # noqa: E402
from catalog.schema import OPS, SEGMENT_KEYS, TOP_KEYS  # noqa: E402

from family import Family, cli  # noqa: E402

CASES = [
    {
        "id": "unknown-top-key",
        "data": {"segment": [{"name": "a", "ops": []}], "surprise": 1},
        "needle": "名单外的键",
    },
    {
        "id": "unknown-op-kind",
        "data": {"segment": [{"name": "a", "ops": [{"kind": "explode"}]}]},
        "needle": "不在白名单",
    },
    {
        "id": "off-without-naming",
        "data": {"segment": [{"name": "a", "ops": [{"kind": "off", "page": "p"}]}]},
        "needle": "没点名",
    },
    {
        "id": "off-only-keep-overlap",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "off", "only": ["x", "y"], "keep": ["y"], "page": "p"},
        ]}]},
        "needle": "重叠",
    },
    {
        "id": "duplicate-segment-names",
        "data": {"segment": [{"name": "a", "ops": []}, {"name": "a", "ops": []}]},
        "needle": "段名重复",
    },
    {
        "id": "focus-match-unknown",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "if_focus", "text": "p", "match": "fnmatch"},
        ]}]},
        "needle": "match='fnmatch' 认不出",
    },
    {
        "id": "return-value-not-boolean",
        "data": {"segment": [{"name": "a", "ops": [{"kind": "return", "value": "false"}]}]},
        "needle": "只能是 true / false",
    },
    {
        "id": "page-missing-args",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "page", "kwargs": {"activity": "X"}},
        ]}]},
        "needle": "缺 args",
    },
    {
        "id": "page-extra-key",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "page", "args": ["X"], "surprise": 1},
        ]}]},
        "needle": "名单外的键",
    },
    {
        "id": "skip-missing-text",
        "data": {"segment": [{"name": "a", "ops": [{"kind": "skip"}]}]},
        "needle": "缺 text",
    },
    {
        "id": "print-missing-text",
        "data": {"segment": [{"name": "a", "ops": [{"kind": "print"}]}]},
        "needle": "缺 text",
    },
    {
        "id": "skip-extra-key",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "skip", "text": "x", "surprise": 1},
        ]}]},
        "needle": "名单外的键",
    },
    {
        "id": "fail-missing-text",
        "data": {"segment": [{"name": "a", "ops": [{"kind": "fail"}]}]},
        "needle": "缺 text",
    },
    {
        "id": "fail-extra-key",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "fail", "text": "x", "surprise": 1},
        ]}]},
        "needle": "名单外的键",
    },
    {
        "id": "require-tap-missing-miss-print",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "require_tap", "text": "设置"},
        ]}]},
        "needle": "缺 miss_print",
    },
    {
        "id": "require-tap-extra-key",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "require_tap", "text": "x", "miss_print": "y", "surprise": 1},
        ]}]},
        "needle": "名单外的键",
    },
    {
        "id": "close-listed-missing-names",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "close_listed", "page": "p", "miss_print": "y"},
        ]}]},
        "needle": "缺 names",
    },
    {
        "id": "close-listed-extra-key",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "close_listed", "names": ["a"], "page": "p", "miss_print": "y",
             "surprise": 1},
        ]}]},
        "needle": "名单外的键",
    },
    {
        "id": "tap-id-without-selector",
        "data": {"segment": [{"name": "a", "ops": [{"kind": "tap_id"}]}]},
        "needle": "resource_id 或 text",
    },
    {
        "id": "tap-id-extra-key",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "tap_id", "text": "x", "surprise": 1},
        ]}]},
        "needle": "名单外的键",
    },
    {
        "id": "gesture-missing-ms",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "gesture", "start": [0.5, 0.3], "end": [0.5, 0.7]},
        ]}]},
        "needle": "缺 ms",
    },
    {
        "id": "gesture-point-out-of-range",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "gesture", "start": [0.5, 1.2], "end": [0.5, 0.7], "ms": 300},
        ]}]},
        "needle": "0–1 的比例",
    },
    {
        "id": "gesture-ms-not-positive",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "gesture", "start": [0.5, 0.3], "end": [0.5, 0.7], "ms": 0},
        ]}]},
        "needle": "正的整数毫秒",
    },
    {
        "id": "gesture-extra-key",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "gesture", "start": [0.5, 0.3], "end": [0.5, 0.7], "ms": 300,
             "surprise": 1},
        ]}]},
        "needle": "名单外的键",
    },
    # 缺键 path（#1399）：每个 op 的每个必填键各一条，结构反推由 `expected()` 管。
    # 其中 if-setting 缺 kw、let 缺 lib / name、off-required 缺 only、skip-unless-installed 缺
    # contains、start-or-skip 缺 dead_ends 六条是从 `NewOpValidatorTests` 逐字搬来的。
    {
        "id": "app-stop-missing-pkg",
        "data": {"segment": [{"name": "a", "ops": [{"kind": "app_stop"}]}]},
        "needle": "缺 pkg",
    },
    {
        "id": "close-all-missing-page",
        "data": {"segment": [{"name": "a", "ops": [{"kind": "close_all"}]}]},
        "needle": "缺 page",
    },
    {
        "id": "close-listed-missing-miss-print",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "close_listed", "names": ["a"], "page": "p"},
        ]}]},
        "needle": "缺 miss_print",
    },
    {
        "id": "close-listed-missing-page",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "close_listed", "names": ["a"], "miss_print": "m"},
        ]}]},
        "needle": "缺 page",
    },
    {
        "id": "code-missing-name",
        "data": {"segment": [{"name": "a", "ops": [{"kind": "code"}]}]},
        "needle": "缺 name",
    },
    {
        "id": "enter-missing-text",
        "data": {"segment": [{"name": "a", "ops": [{"kind": "enter"}]}]},
        "needle": "缺 text",
    },
    {
        "id": "entry-missing-text",
        "data": {"segment": [{"name": "a", "ops": [{"kind": "entry"}]}]},
        "needle": "缺 text",
    },
    {
        "id": "gesture-missing-end",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "gesture", "start": [0.5, 0.3], "ms": 300},
        ]}]},
        "needle": "缺 end",
    },
    {
        "id": "gesture-missing-start",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "gesture", "end": [0.5, 0.7], "ms": 300},
        ]}]},
        "needle": "缺 start",
    },
    {
        "id": "go-missing-expect",
        "data": {"segment": [{"name": "a", "ops": [{"kind": "go", "text": "x"}]}]},
        "needle": "缺 expect",
    },
    {
        "id": "go-missing-text",
        "data": {"segment": [{"name": "a", "ops": [{"kind": "go", "expect": "y"}]}]},
        "needle": "缺 text",
    },
    {
        "id": "if-entry-missing-text",
        "data": {"segment": [{"name": "a", "ops": [{"kind": "if_entry"}]}]},
        "needle": "缺 text",
    },
    {
        "id": "if-find-missing-text",
        "data": {"segment": [{"name": "a", "ops": [{"kind": "if_find"}]}]},
        "needle": "缺 text",
    },
    {
        "id": "if-focus-missing-text",
        "data": {"segment": [{"name": "a", "ops": [{"kind": "if_focus"}]}]},
        "needle": "缺 text",
    },
    {
        "id": "if-lib-missing-name",
        "data": {"segment": [{"name": "a", "ops": [{"kind": "if_lib"}]}]},
        "needle": "缺 name",
    },
    {
        "id": "if-setting-missing-kw",
        "data": {"segment": [{"name": "a", "ops": [{"kind": "if_setting", "ops": []}]}]},
        "needle": "缺 kw",
    },
    {
        "id": "if-tap-missing-text",
        "data": {"segment": [{"name": "a", "ops": [{"kind": "if_tap"}]}]},
        "needle": "缺 text",
    },
    {
        "id": "if-var-missing-name",
        "data": {"segment": [{"name": "a", "ops": [{"kind": "if_var"}]}]},
        "needle": "缺 name",
    },
    {
        "id": "let-missing-lib",
        "data": {"segment": [{"name": "a", "ops": [{"kind": "let", "name": "pkg"}]}]},
        "needle": "缺 lib",
    },
    {
        "id": "let-missing-name",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "let", "lib": "browser_settings"},
        ]}]},
        "needle": "缺 name",
    },
    {
        "id": "lib-missing-name",
        "data": {"segment": [{"name": "a", "ops": [{"kind": "lib"}]}]},
        "needle": "缺 name",
    },
    {
        "id": "note-miss-missing-text",
        "data": {"segment": [{"name": "a", "ops": [{"kind": "note_miss"}]}]},
        "needle": "缺 text",
    },
    {
        "id": "off-missing-page",
        "data": {"segment": [{"name": "a", "ops": [{"kind": "off"}]}]},
        "needle": "第 1 个 op 缺 page",
    },
    {
        "id": "off-required-missing-only",
        "data": {"segment": [{"name": "a", "ops": [{"kind": "off_required", "page": "p"}]}]},
        "needle": "第 1 个 op 缺 only",
    },
    {
        "id": "off-required-missing-page",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "off_required", "only": ["x"]},
        ]}]},
        "needle": "第 1 个 op 缺 page",
    },
    {
        "id": "press-missing-key",
        "data": {"segment": [{"name": "a", "ops": [{"kind": "press"}]}]},
        "needle": "缺 key",
    },
    {
        "id": "require-entry-missing-miss-print",
        "data": {"segment": [{"name": "a", "ops": [{"kind": "require_entry", "text": "x"}]}]},
        "needle": "缺 miss_print",
    },
    {
        "id": "require-entry-missing-text",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "require_entry", "miss_print": "m"},
        ]}]},
        "needle": "缺 text",
    },
    {
        "id": "require-find-missing-miss-print",
        "data": {"segment": [{"name": "a", "ops": [{"kind": "require_find", "text": "x"}]}]},
        "needle": "缺 miss_print",
    },
    {
        "id": "require-find-missing-text",
        "data": {"segment": [{"name": "a", "ops": [{"kind": "require_find", "miss_print": "m"}]}]},
        "needle": "缺 text",
    },
    {
        "id": "require-focus-missing-contains",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "require_focus", "miss_print": "m"},
        ]}]},
        "needle": "缺 contains",
    },
    {
        "id": "require-focus-missing-miss-print",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "require_focus", "contains": "x"},
        ]}]},
        "needle": "缺 miss_print",
    },
    {
        "id": "require-go-missing-expect",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "require_go", "text": "x", "miss_print": "m"},
        ]}]},
        "needle": "缺 expect",
    },
    {
        "id": "require-go-missing-miss-print",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "require_go", "text": "x", "expect": "y"},
        ]}]},
        "needle": "缺 miss_print",
    },
    {
        "id": "require-go-missing-text",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "require_go", "expect": "y", "miss_print": "m"},
        ]}]},
        "needle": "缺 text",
    },
    {
        "id": "require-lib-missing-miss-print",
        "data": {"segment": [{"name": "a", "ops": [{"kind": "require_lib", "name": "gear"}]}]},
        "needle": "缺 miss_print",
    },
    {
        "id": "require-lib-missing-name",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "require_lib", "miss_print": "m"},
        ]}]},
        "needle": "缺 name",
    },
    {
        "id": "require-setting-missing-kw",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "require_setting", "miss_print": "m"},
        ]}]},
        "needle": "缺 kw",
    },
    {
        "id": "require-setting-missing-miss-print",
        "data": {"segment": [{"name": "a", "ops": [{"kind": "require_setting", "kw": "x"}]}]},
        "needle": "缺 miss_print",
    },
    {
        "id": "require-switches-missing-before",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "require_switches", "names": ["x"], "title": "t"},
        ]}]},
        "needle": "缺 before",
    },
    {
        "id": "require-switches-missing-names",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "require_switches", "before": {"expr": "var", "name": "v"}, "title": "t"},
        ]}]},
        "needle": "缺 names",
    },
    {
        "id": "require-switches-missing-title",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "require_switches", "before": {"expr": "var", "name": "v"}, "names": ["x"]},
        ]}]},
        "needle": "缺 title",
    },
    {
        "id": "require-tab-missing-miss-print",
        "data": {"segment": [{"name": "a", "ops": [{"kind": "require_tab", "name": "gear"}]}]},
        "needle": "缺 miss_print",
    },
    {
        "id": "require-tab-missing-name",
        "data": {"segment": [{"name": "a", "ops": [{"kind": "require_tab", "miss_print": "m"}]}]},
        "needle": "缺 name",
    },
    {
        "id": "require-tap-missing-text",
        "data": {"segment": [{"name": "a", "ops": [{"kind": "require_tap", "miss_print": "m"}]}]},
        "needle": "缺 text",
    },
    {
        "id": "return-lib-missing-name",
        "data": {"segment": [{"name": "a", "ops": [{"kind": "return_lib"}]}]},
        "needle": "缺 name",
    },
    {
        "id": "shell-missing-command",
        "data": {"segment": [{"name": "a", "ops": [{"kind": "shell"}]}]},
        "needle": "缺 command",
    },
    {
        "id": "skip-unless-installed-missing-command",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "skip_unless_installed", "contains": "c", "text": "t"},
        ]}]},
        "needle": "缺 command",
    },
    {
        "id": "skip-unless-installed-missing-contains",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "skip_unless_installed", "command": "pm path x", "text": "t"},
        ]}]},
        "needle": "缺 contains",
    },
    {
        "id": "skip-unless-installed-missing-text",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "skip_unless_installed", "command": "pm path x", "contains": "c"},
        ]}]},
        "needle": "缺 text",
    },
    {
        "id": "sleep-missing-seconds",
        "data": {"segment": [{"name": "a", "ops": [{"kind": "sleep"}]}]},
        "needle": "缺 seconds",
    },
    {
        "id": "start-nothing-to-launch",
        "data": {"segment": [{"name": "a", "ops": [{"kind": "start"}]}]},
        "needle": "至少要给 pkg / action / data / launcher 之一",
    },
    {
        "id": "start-flag-not-allowed",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "start", "pkg": "com.example", "activity": ".X",
             "clear_task": True, "flags": "--activity-clear-top"},
        ]}]},
        "needle": "flags 只放行",
    },
    {
        "id": "start-launcher-with-action",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "start", "pkg": "com.example", "launcher": True,
             "action": "android.intent.action.MAIN"},
        ]}]},
        "needle": "用 launcher 拉起时不能再给",
    },
    {
        "id": "start-launcher-missing-pkg",
        "data": {"segment": [{"name": "a", "ops": [{"kind": "start", "launcher": True}]}]},
        "needle": "launcher 要有 pkg",
    },
    {
        "id": "start-launcher-false",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "start", "pkg": "com.example", "launcher": False},
        ]}]},
        "needle": "launcher 只有 true",
    },
    {
        "id": "start-activity-without-pkg",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "start", "activity": ".X", "action": "android.intent.action.MAIN"},
        ]}]},
        "needle": "activity 要配 pkg",
    },
    {
        "id": "start-landing-args-on-command-shape",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "start", "action": "android.settings.SETTINGS", "expect": "广告"},
        ]}]},
        "needle": "只走 p.start 那条路",
    },
    {
        "id": "start-pkg-only-on-command-shape",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "start", "pkg": "com.example", "clear_task": False},
        ]}]},
        "needle": "只有 pkg 拉不起来",
    },
    {
        "id": "start-data-without-action",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "start", "data": "gs://search/setting"},
        ]}]},
        "needle": "data 要配 action",
    },
    {
        "id": "start-launcher-with-activity",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "start", "pkg": "com.example", "launcher": True, "activity": ".X"},
        ]}]},
        "needle": "用 launcher 拉起时不能再给",
    },
    {
        "id": "start-launcher-with-data",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "start", "pkg": "com.example", "launcher": True, "data": "gs://x"},
        ]}]},
        "needle": "用 launcher 拉起时不能再给",
    },
    {
        "id": "start-launcher-with-flags",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "start", "pkg": "com.example", "launcher": True,
             "flags": "--windowingMode 1"},
        ]}]},
        "needle": "用 launcher 拉起时不能再给",
    },
    {
        "id": "start-launcher-not-a-boolean",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "start", "pkg": "com.example", "launcher": "true"},
        ]}]},
        "needle": "launcher 只能是 true / false",
    },
    {
        "id": "start-pkg-not-a-string",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "start", "pkg": 1, "action": "android.settings.SETTINGS"},
        ]}]},
        "needle": "pkg 必须是非空字符串",
    },
    {
        "id": "start-activity-is-empty",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "start", "pkg": "com.example", "activity": "", "clear_task": True},
        ]}]},
        "needle": "activity 必须是非空字符串",
    },
    {
        "id": "start-data-not-a-string",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "start", "action": "android.intent.action.VIEW", "data": 1},
        ]}]},
        "needle": "data 必须是非空字符串",
    },
    {
        "id": "start-flags-not-a-string",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "start", "action": "android.settings.SETTINGS", "flags": 1},
        ]}]},
        "needle": "flags 必须是非空字符串",
    },
    {
        "id": "start-flags-blank",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "start", "action": "android.settings.SETTINGS", "flags": "   "},
        ]}]},
        "needle": "flags 只放行",
    },
    {
        "id": "start-flag-with-an-argument-not-allowed",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "start", "action": "android.settings.SETTINGS",
             "flags": "--activity-clear-top 1"},
        ]}]},
        "needle": "收到 '--activity-clear-top'",
    },
    {
        "id": "start-action-not-a-string",
        "data": {"segment": [{"name": "a", "ops": [{"kind": "start", "action": 1}]}]},
        "needle": "action 必须是非空字符串",
    },
    {
        "id": "start-clear-task-not-a-boolean",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "start", "pkg": "com.example", "clear_task": "false"},
        ]}]},
        "needle": "clear_task 只能是 true / false",
    },
    {
        "id": "start-or-skip-missing-activity",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "start_or_skip", "pkg": "p", "dead_ends": ["x"], "reason": "r"},
        ]}]},
        "needle": "缺 activity",
    },
    {
        "id": "start-or-skip-missing-dead-ends",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "start_or_skip", "pkg": "p", "activity": "a", "reason": "r"},
        ]}]},
        "needle": "缺 dead_ends",
    },
    {
        "id": "start-or-skip-missing-pkg",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "start_or_skip", "activity": "a", "dead_ends": ["x"], "reason": "r"},
        ]}]},
        "needle": "缺 pkg",
    },
    {
        "id": "start-or-skip-missing-reason",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "start_or_skip", "pkg": "p", "activity": "a", "dead_ends": ["x"]},
        ]}]},
        "needle": "缺 reason",
    },
    {
        "id": "tap-missing-text",
        "data": {"segment": [{"name": "a", "ops": [{"kind": "tap"}]}]},
        "needle": "缺 text",
    },
    # 报错原文与报错位置（#1414）：形状行原先只钉「被拒」，报错话术与「第几个 call / 第几段」
    # 全凭运气，消息换成 None、位置换成 None 或在 `and` / `or` 之间抖一下都不会红。
    {
        "id": "top-level-not-a-table",
        "data": "segment 不是表",
        "needle": "数据顶层必须是表（table）",
    },
    {
        "id": "segments-not-a-list",
        "data": {"segment": "x"},
        "needle": "至少要有 [[segment]]",
    },
    {
        "id": "segment-not-a-table",
        "data": {"segment": ["x"]},
        "needle": "第 1 段 必须是表",
    },
    {
        "id": "segment-unknown-key",
        "data": {"segment": [{"name": "a", "ops": [], "surprise": 1}]},
        "needle": "第 1 段 出现名单外的键",
    },
    {
        "id": "segment-name-not-a-string",
        "data": {"segment": [{"name": 5, "ops": []}]},
        "needle": "缺段名 name",
    },
    {
        "id": "segment-with-code-and-ops",
        "data": {"segment": [{"name": "a", "code": "x", "ops": []}]},
        "needle": "不能同时有 code 与 ops",
    },
    {
        "id": "segment-without-code-and-ops",
        "data": {"segment": [{"name": "a"}]},
        "needle": "既没有 code 也没有 ops",
    },
    {
        "id": "segment-ops-not-a-list",
        "data": {"segment": [{"name": "a", "ops": "x"}]},
        "needle": "的 ops 必须是数组",
    },
    {
        "id": "nested-op-not-a-table",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "gated", "entries": ["x"], "ops": [7]},
        ]}]},
        "needle": "第 1 个 op 第 1 个 op 必须是表",
    },
    {
        "id": "off-only-and-only-code",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "off", "only": ["x"], "only_code": "s", "page": "p"},
        ]}]},
        "needle": "不能同时给 only 与 only_code",
    },
    {
        "id": "off-only-not-a-list",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "off", "only": "x", "page": "p"},
        ]}]},
        "needle": "off 的 only 必须是非空数组",
    },
    {
        "id": "off-required-only-keep-overlap",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "off_required", "only": ["x"], "keep": ["x"], "page": "p"},
        ]}]},
        "needle": "off_required 里 only 与 keep 重叠",
    },
    {
        "id": "gesture-point-not-a-list",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "gesture", "start": 5, "end": [0.5, 0.7], "ms": 300},
        ]}]},
        "needle": "要是两个 0–1 的比例",
    },
    {
        "id": "gesture-ms-is-a-boolean",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "gesture", "start": [0.5, 0.3], "end": [0.5, 0.7], "ms": True},
        ]}]},
        "needle": "正的整数毫秒",
    },
    {
        "id": "if-var-name-not-a-string",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "if_var", "name": 5, "ops": []},
        ]}]},
        "needle": "name 必须是非空字符串",
    },
    {
        "id": "require-switches-before-name-not-a-string",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "require_switches", "before": {"expr": "var", "name": 5},
             "names": ["x"], "title": "t"},
        ]}]},
        "needle": "before 要写成",
    },
    {
        "id": "require-switches-before-not-a-table",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "require_switches", "before": "var", "names": ["x"], "title": "t"},
        ]}]},
        "needle": "before 要写成",
    },
    {
        "id": "require-switches-names-with-a-non-string",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "require_switches", "before": {"expr": "var", "name": "v"},
             "names": [5], "title": "t"},
        ]}]},
        "needle": "names 必须是非空的字符串数组",
    },
    {
        "id": "require-switches-title-not-a-string",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "require_switches", "before": {"expr": "var", "name": "v"},
             "names": ["x"], "title": 5},
        ]}]},
        "needle": "title 必须是非空字符串",
    },
    {
        "id": "require-expect-call-not-a-table",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "require_expect", "calls": [7]},
        ]}]},
        "needle": "第 1 个 op 的第 1 个 call 必须是表",
    },
    {
        "id": "require-expect-call-extra-key",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "require_expect", "calls": [{"args": ["x"], "name": "n"}]},
        ]}]},
        "needle": "第 1 个 call 出现名单外的键",
    },
    {
        "id": "require-expect-missing-miss-print",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "require_expect", "calls": [{"args": ["x"]}]},
        ]}]},
        "needle": "第 1 个 op 缺 miss_print",
    },
    {
        "id": "require-expect-call-without-args",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "require_expect", "calls": [{"kwargs": {}}], "miss_print": "m"},
        ]}]},
        "needle": "第 1 个 call 缺 args",
    },
    {
        "id": "require-expect-args-empty",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "require_expect", "calls": [{"args": []}], "miss_print": "m"},
        ]}]},
        "needle": "的 args 必须是非空数组",
    },
    {
        "id": "require-expect-args-not-a-list",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "require_expect", "calls": [{"args": "x"}], "miss_print": "m"},
        ]}]},
        "needle": "的 args 必须是非空数组",
    },
    {
        "id": "if-lib-any-call-with-both-name-and-method",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "if_lib_any", "calls": [{"name": "gear", "method": "x"}], "ops": []},
        ]}]},
        "needle": "要给「name / method」里的恰好一个",
    },
    {
        "id": "gated-entries-not-a-list",
        "data": {"segment": [{"name": "a", "ops": [{"kind": "gated", "entries": "x"}]}]},
        "needle": "gated 需要非空的 entries",
    },
    {
        "id": "lib-arg-block-extra-key",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "lib", "name": "close_named", "args": [{"ops": [], "surprise": 1}]},
        ]}]},
        "needle": "实参块 出现名单外的键",
    },
]


def _walk_ops(ops):
    """一条 op 列表连同 `OPS` 声明的子 op 列表里的全部 op。"""
    for op in ops:
        if not isinstance(op, dict):
            continue
        yield op
        spec = OPS.get(op.get("kind"))
        if spec is not None:
            for key in spec.nested:
                nested = op.get(key)
                if isinstance(nested, list):
                    yield from _walk_ops(nested)


def _case_ops(data):
    for segment in data.get("segment", []):
        if isinstance(segment, dict):
            nested = segment.get("ops")
            if isinstance(nested, list):
                yield from _walk_ops(nested)


def _names_something_absent(data):
    """这条行拒绝的是结构里没有的名字（顶层字段、段字段或 kind）。

    这样的行句柄为空：它的内容是「这个名字不在结构里」，句柄会说反。
    """
    if not isinstance(data, dict) or set(data) - TOP_KEYS:
        return True
    segments = data.get("segment")
    if not isinstance(segments, list):
        return True
    for segment in segments:
        if not isinstance(segment, dict) or set(segment) - SEGMENT_KEYS:
            return True
    return any(op.get("kind") not in OPS for op in _case_ops(data))


def handles(case):
    """这条行依赖的结构项，全部从它自己的数据现算。"""
    data = case["data"]
    if _names_something_absent(data):
        return ()
    found = set()
    for key in data:
        if key in TOP_KEYS:
            found.add(("top-key", key))
    for segment in data.get("segment", []):
        if not isinstance(segment, dict):
            continue
        for key in segment:
            if key in SEGMENT_KEYS:
                found.add(("segment-key", key))
    for op in _case_ops(data):
        kind = op["kind"]
        found.add(("kind", kind))
        for key in OPS[kind].required:
            if key not in op:
                found.add(("required", kind, key))
    return tuple(sorted(found))


def structure():
    """当前存在的全部结构项：四类句柄各自从 `OPS` / 顶层 / 段键现算。"""
    found = {("top-key", key) for key in TOP_KEYS}
    found |= {("segment-key", key) for key in SEGMENT_KEYS}
    for kind, spec in OPS.items():
        found.add(("kind", kind))
        found |= {("required", kind, key) for key in spec.required}
    return found


def produce(case):
    """校验器给出的报错原文；不再被拒时留下 `<accepted>`。"""
    try:
        catalog.validate(case["data"])
    except catalog.SchemaError as exc:
        return str(exc)
    return "<accepted>"


def _expected():
    """从 `OPS` 反推「应该有 case」的句柄：每个必填键各一条缺键 case（#1399）。

    句柄词表与 `handles()` 同一口径，所以 `OPS` 加一个必填键，这里立刻点名它缺 case；
    删一条缺键行，`gap_violations()` 跟着红。`OPS` 是唯一 owner，这份集合不另存一份。
    """
    return {("required", kind, key) for kind, spec in OPS.items() for key in spec.required}


FAMILY = Family("catalog-rejections", CASES, handles=handles, structure=structure,
                produce=produce, expected=_expected)

if __name__ == "__main__":
    sys.exit(cli())
