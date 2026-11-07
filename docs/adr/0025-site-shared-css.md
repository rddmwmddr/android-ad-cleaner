# 官网两页的共享样式收进 `site.css`，由生成器渲染进页面，页面仍是单文件

基线 `0d30e19`。前置是 #643 的教程页：它把首页的调色板、深色媒体查询、顶栏与页脚整段复制了过去，加手机顶栏入口时已经分叉——版心 `--gutter` 首页 20px / 教程页 16px，栏高 64 / 60，顶栏 gap 28 / 20。改主题或改顶栏要动两处，漏一处就是两页不一致（#653）。

## Decision

**单一来源是仓库根的 `site.css`；`tool/gen_site_css.py` 把它渲染进两页 `<style>` 的 `site-css` 标记区。页面不引用外部样式表。**

- 共享内容：调色板与深色档（`@media (prefers-color-scheme: dark)` 与 `:root[data-theme="dark"]` 两条）、基础重置、顶栏、页脚。
- 两页在共享样式上的差异值不消除，集中到 `site.css` 顶部的 `:root.reading` 一条（页面专属样式仍各自持有）：教程页 `<html class="reading">`，版心 16px、栏高 60、gap 20、顶栏底边 0。验收要求两页与改前逐像素一致，所以分叉保留、只收拢到一处；改结构（顶栏、页脚、调色板）只需改 `site.css` 一个文件。
- 页面专属样式（`.shots` / `.toc` / `.table` / `.cards` / `.sw` / `.board` / 各 `@media` 断点）留在各自 `<style>` 里，不进 `site.css`。
- `body::before`（安全区顶条）原来是首页独有，现在两页都有：`env()` 为 0 时高度为 0，不产生像素；带安全区的全屏形态下教程页会多一条与首页相同的 `--paper` 顶条，对拍只在 `env()` 为 0 的桌面形态下做过。

## Considered Options

- **同目录一份 `site.css` + `<link rel="stylesheet">`**（否）。机主服务器上的官网副本是单文件（`ahuamiao.com/sites/other/*.html`），`gui/standalone.py` 也只把图片内联进 `index.html`；外链样式表在这两处都取不到，而发版同步是人工步骤，漏传一个文件的表现是整站没有样式。仓库已有的单文件渲染路径（ADR-0017 列的三处目标）也都不支持外链。
- **构建期合并后提交产物**（采纳，就是本方案）。渲染进标记区等价于此，且不需要额外的产物目录：仓库里的 html 本身就是产物。
- **把分叉也统一成一套值**（否）。会改两页的版心、栏高与页脚链接下划线，直接违背「与改前逐像素一致」的验收。
- **生成器渲染整段 `<style>`**（否）。页面专属样式会跟着搬进 `site.css`，两页的断点与组件各不相同，合起来比现在更难读。只渲染标记区，其余一字不动，与 #654 的品牌连点表同形。

## Consequences

- 改 `site.css` 之后要跑一次 `python tool/gen_site_css.py`。`tests/test_doc_consistency.py` 的 `SiteCssTests` 抓四件事：两页标记区与 `site.css` 逐字一致（漏跑即红）、标记区恰好一对、教程页带着 `class="reading"`、两页都没引外部样式表。
- 页面产物形态不变：GitHub Pages、`gui/standalone.py` 的单文件导出、机主服务器上的副本都不需要多带一个文件。
- 改前改后对拍：两页逐元素比计算样式（390 / 1280 各一次），布局内容高逐值相同，差异只有下面这几处有意统一的行为。截图对拍 390 / 1280 × 浅色 / 深色，首页四组全等；教程页只有 `<video>` 原生控制条的时长文字在抖（同一文件重跑也抖），隐去视频元素后四组全等。关掉 JS 后两页仍与改前逐像素一致。
- 有意统一的行为（都不改布局）：`-webkit-text-size-adjust: 100%`、`-webkit-tap-highlight-color: transparent`、`.brand` 与 `.nav a` 的 `white-space: nowrap`、`.nav a` 的 `touch-action: manipulation`、hover 改到 `(hover: hover) and (pointer: fine)` 下、`img` 加 `display: block`。
- `--shadow` 进了共享 `:root`，但首页 `.board` 仍写字面量阴影：两页深色档的阴影本来就不同，改成变量会改首页深色渲染，不在本票范围。
