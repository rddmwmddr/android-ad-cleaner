# 桌面客户端的鸿蒙功能

0.4.2 起，原「肉呆去广告 · 鸿蒙版」并入同一个 Mac / Windows 客户端。这条通道还没有在鸿蒙真机上复测；0.4.1 及更早的安装包只支持安卓连接。

连接页会分别列出安卓与鸿蒙设备。纯血鸿蒙由客户端取出 HDC 后连接，手机上不用装 App；鸿蒙 4 及以前仍走 adb。多台手机同时连接时，必须点选要操作的那台。

进入鸿蒙页面后可选择系统广告、跨应用关联保护、小艺搜索、负一屏、浏览器、应用市场、用户体验计划。每项结果单独显示；未完成项可以重试。停止和关窗会等当前开关回读及原状态保存完成，再结束任务。

每次拨动前写入原状态，多次执行保留最早的状态。「还原改动」只处理这台设备有记录的开关。旧鸿蒙客户端的 `RoudaiHarmony` 数据目录首次使用时会复制进统一客户端的 `harmony` 数据目录，原文件保留。完成后仍建议在手机上关闭开发者选项；关闭后不会撤销去广告改动。

## 适配范围

规则来源是 HOP-AL10（Pura X Max）7.0.0.111 的既有实测，展开与折叠两种状态都在原项目验证过。本次合并不会把其他型号自动标成已实测；系统和 App 版本不同可能找不到入口。当前只接受 API 20 及以上的鸿蒙 USB 设备。

不关闭整个 App 的通知、不卸载或停用系统包，不碰系统更新、不绕过锁屏、不代替用户同意协议。保护开关按规则打开。具体范围见 [词库](docs/词库.md)，未验证线索仍在 [词条线索](docs/词条线索.md)。

## 源码与验证

来源：[harmony-ad-cleaner 的 179520d](https://github.com/rddmwmddr/harmony-ad-cleaner/commit/179520d)。迁入既有引擎、规则、词库和离线用例；桌面外壳由统一客户端提供。没有复制手机调试签名、设备 ID 或私有日志。

- `gui/harmony_engine.py`：HDC、读屏、导航、点击和回读。
- `gui/harmony_client.py`：选机、互斥、进度、原状态、日志和旧数据迁移。
- `gui/harmony_vocab.py`：从 `entry/src/main/ets/engine/Recipes.ets` 解析规则。
- `entry/.../Phone.ets`、`Screen.ets`：保留原引擎作为离线一致性守卫，不构建或分发手机 App。
- `recipes.json`：打包用冻结规则；更改清单后运行 `python3 gui/harmony_engine.py freeze harmony/recipes.json`。
- 词库生成：`python3 gui/harmony_vocab.py write`。
- 设备无关回归：仓库根 `python -m unittest discover -s tests`，前端先 `npm ci`。
- 打包件 `--smoke-harmony` 检查 HDC 可执行、规则与资源完整，不连接手机。

## HDC 的来源与取用

HDC 与共享库是用自 OpenHarmony `7.0-Release` SDK（包内版本 `26.0.0.38-Beta`）的官方工具，按 Mac ARM / Intel / Windows 各取一套。二进制不入库：`gui/hdc_fetch.py` 按钉死的 SHA-256 下载三个 tarball、解出 `hdc` 与 `libusb_shared`，构建时放进打包资源；原许可声明完整保留在 `desktop/vendor/NOTICE-hdc.txt`。

源码运行先取一次工具（下载量约 1.3 GB，之后命中缓存）：

```bash
python3 gui/hdc_fetch.py          # 取当前平台的工具到 ~/.cache/android-ad-cleaner/hdc
```

缓存目录可用 `AAC_HDC_CACHE` 覆盖。`find_hdc()` 的顺序是：显式 `HDC` 环境变量 → 缓存目录 → 包内 `harmony/desktop/vendor/<平台>/` → `PATH` → SDK 默认路径。
