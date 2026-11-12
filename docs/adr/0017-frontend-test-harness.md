# 前端测试基座用 jsdom + `node --test`，由 Python 回归命令代跑

基线 `d664ece`（#647）。

**手机版那部分已废止**：界面在 #666 改成 Compose，`mobile.js` 随之删除，本文里「注入 `mobile.js`」「手机版完成页出口」等内容只描述当时的基座；手机版的判断改由 `tests/test_android_view.py` 守，见 [ADR-0018](0018-android-compose-ui.md)。桌面版的用法不变。

`gui/web/index.html` 的 JS 全在一个内联 `<script>` 里（约 450 行），手机版 `mobile.js` 是加载即改写
桌面版全局函数的 IIFE。两者在此之前没有任何自动化守护：`tests/` 里对 `index.html` 只有文件存在性
断言，#632 的 `tick()` 门槛与手机版完成页出口只有作者手测。

## Decision

**用例写在 `tests/js/`，用 `node --test`；由一个 Python `TestCase`（`tests/test_web_client.py`）
起子进程代跑，回归仍是一条 `python -m unittest discover -s tests`。**

- DOM 用 jsdom：`new JSDOM(读进来的真实 gui/web/index.html, {runScripts: "dangerously"})`，
  再注入 `mobile.js` 文本、dispatch `pywebviewready`。生产代码一个字节不改。
  （`mobile.js` 已在 #666 删除，注入这一步随之去掉。）
- `package.json` 与 `package-lock.json` 进库，jsdom 版本钉死，CI 用 `npm ci`；`node_modules/` 不入库。
- 两个 CI job 各加 `actions/setup-node`，钉 `22.23.4`，不依赖 runner 镜像自带的那份；这个版本是
  实测过 `--test-force-exit` 且满足 jsdom engines 的那个。
- 假 api 桥按方法名给用例指定的返回值，**没定义的方法调用即记错，用例收尾判红**——代码多调一个
  窗口桥方法要当场暴露。只抛不记不行：页面里不少调用带 `.catch(() => {})`，会把错吞掉。
- 用例文件由 Python 侧展开成显式路径传给 node：Node 22 不把目录当 `--test` 参数，只认文件或 glob。
- 找 node 不到就报错，不跳过；用例文件一个都没跑到也报错（`node --test` 在空集合上返回 0）。

## Considered Options

- **零依赖 `node:vm` + 自制 DOM 桩**：探路时一份几十行的临时桩就能跑起 `index.html`，`tick()` 与
  `summarize()` 都调得到。但 `mobile.js` 覆盖不了——`main().querySelector("h1")` 作用在字符串型 `innerHTML` 上
  恒为 null，`mobile.js` 当场 `TypeError`；把 `querySelector` 改成一概返回新桩能让用例过，但断言
  退化成对另一个桩做字符串匹配，徽标是否真在 `h1` 之前验不了。省下的只有 22M 与一份 lockfile，
  换来一个只覆盖一半却看起来全覆盖的基座。
- **把纯逻辑抽到单独 JS 文件再 import**：牵动三处打包——`gui/bundle_data.py` 的 glob、
  `gui/standalone.py` 的单文件内联、安卓侧 `MainActivity` 读 `filesDir/aac/gui/web/index.html`。
- **并列第二条命令 `node --test`**：仓库所有可复现的计数都挂在一条回归命令上
  （`CODING_STANDARDS.md` 的计数约定、`docs/agents/code-review.md` 的核对方式），破这条要连带改一堆文档。
- **依赖 runner 自带的 node**：版本随镜像漂移，jsdom 对 node 有最低版本要求，属于「某天 CI 突然红」那类。

## Consequences

- 仓库第一次出现 npm 工具链：`package-lock.json` 约 13K 入库，`node_modules` 约 22M 不入库；
  本地与两个 CI job 都需要 node。
- 页面里的 `setInterval` 让事件循环不退出：每个用例收尾必须 `window.close()`，漏了的表现是**挂死**
  而不是报错。`--test-timeout` 只把用例标红、不让进程退出，所以还要 `--test-force-exit`，wrapper
  另有 subprocess 超时。
- jsdom 不拉图片、不算样式，样式层仍无守护；本基座覆盖的是 #632 的两处行为（`tick()` 落点、
  手机版完成页出口）与当时前端自己那份 `summarize()` 的三条摘要分支（那份随 #1189 收进
  `tool/summary.py`，前端如今只渲染后端给的字段）；`mobile.js` 的首页状态机与一键流程不在范围内
  （该文件与这两条用例都已在 #666 移除，手机版改由 `tests/test_android_view.py` 守）。
- 页面结构一变，用例跟着变：用例是行为断言（完成页标题、第 5 步高亮、按钮文案与 onclick），
  不是对 HTML 字符串的逐字比对。
