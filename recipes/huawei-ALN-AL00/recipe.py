# 华为 ALN-AL00 / HarmonyOS 4.2 通知路径，2026-10-30 逐项实测。
# 由 tool/fast.py 注入 p 和 ONLY；新参数化配方未整轮真机重跑。
BUILD = "ALN-AL00 4.2.0.223(C00E215R5P16)"
MODELS = ["ALN-AL00"]

import os
from collections import defaultdict
from dataclasses import dataclass, field
import datetime
import json
from pathlib import Path
import re
import shlex
import time

import adb_link
from chan_fast import ShellPhone, parse, truncated
from channel_policy import protected_channel
from fast import ScreenLocked
from row import bounds
import wait

MODEL = "ALN-AL00"
APP_PAGE = "com.android.settings/com.android.settings.Settings$AppNotificationSettingsActivity"
HEADER = "com.android.settings:id/entity_header_title"
CHECKBOX = "com.android.settings:id/checkboxWidget"
BLOCKED = {"ignore", "deny", "errored"}


@dataclass(frozen=True)
class Item:
    package: str
    channel: str
    name: str
    app: str

    @property
    def key(self):
        return self.package, self.channel


@dataclass
class Result:
    changed: int = 0
    already: int = 0
    blocked: int = 0
    failed: list = field(default_factory=list)


def load_items(path):
    """不沿用旧清单的渠道名；点击前总是取本机当前渠道名。"""
    items, app_names = {}, {}
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = [value.strip() for value in line.split("\t")]
        if (len(parts) < 4 or not re.fullmatch(r"[\w.]+", parts[0])
                or not parts[1] or truncated(parts[1]) or not parts[2] or not parts[3]):
            raise ValueError(f"清单第 {number} 行需要有效包名、完整渠道 ID 和第四列应用名")
        package, channel, name, app = parts[:4]
        if package in app_names and app_names[package] != app:
            raise ValueError(f"清单第 {number} 行：同一应用的显示名不一致")
        app_names[package] = app
        item = Item(package, channel, name, app)
        if item.key in items and items[item.key] != item:
            raise ValueError(f"清单第 {number} 行：同一渠道的审核名称不一致")
        items[item.key] = item
    return list(items.values())


def permission_mode(reader, package):
    text = reader.shell("cmd appops get " + shlex.quote(package) + " POST_NOTIFICATION").output
    match = re.search(r"(?m)^POST_NOTIFICATION:\s*(\w+)", text)
    if match:
        return match.group(1)
    return "default" if "No operations" in text else "unknown"


def require_device(reader):
    model = reader.shell("getprop ro.product.model").output.strip()
    build = reader.shell("getprop ro.build.display.id").output.strip()
    if model != MODEL or build != BUILD:
        raise ValueError(f"仅适配 {MODEL} / {BUILD}；当前版本未验证，未修改")


def guard(before, apps_before, current, apps, allowed):
    """查全部原有渠道，不能只查当前应用；权限总开关也不能变化。"""
    for key, old in before.items():
        new = current.get(key)
        if key not in allowed and (new is None or old[1:] != new[1:]):
            raise RuntimeError("清单外渠道发生变化，停止并保留备份：" + key[0])
    if any(apps.get(package) != value for package, value in apps_before.items()):
        raise RuntimeError("应用通知总开关发生变化，停止并保留备份")


def headers(root):
    return {node.get("text") for node in root.iter("node")
            if node.get("resource-id") == HEADER}


def checkbox(phone, app, name):
    if phone.focus() != APP_PAGE:
        raise RuntimeError("离开已确认的应用通知页，未继续点击")
    root = phone.tree()
    titles = headers(root)
    # 应用身份在入页时已核对；只允许在同一 Activity 内受控滚动。
    if titles and titles != {app}:
        raise RuntimeError("应用身份已变化，未继续点击")
    nodes = {}
    for node in root.iter("node"):
        if (node.get("resource-id") == CHECKBOX
                and node.get("class") == "android.widget.CheckBox"
                and node.get("checkable") == "true" and node.get("enabled") == "true"
                and name in (node.get("text", "").strip(), node.get("content-desc", "").strip())
                and phone.on_screen(node)):
            nodes[node.get("bounds")] = node
    return next(iter(nodes.values())) if len(nodes) == 1 else None


