# 各品牌手动清单

| 品牌 | 清单 | 实测机型 |
|---|---|---|
| OPPO / 一加 / realme | [OPPO-ColorOS.md](OPPO-ColorOS.md) | Find N6、Find X10 Pro Max、Find X9 Ultra（部分）、Find N3 典藏版（部分） |
| 荣耀 | [荣耀-MagicOS.md](荣耀-MagicOS.md) | PNM-AN10 |
| 小米 / Redmi | [小米-HyperOS.md](小米-HyperOS.md) | Xiaomi 18 Pro Max |
| vivo / iQOO | [vivo-OriginOS.md](vivo-OriginOS.md) | X300 Ultra |

## 怎么读

- 🔴 关掉　🟢 保留　⚠️ 注意
- 「路径」是从桌面开始点的顺序。
- 你的界面和清单对不上：系统版本不同。在设置页顶部的搜索框搜开关名，多数能搜到。

## 每个品牌都要做的三件事

1. **系统广告开关**：设置里搜「广告」。
2. **广告跟踪 / OAID**：设置里搜「广告跟踪」或「设备标识」，每个 App 的开关都关掉。
3. **营销通知**：通知管理里，每个 App 点进去，关掉名字带「营销」「活动」「优惠」「推荐」「资讯」的渠道，保留订单、物流、更新、聊天。
   - 部分 vivo 页面只有应用级总开关，不能按渠道安全关闭；当前工具会跳过，见 [vivo 清单](vivo-OriginOS.md)。
     要压掉某个 App 的推送就整包关：`python3 tool/run.py -s <序列号> notif-off <包名>`。
