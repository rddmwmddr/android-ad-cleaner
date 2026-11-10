# 用 Dhizuku（Device Owner）替代 shell 后端

本工具不引入 [Dhizuku](https://github.com/iamr0s/Dhizuku) 作为执行后端。

## 为什么超出范围

Dhizuku 做的事是把 **Device Owner** 权限共享给其他 App。客户端拿到的身份是设备所有者，不是 shell，这两者能做的事完全不同。

本工具的核心动作是打开系统设置页、读出每个开关、逐个点击。手机版靠 uiautomator2 读屏点击（`aac_android/u2.py` 经 shell 启动 `app_process` 里的读屏服务），辅以少量 shell 命令：`pm suspend`、`cmd appops`、`settings put`、`am force-stop`。这些都需要 **shell / adb 级权限**。

Dhizuku 的 `remoteProcess` 起进程用的是它自己的普通 App uid（`DhizukuService.java` 的 `remoteProcess` → `DhizukuProcess.remoteProcess`），不是 shell。它调不了 `pm`、`settings`、`appops`，更启动不了 uiautomator2 的读屏服务。作为设备所有者，它能做的只有 `DevicePolicyManager` 那一套：

- `setApplicationHidden` —— 约等于 `pm disable-user`
- `setPackagesSuspended` —— 约等于 `pm suspend`
- `setPermissionGrantState` —— 授予 / 撤销运行时权限
- 白名单内的 secure / global 设置、user restrictions

也就是说，它能替代的只是「禁用 / 挂起 App、撤运行时权限」这一小块，而这一块现在被 Shizuku 与手机版内置无线调试完全覆盖（ADR-0014）。它替代不了读屏与点击，能力**窄于**现有方案。

激活门槛反而更高：官方要求设备不绑定任何账号，还要用一次 adb 把它设成 Device Owner（[激活说明](https://github.com/iamr0s/Dhizuku/discussions/19)）。手机版的内置无线调试（#622）已经做到不用装任何东西。

## 什么时候可以重新评估

如果产品路线改成「不点 UI、纯靠 DPM 隐藏或挂起广告 App」，Dhizuku 才有位置——但那已经是另一种产品形态，不再是逐个开关的审计与回读。

如果诉求是「Shizuku 被系统杀掉导致跑到一半断线」，正确的解法是加固无线调试后端与断线恢复（#746、#769 那批），不是换权限模型。

## 历史请求

- #922 — 「可以添加对 Dhizuku 的适配~ 更稳定」
