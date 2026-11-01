# 发版

面向用户的更新说明（Release Note）就放在 GitHub Release 的正文里，repo 内不留副本。这份文件写两件事：正文从什么原料、按什么格式生成，以及一轮发版里各产物的顺序。

术语见 [CONTEXT.md](../../CONTEXT.md) 的「文档」组。发版**之后**要催的复测在 [release-followup.md](release-followup.md)，不在这里。

## 两个落点，两个读者

| 落点 | 读者 | 写法 |
| --- | --- | --- |
| `CHANGELOG.md` | 维护者、本仓库 agent | 一条一行、≤ 80 字、按 `新增 / 修复 / 内部` 分类、挂 PR 号 |
| GitHub Release 正文 | 用户 | 按「用户会遇到什么」组织：现象 → 现在会怎样。不写函数名、内部类名、测试数、基线 SHA |

同一笔改动两边都写，但不是同一段话。CHANGELOG 说改了什么，Release Note 说用户感受得到什么。

## 正文的原料

```bash
# 上一次发版之后合进 main 的 PR
LAST=$(gh release view --json publishedAt -q .publishedAt)
gh pr list --state merged --search "merged:>=$LAST" --json number,title,body

# 这一版的维护者记录
sed -n '/^## 未发布/,/^## /p' CHANGELOG.md
```

两边对上之后，按「用户会不会遇到」筛：引擎内部的改动归到「其他」里的一句话，用户可见的修复逐条进表。PR 正文里的「为什么」正是 Release Note 需要的语言，可以直接改写成现象。

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
- 验证：N 项设备无关回归通过；模拟器 / 真机验证了哪几项；**没有真机复测**就直说。
- 旧版不会自动更新：0.2.7 起的客户端左下角会提示新版。Windows 安装程序暂未签名。附 `SHA256SUMS.txt`。

感谢 <本期贡献者>。

[完整更新记录](https://github.com/rddmwmddr/android-ad-cleaner/blob/main/CHANGELOG.md) · [官网](https://ahuamiao.com/sites/other/android-ad-removal-intro.html)
```

写正文时的三条硬约束：

- 症状写用户原话能对上的那句（「关快应用后快递卡片打不开」），不写实现原因（「平台包被挂起」）。
- 「没有真机复测」不许省略成「已验证」，也不许写成「应该没问题」。
- 不写用例数以外的任何数字；用例数只写一次，放在「其他」的验证一行里。

## 一轮发版的产物顺序

1. **跑验证**：`python -m unittest discover -s tests`（本机 `.venv`）与 `uv run --python 3.12 --with-requirements requirements.txt python -m unittest discover -s tests` 各一套，加 `uvx ruff@0.17.3 check --select F,E9 tool tests gui`。这一步的数字就是正文验证行与 CHANGELOG 那一行的来源，只跑一次。
2. **补齐 `## 未发布`**：确认这一版的每一笔都在里面、都是一行一条。这时还没写验证行。
3. **建 Release 草稿并推 tag**：`build-windows.yml` 由 `v*` 标签触发，要求对应 Release **先存在**（草稿即可，否则 workflow 报「请先创建对应的 Release 草稿」）。它打包两个 Windows 安装包、跑冒烟测试、把产物传进草稿。草稿已公开时它保留已验证的文件、不重建。
4. **上传 macOS 安装包**到同一个草稿（本机打包与公证步骤在 `CLAUDE.local.md`）。
5. **写正文并发布**。正文可以在草稿阶段写好；发布前核对四个安装包的 SHA256 与 `SHA256SUMS.txt` 一致。
6. **同步用户侧文本**：
   - `README.md` 的版本摘要：首段从 Release 正文首段复制，后面接「旧版不会自动更新……」；下载表格换版本号与链接。
   - `index.html` 的 `REL`（`version` / `github` / `files[].file` / `size` / `sha`）与 `RELEASED` 日期。
7. **同步版本提示**：官网的 `android-ad-cleaner-latest.json`，以及放在机主服务器上的官网副本（两处的步骤在本机 `CLAUDE.local.md`）。
8. **网盘**：`gui/upload_baidu.sh <版本>`，从公开的 Release 下载安装包、核对 SHA256、上传并回写 `index.html` 的网盘链接。
9. **CHANGELOG 收口**：把 `## 未发布` 改名为 `## <版本> · <日期>`，在标题下补一行验证（回归项数 + 验证了什么 + 缺什么），再重开一个空的 `## 未发布`。
10. **催复测**：按 [release-followup.md](release-followup.md) 逐条发给 `waiting-for-verify` 的报告者。

第 9 步放在最后：验证行里是发版那一刻跑出来的数，提前写会随 rebase 失效。
