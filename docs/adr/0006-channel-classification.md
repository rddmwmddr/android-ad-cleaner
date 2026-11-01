# 渠道判定是一个具名判定集，不是一个类别

营销 / 服务 / 受保护三种渠道判定原先散在两处、各用不同的匹配域。基线 `69cfc4d` 的事实：

- `tool/chan_fast.py:76` 的 `KW`（营销关键词）匹配 `name + " " + cid`，是渠道**进入候选清单**的必要条件。
- `tool/chan_fast.py:77-80` 的 `SKIP` 只匹配渠道名，命中则**不进候选清单**。
- `tool/chan_fast.py:86` 的 `VIVO_MARKETING` 按 cid 命中 `^VPushChannel_(?:0|4|6)$`，只越过 `SKIP`，不越过 `KW`；扫描分支里写成 `(VIVO_MARKETING.match(cid) or not SKIP.search(name))`。
- `gui/app.py:382` 的 `SERVICE` 匹配**整行 TSV**（含包名、应用名），命中则渠道照常显示、只是**默认不勾**。
- 受保护判定已经统一在 `tool/channel_policy.py:8` 的 `protected_channel()`，`chan_fast`、`gui/app.py`、`huawei_channels` 三处消费它。架构体检报告里「三份词表在漂」的措辞在这个基线上已经过时：`PHOTO_SPOT` 不是第二份保护词表。

真正还分散的是 `SKIP` 与 `SERVICE` 两份「服务类」词表。它们不是一个概念的两份拷贝，而是**两级不同后果**：`SKIP` 把渠道从候选清单里拿掉，`SERVICE` 把渠道留在清单里但不预选；匹配域也不同（名字 vs 整行）。同一份词表无法同时复现这两种后果。

## Decision

**一个入口，一组具名判定。** 在 `tool/channel_policy.py` 新增 `classify(name, channel_id="", list_label="", package="", app="")`，返回一个 frozen 结果对象，字段是判定而不是类别：

| 字段 | 含义 | 对应基线 |
|---|---|---|
| `marketing_candidate` | 营销关键词命中，可进候选清单 | `KW` |
| `scan_excluded` | 服务类、不进候选清单 | `SKIP` 且非厂商营销 ID |
| `default_unchecked` | 已进清单但默认不勾 | `SERVICE` |
| `protected` | 找机位一类，始终不动 | `protected_channel()` |
| `vivo_marketing_id` | 按 cid 认的 vivo 营销分类 | `VIVO_MARKETING` |
| `ad_network_id` | 渠道 ID 命中广告网络名，命中即营销并越过服务词（见增补） | `AD_NETWORK` |

不采用报告里的单一 `category` 枚举：它装不下 `scan_excluded` 与 `default_unchecked` 的差异，压平任何一级都会改变用户可见行为。

**厂商营销 ID 的合成在 classify 内部完成。** `scan_excluded = skip_hit and not vivo_marketing_id`，消费方只读 `scan_excluded`，不再各自重写那个 OR。字段名保留 vivo 范围（`vivo_marketing_id`），不命名为泛化的 `vendor`——目前没有通用机制。

**序列化词条改写成字段规则。** 基线里两个词条依赖 TSV 形状：`youtube\t2\t` 实际是在匹配「包名尾部 `youtube` + cid=`2`」，`\t其他$` 匹配「最后一个字段恰为『其他』」（没有非空应用名列时是渠道名，有非空应用名列时是应用名）。新接口接收解析后的字段，分别写成「包名尾部 `youtube` 且渠道 ID 为 `2`」与「最后一个字段等于『其他』」；等价性由对拍语料证明。

**`protected_channel()` 保留为下层判据。** `toggle()` / `verify()` / `huawei_channels` 继续直接调它（它们需要 `list_label` 这个第三输入），classify 内部也调它，不再有第二套保护词表。

**本轮零行为变化。** 已知的两处分歧原样保留并用用例钉住，另开票处理：`\t其他$` 在带非空应用名列的行上不命中，以及服务类裸词会命中包名或应用名。

