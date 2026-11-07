/* 手机版：完成页要有出口（#632 第 2 条）。手机版藏了侧栏，停止后停在执行页就回不去，
   覆盖后的 showDone 追加「回到首页 / 重新开始」并配上顶部状态徽标。 */
const test = require("node:test");
const assert = require("node:assert/strict");
const { openPage, pollResult } = require("./page.js");

test("手机版停止后完成页给出回到首页与重新开始的出口", async () => {
  const page = await openPage({
    mobile: true,
    api: { poll: () => pollResult({ results: [], cancel: true }) },
  });
  try {
    await page.window.tick();

    const buttons = [...page.document.querySelectorAll("#main .actions .btn")].map(b => b.textContent);
    assert.deepEqual(buttons, ["回到首页", "重新开始"]);
    assert.equal(page.document.querySelector("#main .actions .btn").getAttribute("onclick"), "showConnect()");
    assert.ok(page.document.querySelector("#main .hero .badge.warn"), "停止不是出错，徽标是 warn");
  } finally { page.close(); }
});
