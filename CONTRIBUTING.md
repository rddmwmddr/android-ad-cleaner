# 贡献指南

面向人类贡献者。本文件只指路，不复述规则：每条规矩的正文只有一处，按指针去读。

用户侧的 AI 执行手册是 [AGENTS.md](AGENTS.md)——那是给手机端 agent 的操作说明，不描述如何维护本仓库。

## 五步流程

1. **开票**：先有 GitHub issue 再动手，分支名带票号；票怎么认领、怎么关见 [issue-tracker](docs/agents/issue-tracker.md) 的「票的生命周期」。
2. **分支**：`git checkout -b feat/<描述>-<票号>`。
3. **提交**：主题用 Conventional Commits，并带上 DCO 签署（见「提交规矩」）。
4. **回归**：本地跑一遍全量用例与静态检查（见「验证」）。
5. **提 PR**：写清改了什么、怎么验的；审查口径见 [CODING_STANDARDS.md](CODING_STANDARDS.md)。

## 环境准备

Python 解释器按仓库根的 `.python-version` 取（3.13），然后：

```bash
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt
npm ci
```

`npm ci` 只服务前端用例，第一次跑测试前装一次即可。

## 提交规矩

主题的格式：

```bash
git commit -m "fix(chan_fast): keep the channel page open when a row vanishes"
```

DCO 签署（实际提交用这条）：

```bash
git commit -s -m "fix(chan_fast): keep the channel page open when a row vanishes"
```

允许的 type 与格式细则见 [CLAUDE.md](CLAUDE.md) 的「开发」一节。CI 会查这两项，本地也能复现。

## 两类 PR 的分岔

- **机型 / 清单类**：改动主要是机型脚本与清单数据。合并前要过的三查见 [issue-tracker](docs/agents/issue-tracker.md) 的「Pull requests as a triage surface」。
- **核心行为类**：碰引擎、客户端或架构。这类不整单合并，按本仓库的模型重写；采纳口径见 [docs/09](docs/09-社区问题处理.md) 的「相关 PR 的采用范围」。

## 验证

```bash
.venv/bin/python -m unittest discover -s tests
uvx ruff@0.17.3 check --select F,E9 tool tests gui android/app/src/main/python
```

第一条跑全量回归，第二条是仓库的静态检查。口径、解释器版本与为什么钉这个 ruff 版本，见 [CLAUDE.md](CLAUDE.md) 的「开发」一节。

## 维护者处理外部 PR

1. 拉分支：`gh pr checkout <PR 号>`。
2. 跑一遍回归，确认改动可复现。
3. 记录实际改了什么，与作者描述不一致的地方标出来。
4. 推回原分支：小修直接补提交；核心行为类按上面的分岔重写。
5. 合并说明里写清采纳范围：全单合并、部分采纳，还是重写。

## 规则在哪

| 想知道什么 | 看哪里 |
|---|---|
| 维护指令、执行口径 | [CLAUDE.md](CLAUDE.md) |
| 审查判据 | [CODING_STANDARDS.md](CODING_STANDARDS.md) |
| 流程（票、标签、发版、审查） | [docs/agents/](docs/agents/) |
| 术语表 | [CONTEXT.md](CONTEXT.md) |
| 用户侧 AI 的操作手册 | [AGENTS.md](AGENTS.md) |
