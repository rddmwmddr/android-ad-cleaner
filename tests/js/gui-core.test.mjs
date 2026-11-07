/* gui/web/index.html 与 core.js 的纯逻辑面（#647）。跑法：node --test tests/js/ */
import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const GuiCore = require("../../gui/web/core.js");

describe("GuiCore.shouldFinish（tick 的完成页分支，#632/#647）", () => {
  it("停止时即使 results 为空也进完成页", () => {
    assert.equal(GuiCore.shouldFinish({ running: false, results: [], cancel: true }), true);
  });

  it("跑完且有结果时进完成页", () => {
    assert.equal(GuiCore.shouldFinish({ running: false, results: [{ rc: 0 }], cancel: false }), true);
  });

  it("还在跑时不进", () => {
    assert.equal(GuiCore.shouldFinish({ running: true, results: [], cancel: false }), false);
  });

  it("没跑也没停、又没有结果时不进（防抖动的空轮询）", () => {
    assert.equal(GuiCore.shouldFinish({ running: false, results: [], cancel: false }), false);
    assert.equal(GuiCore.shouldFinish({ running: false, cancel: false }), false);
  });
});

describe("GuiCore.summarize（完成页一句话总结，#647）", () => {
  const one = (...tail) => ({ tail });

  it("机型脚本落点", () => {
    assert.equal(GuiCore.summarize(one("机型脚本跑完：关了 12 个，41 秒")), "关了 12 个开关");
  });

  it("渠道落点带仍开着计数", () => {
    assert.equal(GuiCore.summarize(one("拨了 5 个", "仍开着: 2 个")), "关了 5 个渠道，复查仍开着 2 个");
    assert.equal(GuiCore.summarize(one("拨了 5 个")), "关了 5 个渠道");
  });

  it("快应用落点数已关闭行", () => {
    const tail = [
      "快应用组件已关闭（保留项除外）。请按常用入口核对效果；恢复：quickapp on",
      "  组件一   com.foo.bar                  已关闭",
      "  组件二   com.baz.qux                  已关闭",
    ];
    assert.equal(GuiCore.summarize(one(...tail)), "2 个组件已关闭");
  });

  it("快照与插电常亮落点", () => {
    assert.equal(GuiCore.summarize(one("快照已存")), "已保存");
    assert.equal(GuiCore.summarize(one("插电常亮已改回 30")), "插电常亮已改回 30");
    assert.equal(GuiCore.summarize(one("插电常亮未改动")), "插电常亮未改动");
  });

  it("认不出时回退到最后一个非空行", () => {
    assert.equal(GuiCore.summarize(one("", "最后的输出行")), "最后的输出行");
    assert.equal(GuiCore.summarize(one("", "")), "");
  });
});