def open_app(phone, item):
    phone.d.shell("am start -f 0x10008000 -a android.settings.APP_NOTIFICATION_SETTINGS"
                  " --es android.provider.extra.APP_PACKAGE " + shlex.quote(item.package))

    def sample():
        if phone.focus() != APP_PAGE:
            return None
        return item.app if headers(phone.tree()) == {item.app} else None

    def locked():
        return ScreenLocked("手机锁屏，请机主解锁后重跑") if phone.locked() else None

    if not wait.until(sample, timeout=8, stable=.2, poll=.15, blocked=locked,
                      now=time.monotonic, sleep=time.sleep):
        raise RuntimeError("未核对到目标应用通知页")


def locate(phone, item, name):
    phone.top(12)
    for _ in range(16):
        if phone.locked():
            raise ScreenLocked("手机锁屏，未继续点击")
        node = checkbox(phone, item.app, name)
        if node is not None:
            return node
        if not phone.scroll_more():
            break
    return None


def save_snapshot(serial, before, apps, modes, awake):
    from run import latest_backup
    path = Path(latest_backup(serial)) / ("huawei-channels-before-"
           + datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".json")
    data = {"channels": [[*key, *value] for key, value in sorted(before.items())],
            "apps": apps, "permissions": modes, "stay_on": awake}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print("改动前快照已保存到本地 backups/；包含个人渠道资料，请勿提交")
    return path


def restore_modes(reader, modes):
    """只还原本机已确认的 default→allow 副作用，不覆盖其他来源的改动。"""
    failures = []
    for package, original in modes.items():
        try:
            current = permission_mode(reader, package)
            if original == "default" and current == "allow":
                reader.shell("cmd appops set " + shlex.quote(package) + " POST_NOTIFICATION default")
                current = permission_mode(reader, package)
            if current != original:
                failures.append(package)
        except adb_link.DeviceLost:
            raise
        except (OSError, RuntimeError):
            failures.append(package)
    if failures:
        raise RuntimeError("通知权限模式未恢复原值：" + "、".join(failures))