**对拍。** 测试内冻结基线实现（旧 `KW` / `SKIP` / `VIVO_MARKETING` / `SERVICE` 原文与旧组合式），配一份覆盖每个词条与序列化边界的语料，逐条比对旧判定与新 `classify()`，差异必须为零。语料要能证伪：故意包含带第四列的「其他」行、`youtube` 渠道行、包名/应用名误命中行。

## Considered Options

- **具名判定集**（采纳）vs **单一类别枚举**（否）。枚举无法在不改变行为的前提下同时表达两级服务语义；报告的价值在「一处加词」，不在类别数。
- **字段规则**（采纳）vs **把字段拼回 TSV 再跑旧正则**（否）。拼回字符串可逐字保真，但把「第四列在不在」这种隐式耦合继续藏起来，且无法单独测试。
- **放进 `channel_policy.py`**（采纳）vs **新建模块**（否）。`gui/app.py` 已经通过 `_tool("channel_policy")` 取它，`chan_fast` / `huawei_channels` 也直接 import；扩展现有模块不动任何调用关系，符合 ADR-0003 的惰性取。
- **服务词表单张表**（采纳）vs **拆成功能 / 服务 / 含糊三个子表**（否）。判定只有「扫描排除」一级，分桶是纯装饰，会把一个概念拆成三个名字。
- **零变化 + 冻结基线对拍**（采纳）vs **顺手修已知分歧**（否）。重构与行为修复混在一笔，对拍的「差异为零」就不再是证据。

## Consequences

- **加词仍要选级别。** 一处加词的目标达成了（都在一张表里），但加一个词仍要判断它属于 `scan_excluded` 还是 `default_unchecked`——这是两个真实不同的后果，不是可以抹掉的重复。
- **`SKIP` 的模块级名字消失。** 现有直接引用 `chan.SKIP` 的测试改为指向新位置，不留兼容别名。
- **文档落点。** CLAUDE.md 增加「找渠道怎么判营销/服务/受保护，先看 `channel_policy.classify()`」；`CONTEXT.md` 的「通知」组补五个术语；`AGENTS.md` §5 与 `tool/run.py` 的 `cmd_chan_scan()` 里生成的清单表头本轮不动——它们描述的是人工核对时要删哪些，仍然准确，改它们容易被读成行为变化。
- **已知盲区保留。** 带非空应用名列的「其他」不会被默认不勾；服务类裸词会命中包名或应用名。两条都在对拍语料里显式出现，等单独的行为票。
- **CHANGELOG** 的「## 未发布」一条加在实现那一笔，本 ADR 只落决策。

## 增补：广告网络 ID（#456）

厂商把广告网络名直接编进渠道 ID，渠道名却可能是任意中文（桌面 `TencentAdNetCH1`、`ADroiUnion`）。这类 ID 不进 `KW`，扫描于是漏掉真正该关的渠道。

- **新增** `AD_NETWORK` 词表与 `ad_network_id` 字段。只匹配渠道 ID，大小写不敏感、子串匹配——ID 常带 `CH1`、`_union` 一类前后缀，整段锚定认不出来；词条写得足够长（`adroi` 而不是 `ad`）来控制误报；`adroi` 仍会命中 `adroit` 一类英文词，按低风险误报接受。
- **与 `VIVO_MARKETING` 的区别**：vivo 分类号只越过 `SKIP`，营销关键词仍要命中；广告网络 ID 本身就是营销证据，命中即 `marketing_candidate=True` 并越过 `SKIP`。ID 是厂商固定车道，渠道名不可靠。
- **出口不变**：判定仍只从 `classify()` 出，消费方照旧只读 `marketing_candidate` / `scan_excluded`，不加旁路剔除逻辑。
- **对拍策略**：冻结基线断言保持原样，继续证明其余判定没有漂移；新规则由独立用例钉住，`ad_network_id` 为假时任何判定都与改前一致。
