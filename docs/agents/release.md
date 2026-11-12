# 发版

面向用户的更新说明（Release Note）就放在 GitHub Release 的正文里，repo 内不留副本。这份文件写两件事：正文从什么原料、按什么格式生成，以及一轮发版里各产物的顺序。

术语见 [CONTEXT.md](../../CONTEXT.md) 的「文档」组。发版**之后**要催的复测在 [release-followup.md](release-followup.md)，不在这里。

## 两个阶段

一轮发版分成两段，中间隔着不确定的时间：

| 阶段 | 谁 | 结束条件 |
| --- | --- | --- |
| 出包点 | 维护者 | 收口提交合入 main，`v<x.y.z>` tag 推上去 |
| 发版动作 | owner | Release 公开，下载页、Gitee 与 `latest.json` 同步完 |

tag 钉在出包点选定的那个提交上，之后 main 照常合入新的 PR，发版不受影响。反过来，没进 tag 的改动也不算这一版；进了 tag 的提交不要再改写（rebase、force-push），否则产物与源码对不上。 <!-- rule:doc.release.outpack-then-release -->

## 两个落点，两个读者

| 落点 | 读者 | 写法 |
| --- | --- | --- |
| `CHANGELOG.md` | 维护者、本仓库 agent | 一条一行、≤ 80 字、按 `新增 / 修复 / 内部` 分类、挂 PR 号 |
| GitHub Release 正文 | 用户 | 按「用户会遇到什么」组织：现象 → 现在会怎样。不写函数名、内部类名、基线 SHA；回归项数只写一次，写在「其他」里 |

同一笔改动两边都写，但不是同一段话。CHANGELOG 说改了什么，Release Note 说用户感受得到什么。 <!-- rule:doc.release.two-readers -->

## 正文的原料

```bash
# 上一次发版之后合进 main 的 PR
LAST=$(gh release view --json publishedAt -q .publishedAt)
gh pr list --state merged --search "merged:>=$LAST" --json number,title,body

# 这一版的维护者记录
sed -n '/^## 未发布/,/^## /p' CHANGELOG.md
```

两边对上之后，按「用户会不会遇到」筛：引擎内部的改动归到「其他」里的一句话，用户可见的修复逐条进表。PR 正文里的「为什么」正是 Release Note 需要的语言，可以直接改写成现象。 <!-- rule:doc.release.note-sources -->

## 正文的格式

