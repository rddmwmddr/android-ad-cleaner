# 设置入口的判据归引擎的 `row.icon_hit()`：只认「恰好是设置」，怎么点留给脚本

基线 `01c7e46`。

各机型脚本点设置齿轮的入口各写各的。小米 / 红米有 13 个脚本文件复制了同一份内嵌 `icon_hit`
（#305 引入：描述或正文恰好是「设置」/「settings」/「setting」，或 resource-id 末段是 setting
词）；vivo 参考脚本的 `gear()` 是另一套，把 `content-desc` 与 `resource-id` 拼起来做子串匹配，
且只认 `clickable="true"` 的节点。

两套判据在 #530 上撞出问题。vivo 应用商店底栏标签读作「我的, 2个应用待更新,第5个, 共5个」，
参考脚本的精确匹配读不到，`--ref` 模式商店段空转到超时；同一份脚本的 `gear()` 又会把 id 里带
setting 的其它入口当成齿轮先点掉。

## Decision

**引擎在 `tool/row.py` 新增纯函数 `icon_hit(node) -> bool`，判据与小米脚本已有的内嵌版逐字相同。**

- 位置：与 `bounds()` 同级。两者都是按节点判读的纯函数，不碰读屏、不碰点击、不依赖 `Phone` 状态。
- 判据：content-desc 或 text 恰好是「设置」/「settings」/「setting」；或 resource-id 末段以
  `setting` 开头、或含 `_setting`。子串匹配不算——`securitySettingSwitchLayout` 的 setting
  前面粘着 security，那是应用安全检测入口。
- 尺寸启发式（小尺寸 `ImageView` 即使没勾 `clickable` 也算入口）不进谓词，留在调用方：它要屏宽 / 屏高。
- 机型脚本从 `fast` 取这一份（`fast.py` 显式 re-export）；直接 `from row import icon_hit` 也是同一个函数。

## Considered Options

- **每个脚本各留一份**（现状）vs **收进引擎**。前者是 13 份逐字相同的副本，改判据要改 13 处，
  且已经出现过小米侧改紧、vivo 侧没跟上的情况。
- **放 `row.py`**（采纳）vs **放 `fast.py` 模块级**。`row.py` 已经是节点判读的集中地
  （`bounds` / `line` / `title_of` / `control`），谓词放这里与它们同类。
- **显式 re-export（`from row import icon_hit as icon_hit`）**（采纳）vs `# noqa: F401`。前者表达
  「这是给脚本的入口」，ruff 也认。

## Consequences

- 13 份小米 / 红米脚本的 `gear()` 删掉内嵌副本，改 `from fast import bounds, icon_hit`。行为逐字不变：
  `tests/test_gear_match_305.py` 不改预期通过。
- vivo 参考脚本（`recipes/vivo-V2547DA/` 两份）的 `gear()` 改用引擎判据。这是**行为变化，不是搬家**：
  从子串匹配收窄到精确匹配，并按小米的形态补上「不可点的小尺寸 `ImageView` 也算」这条。
  齿轮的 content-desc 若不是恰好「设置」，新实现会漏；**没有真机，这一点未验**（#530）。
- 两份 vivo 脚本的商店段把 `p.tap("我的", exact=True, scrolls=0)` 换成 `Phone.tab("我的")`，
  并按 #386 的约定校验返回值（`if not p.tab(...): raise`）。这推翻了 ADR-0012 里「其余十八处裸
  `p.tap("我的", exact=True)` 不动，vivo 上 exact 本来就能命中」这句的一半（见该文件已订正的条目）。
- 没有真机可验。验收是单元回归：谓词的真 / 反例、13 份脚本行为不变、vivo `gear()` 在说明行两种
  先后下都只点齿轮，以及商店段确实改成 `p.tab`。真机复测归 #530 的 `waiting-for-verify`。
