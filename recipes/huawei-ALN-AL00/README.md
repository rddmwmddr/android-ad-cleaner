# 华为 ALN-AL00 / HarmonyOS 4.2 通知脚本

限定 `ALN-AL00 4.2.0.223(C00E215R5P16)`、Android 12 / SDK 31。其他型号或版本拒绝修改通知，不套用荣耀路径。

2026-10-30 在一台本机的人工审核清单上，逐项回读确认关闭 48 个渠道、31 个候选原已由应用通知权限屏蔽。约 164 秒后的只读回查仍满足目标，清单外渠道及原权限模式未变。

计数口径：对该次 79 条候选的 `(包名, 渠道ID)` 在前后快照中逐条匹配，结束时重要级别为 0 的计 48 条；仍非 0 但所属应用原通知权限为禁止的计 31 条，剩余 `79 - 48 - 31 = 0`。原始清单和快照含个人资料，只在机主本地备份，不进入公开文件；这些计数不是新脚本的测试样本成绩。

这是路径实测记录。参数化后的新代码只做离线回归，尚未在手机上整轮重跑，不填写新脚本的真机耗时，也不宣称长期不被系统重同步。

实现和离线测试均放在本机型配方目录内，由现有机型入口执行；未新增桌面客户端的清单选择流程，也未验证打包版。

## 使用

先备份和扫描，人工逐项审核候选，仅保留明确希望关闭的渠道。第三列必须是当前渠道名，第四列必须是本机显示的应用名；名称变化会要求重新审核。

```bash
python3 "tool/run.py" -s "<序列号>" backup
python3 "tool/run.py" -s "<序列号>" chan-scan
AAC_HUAWEI_CHANNELS="<审核后的清单.tsv>" AAC_HUAWEI_CHANNEL_ACTION="verify" \
  python3 "tool/run.py" -s "<序列号>" recipe 营销通知
AAC_HUAWEI_CHANNELS="<审核后的清单.tsv>" AAC_HUAWEI_CHANNEL_ACTION="off" \
  python3 "tool/run.py" -s "<序列号>" recipe 营销通知
python3 "tool/run.py" -s "<序列号>" finish
```

清单和动作参数只对当前命令生效，不修改系统环境配置。`AAC_HUAWEI_CHANNEL_ACTION` 支持 `off`（默认关闭）、`on`（恢复开启）、`verify`（核查关闭目标状态）；未知动作直接报错。核查不打开通知页或拨动开关，但外层机型引擎仍会管理读屏会话和临时插电常亮，并在退出时恢复。

不带清单时提示并跳过，不记为失败步骤，也不会选择备份里的历史应用列表。这个步骤不暂停快应用，也不修改其他广告/隐私开关；快应用仍使用独立的检测、确认及 `quickapp off/on` 流程。

## 恢复

仅将本次确实关闭且原来开启的渠道整理成恢复清单，不要将原已关闭的渠道一并开启：

```bash
AAC_HUAWEI_CHANNELS="<本次实际关闭的清单.tsv>" AAC_HUAWEI_CHANNEL_ACTION="on" \
  python3 "tool/run.py" -s "<序列号>" recipe 营销通知
python3 "tool/run.py" -s "<序列号>" finish
```

工具保存改动前渠道、总开关、权限模式和插电常亮快照到 `backups/`。恢复命令以重新开启渠道为目标，原重要级别可据快照手动核对。恢复新代码也尚未做真机重跑。

## 本机发现与边界

- 同一应用的多个候选在同一页连续处理，避免每个渠道都跳到原生分类页。
- 只接受已核对应用名称的 Android 应用通知页与独立、明确命名的渠道复选框；不点击应用通知总开关。
- 滚动前核对应用身份；页眉滚出屏幕后仍要求 Activity 不变。相同位置的重复节点去重，真正多解时跳过。
- 每步检查全部清单外渠道和总开关；出现差异就停止，不再声称盲点一次就已回退。
- 原已禁止通知的应用保留原状；`default → allow` 的已知副作用恢复原 `default` 并回读，其他模式差异报错。
- 华为原生页会合并类别；曾观察到进入该页后渠道旧状态重新同步。这里只报告实际回读，不保证永久关闭。
- 不关闭整个“其他/服务提醒”分类，不默认选择路况、直播或媒体发送提醒。是否包含此类功能通知必须由机主明确审核清单决定。
- 已脱敏的兼容性反馈：[Issue #330](https://github.com/rddmwmddr/android-ad-cleaner/issues/330)。

## 离线验证

本机型的离线测试位于 `recipes/huawei-ALN-AL00/tests/test_recipe.py`，覆盖实际机型执行入口的关闭、恢复、核查分派，以及渠道名、通知页身份、清单外渠道、权限和临时设置恢复等保护。`tests/test_recipe_suites.py` 只负责将 `recipes/*/tests/test_*.py` 接入仓库现有的 unittest 入口，不包含厂商逻辑。

```bash
python3 -m unittest discover -s "recipes/huawei-ALN-AL00/tests" -v
python3 -m unittest discover -s "tests"
python3 -m ruff check --select F,E9 "tool" "tests" "gui" "recipes/huawei-ALN-AL00"
```

静态检查使用仓库 CI 指定的 ruff 0.17.3。本地离线结果不代表已运行 GitHub Actions、打包或真机复跑。