格式锚是 [v0.3.0 的正文](https://github.com/rddmwmddr/android-ad-cleaner/releases/tag/v0.3.0)：

```markdown
<一句话：这一版修了什么、新增什么。纯重构写「引擎里……重写，用起来不变」。>

### 修复

| 现象 | <版本> |
|---|---|
| <用户看到的症状>（#issue） | <现在会怎样> |

### 新机型脚本

<型号逐项列出；写明由贡献者在自己手机上录制、本仓库没有该机型。>

### 其他

- 引擎重构一句话带过。
- 验证：N 项设备无关回归通过；模拟器 / 真机验证了哪几项；没在真机上跑的部分写清最多验到哪一步——在模拟器上看过、只有用例覆盖、还是完全没跑过。
- 0.4.1 及以前需先手动安装首个带应用内升级的版本；之后可在 App 内检查、下载并安装更新，Android 仍需系统确认。Windows 安装程序暂未签名。附 `SHA256SUMS.txt`。

感谢 <本期贡献者>。

[完整更新记录](https://github.com/rddmwmddr/android-ad-cleaner/blob/main/CHANGELOG.md) · [官网](https://ahuamiao.com/sites/other/android-ad-removal-intro.html)
```

写正文时的三条硬约束：

- 症状写用户原话能对上的那句（「关快应用后快递卡片打不开」），不写实现原因（「平台包被挂起」）。 <!-- rule:doc.release.symptom-in-user-words -->
- 「没有真机复测」不许省略成「已验证」，也不许写成「应该没问题」；没验的部分要说清最多验到哪一步——在模拟器上看过、只有用例覆盖、还是完全没跑过——不写这几层的计数或百分比。 <!-- rule:doc.release.never-omit-unverified -->
- 不写用例数以外的任何数字。正文的验证行与 CHANGELOG 那一行必须是**同一次** `discover` 的输出：用例数只写一次，放在「其他」的验证一行里，不写拼接或推算出来的复合计数；两版解释器结论不一致时，以 3.12 的发版构建为准。 <!-- rule:doc.release.count-regression-once -->

### 致谢谁

名单从 PR 作者取，不凭印象： <!-- rule:doc.release.credits-from-authors -->

```bash
LAST=$(gh release view --json publishedAt -q .publishedAt)
REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)
gh search prs --repo "$REPO" --merged --merged-at ">=$LAST" --json author,authorAssociation \
  --jq '.[] | select(.authorAssociation | IN("OWNER", "MEMBER", "COLLABORATOR") | not) | .author.login' | sort -u
gh search prs --repo "$REPO" --closed ">=$LAST" is:unmerged --json author,authorAssociation \
  --jq '.[] | select(.authorAssociation | IN("OWNER", "MEMBER", "COLLABORATOR") | not) | .author.login' | sort -u
```

- 合并的 PR 与「分析被采纳、本仓库重新实现后关闭」的 PR 都算：前者交了代码，后者交了分析。
- 去掉 `OWNER` / `MEMBER` / `COLLABORATOR`；同一个人只写一次。
- 写 GitHub 用户名（`@handle`），不用「提交机型脚本和报告问题的朋友」这类笼统说法；机型脚本作者照旧逐人列出。

GitHub 搜索索引有延迟，刚合上没几小时的 PR 可能还查不到；对着本版 PR 列表手工补一遍。 <!-- rule:doc.release.search-index-lag -->

## 手机版 APK

手机版随桌面版一起发布，产物是 arm64 APK（`android/build.sh assembleRelease`）。签名与分发由 owner 掌握：构建读 `.private/android-signing/keystore.properties`（见 `android/app/build.gradle.kts`），缺失就退回 debug 签名。这一节只记口径，不写实际操作步骤；本机没有这份证书，签名与分发路径未验证。 <!-- rule:doc.release.apk-ships-with-desktop -->

`android/**` 的改动由 `.github/workflows/android.yml` 在 PR 上跑 `assembleDebug` 编译闸门与协议层 JVM 单测，不产出发版产物。 <!-- rule:doc.release.android-ci-gate -->

APK 由 owner 在 tag 的源码上构建并传到同一个 Release（发版动作第 3 步）。`gui/upload_gitee.py` 按 Release 里的文件现算清单，APK 在 Release 里就一并传到 Gitee，所以那一版多传一个包。当次 Release 里已有 APK 时，README 下载区与 `docs/手机版教程/README.md` 的「下载」一节一并更新链接；没有就维持「随下一版发布」。 <!-- rule:doc.release.apk-link-sync -->

## 出包点（维护者）

打完 tag 就退出，不碰 Release。四步都在 `git worktree add` 出来的目录里做：主副本的当前分支随时被别的会话切走。

0. **核对产品契约**：`git diff <上一版 tag>..<本次要打的提交> -- AGENTS.md`，§1 有没有变化——既看 `<!-- rule:product.* -->` 锚点集合，也看正文措辞和条数；实现侧动了挂包拒绝名单（`run.py` 的 `NEVER`）、极性词表（`polarity.NEG_PREFIX`）或 `off()` 的走向，同样算触碰。有变化就记下来交给 owner，写进 Release 正文的「其他」，说明用户侧 agent 以后该怎么做。放在最前面，因为它决定正文怎么写。 <!-- rule:doc.release.product-contract-check -->
1. **跑验证**：`python -m unittest discover -s tests`（本机 `.venv`，3.13，与 Linux job 同一版）一套，加 `uvx ruff@0.17.3 check tool tests gui android/app/src/main/python android/smoke.py`，再加 `.venv/bin/pip install mypy==1.18.2 && .venv/bin/mypy`（引擎目录的类型检查，范围与宽松档在 `pyproject.toml`）。这里只跑这一次，数字怎么落到正文与 CHANGELOG，按「正文的格式」里那条用例数的约束办。两个安装包都是 3.12 产物，发版动作第 2 步那次构建会在 3.12 上再跑一遍套件（Windows 平台，POSIX-only 用例会 skip）。
2. **收口**：确认这一版的每一笔都在 `## 未发布` 里、都是一行一条；把 `gui/app.py` 的 `VERSION` 改成新版本号（Windows 包名与 `gui/version.py` 都读它）；把 `## 未发布` 改名为 `## <版本> · <日期>`，在标题下补一行验证（回归项数 + 验证了什么 + 缺什么），再重开一个空的 `## 未发布`。回归项数写第 1 步 `discover` 的输出，不记基线 SHA——那个 tag 上重跑一遍就能得到同一个数。提 PR 合入 main。
3. **打 tag**：`git tag -a v<x.y.z> <收口提交的 SHA> -m "<版本>"`，再 `git push origin v<x.y.z>`。显式给 SHA 而不是 `HEAD`：主副本的当前分支随时被别的会话切走，`HEAD` 不一定是刚收口的那一笔。推完把版本号与 tag 名交给 owner。

收口放在打 tag 之前：验证行里的数是打 tag 那一刻跑出来的，tag 之后这个提交不能再改。 <!-- rule:doc.release.changelog-close-before-tag -->

## 发版动作（owner）

全部按 tag 做：构建、打包、上传都取 tag 指向的提交，不看 main 当时的样子。

1. **建 Release 草稿**：tag 已经存在，在 GitHub 上基于它建草稿。
2. **触发 Windows 构建**：Actions → build-windows → Run workflow，tag 填 `v<x.y.z>`。它先校验 `gui/app.py` 的版本号与 tag 一致、tag 在 main 历史里，然后在 tag 上打包两个 Windows 安装包、跑冒烟测试、把产物传进草稿。草稿还没建时它只出 artifact、不报错；草稿已公开时保留已验证的文件、不重建。
3. **上传 macOS 安装包与 APK** 到同一个草稿。DMG 在本机打包与公证（步骤在 `CLAUDE.local.md`）；APK 用 `android/build.sh assembleRelease` 在 tag 的源码上构建。两者都必须从 tag 出包。
4. **写正文并发布**。正文可以在草稿阶段写好。校验清单从 Release 的资产摘要生成，顺序与下载卡片一致：先跑 `python3 tool/release_meta.py sums v<x.y.z>`，在当刻目录写出 `SHA256SUMS.txt`，确认里面就是这一版发出去的五个包；再加 `--upload` 把它传进草稿、回读核对摘要，草稿阶段可反复覆盖，Release 已公开后工具拒绝上传；某个资产还没算出摘要时改加 `--from-files <安装包所在目录>`，摘要从本地文件重算。发布前拿这份清单核对每个安装包（含 APK）的 SHA256（漏掉哪个包，`baidu_rows.py --legacy` 生成安装说明时会直接报错，不会写出空校验值），并按「致谢谁」核对待致谢名单。 <!-- rule:doc.release.sha-and-credits-before-publish -->
5. **同步用户侧文本**：
   - `README.md` 的版本摘要：首段从 Release 正文首段复制，后面接旧版升级方法（0.4.1 及以前仍需先手动覆盖安装）；下载表格换版本号与链接。
   - `index.html` 的下载页数据：先跑 `python3 tool/release_meta.py page v<x.y.z>` 判能不能回填（只校验，不写盘），通过后加 `--write` 回填 `REL.version`、`REL.github` 前缀里的版本段、五条卡片的 `file` / `size` / `sha` 与 `RELEASED` 日期，并把 `index.html` 与 `android-tutorial.html` 图标地址的 `?v=` 一并换成这一版（缓存键要与 `REL.version` 一致，任一页读不到就整份不写）；卡片文案与 `REL.gitee` 它不动。第 7 步换 `REL.gitee` 用同一条命令加 `--write --gitee`（单加 `--gitee` 不写盘）；国内走百度网盘、要把 `REL.gitee` 留空时跳过这一步。APK 条目的 `id` 逐字写 `android`：卡片角标、手机端高亮和 `baidu_rows.py` 生成的安装说明都靠它，没有这一条，线上就看不到手机版。 <!-- rule:doc.release.apk-id-android -->
     写完跑 `python3 tool/release_assets.py v<x.y.z> --sha` 对账页面与 Release 资产：文件名、大小与 sha 三类逐条比（与每周一那条 job 同一条命令；不带 tag 时取页面 `REL.version`），不一致先查清再往下走。
6. **同步官网副本**：放在机主服务器上的页面副本（步骤在本机 `CLAUDE.local.md`）。版本清单等下一步国内附件校验完成后再发布。
7. **国内下载**：`python3 gui/upload_gitee.py <版本>`，从公开的 Release 下载安装包、核对 SHA256，推代码和标签到 Gitee、建发行版传附件，再匿名下载回来核对。Windows 安装版被 Gitee 拒收，不上传，下载页上它标 `gitee: false`，只给 GitHub 按钮。`index.html` 的 `REL.gitee` 换成这一版的路径。百度网盘暂停使用，页面上不显示；Gitee 不可用时把 `REL.gitee` 留空，改跑 `gui/upload_baidu.sh <版本>`，它会回写网盘链接、按钮随之恢复，但 `#dl-lead` 那句文案是手写的，要把「国内下载走 Gitee，不用登录」改回「国内下载走百度网盘，链接里带提取码」，后半句「安装版会原地替换旧版，原来的备份保留；免安装版不会」原样留着。国内走 Gitee 时 Windows 访客只拿得到免安装版，它不替换、也不卸载已安装的旧版：发版正文的 Windows 侧要像 0.4.0 对 Mac 那样写明这一句，并给出两条出路（用安装版覆盖安装，或先卸载旧的「安卓去广告」，数据与备份保留）。下载页、`README`、`docs/08` 与 `gui/upload_gitee.py` 生成的 Gitee 发行版正文各自只覆盖自己那一处，不能因为页面已经写了就在发版正文里省掉。免安装版启动时也会在界面里提示一次（#872），但那只在用户已经遇到并存时出现，同样不能替代正文那一句。 <!-- rule:doc.release.gitee-portable-wording -->
   应用内更新使用 APK、两份 DMG 和 Windows 便携 ZIP。附件回下载校验通过后，运行 `python3 gui/update_manifest.py <版本> /tmp/android-ad-cleaner-latest.json`，将生成文件发布到官网同名地址并 GET 回读核对。它保留旧客户端读取的 `version`，并附四个平台的大小、SHA256 和双渠道地址；不要再手写只有版本号的 JSON，也不要在 Gitee 附件未就绪时推送新清单。Gitee 暂不可用时保留上一份完整清单，让用户先走官网手动下载。
8. **催复测**：先跑 `python3 tool/followup.py --write`，把 [release-followup.md](release-followup.md) 的队列与 `waiting-for-verify` 标签补到一致（缺行补成骨架行，机型 / 版本 / 要观察的输出现场填；仍报差异的按提示补登记或摘标），再按表逐条发给报告者。

## tag 出问题怎么办

Release 建起来之前发现 tag 打错，删掉远端 tag 重打即可：`git push origin :v<x.y.z>` 之后再按出包点第 3 步补一个。workflow 只由手动触发，删 tag 不会引发构建。Release 一旦建起来就不要再动 tag——附件、`SHA256SUMS.txt` 与 `latest.json` 都已按那个提交生成，改 tag 只会让它们与源码对不上，留到下一个 patch 版修正。
