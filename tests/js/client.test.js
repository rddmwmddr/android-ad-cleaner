/* 桌面版：执行页的落点与完成页摘要的兜底（#632、#647）。 */
const test = require("node:test");
const assert = require("node:assert/strict");
const { openPage, pollResult, stepDone } = require("./page.js");

function spyClearInterval(window) {
  const cleared = [];
  const original = window.clearInterval;
  window.clearInterval = id => { cleared.push(id); return original.call(window, id); };
  return cleared;
}

function heading(page) {
  return page.document.querySelector("#main h1").textContent;
}

function stepOn(page, n) {
  return page.document.querySelector(`.step[data-s="${n}"]`).classList.contains("on");
}

test("执行完有结果时进完成页", async () => {
  const page = await openPage({ api: { poll: () => pollResult({ results: [stepDone] }) } });
  try {
    const cleared = spyClearInterval(page.window);
    await page.window.tick();
    assert.equal(heading(page), "完成");
    assert.ok(stepOn(page, 5), "侧栏第 5 步应当高亮");
    assert.equal(cleared.length, 1, "进完成页之后轮询要停");
  } finally { page.close(); }
});

test("停止时没有结果也进完成页（#632）", async () => {
  const page = await openPage({ api: { poll: () => pollResult({ results: [], cancel: true }) } });
  try {
    const cleared = spyClearInterval(page.window);
    await page.window.tick();
    assert.equal(heading(page), "已停止");
    assert.ok(stepOn(page, 5), "侧栏第 5 步应当高亮");
    assert.equal(cleared.length, 1, "进完成页之后轮询要停");
  } finally { page.close(); }
});

test("完成页摘要认不出模式时显示最后一条非空行", async () => {
  const page = await openPage();
  try {
    assert.equal(page.window.summarize({ tail: ["开始执行", "人话：最后一句", ""] }), "人话：最后一句");
  } finally { page.close(); }
});

test("完成页摘要遇到空 tail 返回空串而不是 undefined", async () => {
  const page = await openPage();
  try {
    assert.equal(page.window.summarize({ tail: ["", ""] }), "");
  } finally { page.close(); }
});

test("完成页摘要认得快照已存", async () => {
  const page = await openPage();
  try {
    assert.equal(page.window.summarize({ tail: ["快照已存：3 项"] }), "已保存");
  } finally { page.close(); }
});
