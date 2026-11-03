# 各品牌手动清单

| 品牌 | 清单 | 实测机型 |
|---|---|---|
| 华为 | [华为-HarmonyOS.md](华为-HarmonyOS.md) | ALN-AL00（4.2.0.223；通知路径实测，新脚本待整轮复测） |
| OPPO / 一加 / realme | [OPPO-ColorOS.md](OPPO-ColorOS.md) | Find N6、Find X10 Pro Max、Find X8s、Find X9 Ultra（部分）、Find N3 典藏版（部分）、Find N5、Pad Mini、Reno5 Z（海外版）、一加 Ace 2、Ace 2 Pro、Ace 5、Ace 6T、13T |
| 荣耀 | [荣耀-MagicOS.md](荣耀-MagicOS.md) | PNM-AN10、WKL-AN20（MagicOS 11；路径逐项实测，整轮待复测） |
| 小米 / Redmi | [小米-HyperOS.md](小米-HyperOS.md) | Xiaomi 18 Pro Max、18 Fold、17 Ultra、17、15、13 Ultra、Pad 7、REDMI K80 至尊版、K80 Pro、K90 Pro Max、Redmi K70、K70 Pro、Note 12 Turbo、Note 14 Pro、Note 14 5G |
| vivo / iQOO | [vivo-OriginOS.md](vivo-OriginOS.md) | X300 Ultra（V2547DA、V2547A）、X Fold6（V2545A，负一屏需手动）、iQOO V2324HA、V2361A、V1986A、V2417A、iQOO Z11 Turbo（V2536A）、vivo V2309A |
| 魅族 | [魅族-Flyme.md](魅族-Flyme.md) | 21 Pro（MEIZU 21 Pro，Flyme 12.6.0.0A；路径手动核对，脚本整段待验证） |

## 怎么读

- 🔴 关掉　🟢 保留　⚠️ 注意
- 「路径」是从桌面开始点的顺序。
- 你的界面和清单对不上：系统版本不同。在设置页顶部的搜索框搜开关名，多数能搜到。

## 每个品牌都要做的三件事

1. **系统广告开关**：设置里搜「广告」。
2. **广告跟踪 / OAID**：设置里搜「广告跟踪」或「设备标识」，每个 App 的开关都关掉。
3. **营销通知**：通知管理里，每个 App 点进去，关掉名字带「营销」「活动」「优惠」「推荐」「资讯」的渠道，保留订单、物流、更新、聊天。
   - 部分 vivo 页面只有应用级总开关，不能按渠道安全关闭；当前工具会跳过，见 [vivo 清单](vivo-OriginOS.md)。
