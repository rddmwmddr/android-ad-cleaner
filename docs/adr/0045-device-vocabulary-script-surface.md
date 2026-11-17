# 设备词汇与脚本面边界：门面补动词、catalog 收 shell

基线 `c9fb8dd7`（spec [#1471](https://github.com/rddmwmddr/android-ad-cleaner/issues/1471) 的集成分支尖端）。九个子票：#1472（门面补动词）、#1473（catalog `start` op 扩展）、#1474（脚本 shell 迁移）、#1475（动作原语归位）、#1476（引擎侧 `p.d` 归零）、#1477（脚本面声明与守卫）、#1478（catalog `am start` 迁移）、#1479（门面收缩）、#1480（本记录）。

## 问题

`Phone` 门面在 [ADR-0033](0033-phone-phase-modules.md) 之后只留转发，但**公开面是「所有内部字段的并集」**，不是一组声明过的名字：20 组属性全部是协作者字段的第二条访问路径，`p.d` 又把读屏 adapter 整个漏到脚本层。三类症状同源——**同一个动作/状态有两条路径，一条有守卫、一条没有**：

- `p.d.click` / `p.d.swipe` / `p.d.press` 是 uiautomator2 的 Device API，`Reader` Protocol 根本没声明它们。`Screen.click` 有屏幕旋转与越界校验、并且故意用 `input swipe x y x y 80` 代替 `input tap`（有的 App 吞 tap）；`p.d.click` 一条都没有。WKL-AN20 因此与引擎走两条不同的点击路径。
- 脚本与 `recipe_lib` 自己拼传输命令（实测 30 处脚本 + 52 处库调用），引擎想换下发方式就得翻 47 份数据。
- catalog 把 `am start` 降级成 `p.d.shell("am start …")`，入口速查再用两条正则从生成出来的源码里把 `am start` 拆回来——这是 [ADR-0034](0034-recipe-source-facts.md) 立命要消灭的「同一批脚本被两套词法解释」。

## Decision

**门面只留「这台手机这个概念」的名字；传输与内部状态归协作者；脚本面是一份声明，守卫按声明扫描。**

### 门面 = 动词 + 8 条设备概念属性

保留（8 个，全部可读写）：`W` / `H`（屏幕宽高，脚本按比例算坐标）、`changed`（本次关掉的页面·标题）、`safe_mode`（只关点名的开关）、`miss` / `missed`（落空计数 / 没拨到的开关）、`lost`（本轮是否已确认断线）、`app`（最近拉起的 App）。

删掉的 12 组内部状态退回协作者：`d` / `reader` / `link` / `log` / `serial` / `pause_at_lock_check` 归 `Connection`，`systemui_text` 归 `Screen`，`vivo_seen` / `skeleton_sigs` / `skeleton_count` / `mismatch_probes` 归 `ChannelSession`，`promoted` 归 `LaunchSession`。引擎与测试改读 `p.conn.*` / `p.screen.*` / `p.channel_session.*` / `p.launch_session.*` / `p.toggler.*` / `p.lost_note.*`。`reader` 只保留构造参数 `Phone(serial, reader=…)`。

判据一句话：**门面上每个名字都要能回答「它是不是这台手机这个概念的一部分」，答不上来就删。**

动作原语（`Screen` 上定义、`Phone` 同名转发）：`shell` / `swipe` / `window_size` / `home` / `back(n=1, settle=True)` / `press` / `app_stop` / `tap_id` / `tap_id_if_present` / `set_text`，加上原有的 `click`（唯一带守卫的坐标点击）与 `scroll`（引擎的翻页手势）。

### 脚本面是一份声明

`tool/phone/surface.py` 的 `SCRIPT_SURFACE` 是唯一来源（8 属性 + 41 动词与查询）。守卫是 AST 静态扫描：`devtools/script_surface.py` 扫 `recipes/**/*.py` 与 `recipe_lib/*.py`，出现声明外的 `p.<名字>` 即红（读、写两种上下文都抓，`p.d(...)` 这种「属性即调用」也抓）；`tests/` 下的假数据不扫。规则 id 是 `dev.phone.script-surface`（`rules.toml`，`status = enforced`），由 `tests/test_phone_facade.py` 的 `ScriptSurfaceTests` 代跑。

脚本面≠门面：`ls` / `close` / `check_alive` / `wait_unlocked` / `home` / `app_stop` 这些是引擎自己或阶段用的，脚本不该碰。新增一个公开名字时要先回答「脚本该不该碰它」，再加进声明。

### catalog 词汇：结构化 op 取代手写命令串

`start` op 扩展了 `action` / `data` / `flags` / `clear_task` / `launcher`（不新增 op 种类），拉起命令的唯一拼装点是 `tool/catalog/launch.py` 的 `launch_command()`；清栈标志 `-f 0x10008000` 不进数据，由引擎默认加。事实层不再从生成源码里回读 `am start`：`_catalog_src` 只交出 `p.start(pkg[, activity][, action=…])`，`entries._scan_entries` 按结构化实参认入口。

## 接管了哪些旧结论

- **取代 [ADR-0033](0033-phone-phase-modules.md) 的「冻结面 / 公开名字一个不改」条款。** 按阶段拆模块的结论不变（两个基座 + 五个阶段 + 薄门面），但「公开面冻结」这条到此为止：它把「所有内部字段的并集」固化成了对外契约，正是本病的来源。ADR-0033 的正文保留当时的取舍与代价叙述。
- **[ADR-0020](0020-no-read-write-split.md) 的结论不变**（不按读 / 写切 `Reader`），但门面不再暴露 `reader`；本 ADR 只把传输收进门面动词，不重新划读写边界。
- [ADR-0034](0034-recipe-source-facts.md) 的「一份 AST 层给事实」不变；本 ADR 让 catalog 数据的 `am start` 形状由结构化 op 提供，不再需要从生成源码里二次解析。
- **[ADR-0002](0002-phone-state-interface.md) 的 `Phone.reader` 命名与 `Phone.d` 写穿别名到此退场。** 它当年选「只命名、不收窄」，让读屏 adapter 在门面上有个名字；现在名字的实体留在 `Connection`（`p.conn.reader`），脚本经门面动词做事，门面不再转发 adapter 本身。ADR-0002 的正文保留当时的取舍。

## 四条实测得来的取舍

这四条都是「先按票面的设想写，被实测推翻后改的」，后来者最容易再次踩进去，所以逐条记：

1. **`press` 不是 `home` / `back`。** uiautomator2 的 `Device.press(key)` 走 `jsonrpc.pressKey`（UiAutomator 注入），与 `shell("input keyevent HOME")` 不是同一条下发路径。所以脚本里 7 处 `p.d.press("home" | "back")` 搬成 `Phone.press`（内部仍走 u2），**不是** `home()` / `back(settle=False)`——后者会换通道，与「换原语不改变下发路径」冲突，也会把真机复测范围从一台扩到四台。
2. **`Phone.swipe` 与 `Screen.scroll` 不等价。** `scroll` 是引擎的「按下-移动-停-松开」翻页手势；脚本的绝对坐标手势走 u2swipe。两条比例相同、下发路径不同，换过去真机行为不一致（WKL-AN20 的桌面下滑）。
3. **`Phone.shell` 返回 `ShellResult`（str 子类，另挂 `exit_code`）。** 输出按字符串用（探型号、读 dumpsys），但拉起 App 那几处要判 `am start` 成没成功；做成 str 子类就不必为退出码再开一个动词，`.output` 也仍可读。
4. **catalog 的 raw `shell` 最终停在 8 条，不是 2 条。** 票面设想只剩 2 条 `input tap`，实测有三族不能迁：`input tap` 2 条（该版日历对 uiautomator 点击不响应）、`input keyevent` 3 条（`press` op 走 `jsonrpc.pressKey`，与 `input keyevent` 非同一下发通道）、`input swipe` 3 条（录脚本时写死的绝对坐标，换成按屏比现算的 `gesture` 会在真机上换像素）。八条都在数据里写明理由。

另有一条不是取舍而是事实：`entries.py` 的 `_AM_PAGE` / `_AM_INTENT` 两条正则**保留**。它们不只读 catalog 生成的源码，还读手写 `.py` 例外脚本与 `recipe_lib/*.py` 实现里的 `am start` 字符串（实测打死后 `used_by()` 从 57 行 / 192 个机型归属掉到 44 行 / 153）。本 ADR 的目标由「catalog 数据不再依赖它们」达成，并有用例把两条正则打成永不匹配、断言 catalog 派生的入口不变。

## Considered Options

- **只在脚本里把 `p.d` 换成门面方法，不动门面属性。** 否决：留下 12 条同构的第二访问路径，修的是症状；半年后同类泄漏会长回来。
- **把 `W` / `H` / `changed` 也删掉，让脚本读 `p.toggler.changed`。** 否决：那会把脚本推向内部对象图，用一种泄漏换另一种。
- **按读 / 写拆 `Reader`。** 否决，沿用 ADR-0020：本票要的是「传输只有一处出口」，不是重新划通道边界。
- **给脚本面也做运行时白名单（属性拦截）。** 否决：静态 AST 扫描在提交时就能红，运行时拦截只会在真机上炸。

## Consequences

- 门面 `Phone` 的 `def` 从 107 降到 83（12 组 × 2 个属性方法退场）；脚本侧 `p.d` 归零，「这台手机怎么做」只剩一套词汇。
- 新增公开名字变贵了：要么进 `SCRIPT_SURFACE`（要回答「是不是设备概念」），要么明确只给引擎用。守卫会把「偷偷挂回门面」变成提交时就红的失败。
- 引擎改下发方式只有一处：`Screen` 的动作原语与 `Connection` 的传输。catalog 数据的命令形状由 `launch_command()` 一家拼装。
- `tests/snapshots/recipe_calls/` 的记录点挪到传输边界（`conn.reader.shell`，名字统一 `shell`），一条命令一行；迁移前后的差异只有方法名替换与新增的门面动作行，没有命令串 / 段名 / 顺序变化。
- 真机复测范围：只有 WKL-AN20 的点击路径替换（`p.d.click` → 带守卫的 `Screen.click`，下发从 u2 click 换成 `input swipe x y x y 80`）。
- 未做：不拆 `Reader` 的读写；不动 `gui/` 与手机版界面；不扩页面树、家族策略、库词汇；不把 `code =` 反委的那批 `.py` 例外迁给 catalog。