def execute(phone, items, want_on=False, verify=False, reader=None):
    """只使用配方引擎提供的读屏会话，不创建第二个会话。"""
    serial = phone.serial
    result = Result()
    if not items:
        return result
    reader = reader or ShellPhone(serial)
    if not verify:
        require_device(reader)
    before, apps_before = parse(reader)
    groups = defaultdict(list)
    modes = {package: permission_mode(reader, package)
             for package in dict.fromkeys(item.package for item in items)}
    for item in items:
        value = before.get(item.key)
        if value is None or value[2]:
            result.failed.append(item.app + "：渠道不存在或已删除")
        elif value[0].strip() != item.name:
            result.failed.append(item.app + "：渠道名已变化，请重新审核清单")
        elif not want_on and protected_channel(value[0], item.channel):
            result.failed.append(item.app + "：受保护的功能通知，未关闭")
        elif (value[1] != 0) == want_on:
            result.already += 1
        elif apps_before.get(item.package) or modes[item.package] in BLOCKED:
            result.blocked += 1
            if want_on:
                result.failed.append(item.app + "：应用通知原已禁止，未自动开启总开关")
        elif modes[item.package] not in {"allow", "default"}:
            result.failed.append(item.app + "：通知权限模式未识别或未验证，未修改")
        elif verify:
            result.failed.append(item.app + " / " + value[0] + "：尚未达到目标状态")
        else:
            groups[item.package].append(item)
    if not groups:
        return result
    allowed = {item.key for app_items in groups.values() for item in app_items}

    awake = reader.shell("settings get global stay_on_while_plugged_in").output.strip()
    if not awake.isdigit():
        raise RuntimeError("读不到插电常亮原值，未修改")
    save_snapshot(serial, before, apps_before, modes, awake)
    active = phone
    opened_modes = {}
    try:
        reader.shell("settings put global stay_on_while_plugged_in 7")
        if active.locked():
            raise ScreenLocked("手机锁屏，请机主解锁后重跑")
        for app_items in groups.values():
            opened_modes[app_items[0].package] = modes[app_items[0].package]
            open_app(active, app_items[0])
            for item in app_items:
                current, apps = parse(reader)
                guard(before, apps_before, current, apps, allowed)
                value = current.get(item.key)
                if value is None or value[2] or value[0].strip() != item.name:
                    raise RuntimeError("渠道记录已变化，未继续点击")
                if (value[1] != 0) == want_on:
                    result.already += 1
                    continue
                name = value[0]
                if sum(key[0] == item.package and val[0] == name and not val[2]
                       for key, val in current.items()) != 1:
                    result.failed.append(item.app + "：渠道名不唯一，未猜测渠道 ID")
                    continue
                node = locate(active, item, name)
                if node is None or node.get("checked") != ("false" if want_on else "true"):
                    result.failed.append(item.app + " / " + name + "：未确认独立复选框或状态不一致")
                    continue
                print(("即将恢复：" if want_on else "即将关闭：") + item.app + " / " + name, flush=True)
                left, top, right, bottom = bounds(node)
                if active.locked() or tuple(active.d.window_size()) != (active.W, active.H):
                    raise RuntimeError("锁屏或尺寸变化，未使用旧坐标")
                active.d.shell(f"input tap {(left + right)//2} {(top + bottom)//2}")
                time.sleep(.3)
                after, apps = parse(reader)
                guard(before, apps_before, after, apps, allowed)
                guard(current, apps_before, after, apps, {item.key})
                value = after.get(item.key)
                if value is None or value[2]:
                    raise RuntimeError("点击后渠道记录已变化，未确认目标状态")
                if (value[1] != 0) == want_on:
                    result.changed += 1
                    active.changed.append((item.app, name))
                else:
                    result.failed.append(item.app + " / " + name + "：回读未确认")
        active.d.shell("input keyevent HOME")
    finally:
        try:
            restore_modes(reader, opened_modes)
        finally:
            reader.shell("settings put global stay_on_while_plugged_in " + awake)
            if reader.shell("settings get global stay_on_while_plugged_in").output.strip() != awake:
                raise RuntimeError("插电常亮未恢复，请按备份手动核对")
    current, apps = parse(reader)
    guard(before, apps_before, current, apps, allowed)
    if any(permission_mode(reader, package) != original for package, original in modes.items()):
        raise RuntimeError("候选应用通知权限模式发生变化，请按快照核对")
    for item in items:
        value = current.get(item.key)
        if (value and not value[2] and (value[1] != 0) != want_on
                and not (not want_on and (apps.get(item.package) or modes[item.package] in BLOCKED))):
            result.failed.append(item.app + " / " + value[0] + "：最终复查未达目标")
    return result


p = globals().get("p")
ONLY = globals().get("ONLY") or []
FAILED_STEPS = []


def run_channels():
    selected = os.environ.get("AAC_HUAWEI_CHANNELS")
    action = os.environ.get("AAC_HUAWEI_CHANNEL_ACTION", "off")
    if action not in {"off", "on", "verify"}:
        raise ValueError("AAC_HUAWEI_CHANNEL_ACTION 只能为 off、on 或 verify")
    if p is None or not selected:
        raise ValueError("通过机型入口执行，并用 AAC_HUAWEI_CHANNELS 指定人工审核清单")
    result = execute(p, load_items(Path(selected)), want_on=action == "on", verify=action == "verify")
    if result.failed:
        raise RuntimeError("；".join(dict.fromkeys(result.failed)))
    print(f"调整 {result.changed} 项，原有总通知屏蔽 {result.blocked} 项")
    return result


def step(name):
    def decorate(action):
        if ONLY and name not in ONLY:
            return action
        print("\n== " + name)
        if p is not None:
            p.miss = 0
        try:
            action()
        except adb_link.DeviceLost:
            raise
        except (OSError, ValueError, RuntimeError) as error:
            FAILED_STEPS.append(name)
            print("未完成：" + str(error))
        return action
    return decorate


@step("营销通知")
def _():
    if not os.environ.get("AAC_HUAWEI_CHANNELS"):
        print("跳过：未提供人工审核的通知清单，使用方法见本机型 README")
        return
    run_channels()
