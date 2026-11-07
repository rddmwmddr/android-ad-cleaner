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

test("执行完有结果时进完成页并停掉轮询", async () => {
  const page = await openPage({ api: { poll: () => pollResult({ results: [stepDone] }) } });
  try {
    page.window.showRun();                       // 轮询由 showRun 建，不先建就是空断言
    const polling = page.window.eval("pollJob");
    assert.notEqual(polling, null, "showRun 之后应当有一个在跑的轮询");
    const cleared = spyClearInterval(page.window);

    await page.window.tick();

    assert.equal(heading(page), "完成");
    assert.ok(stepOn(page, 5), "侧栏第 5 步应当高亮");
    assert.deepEqual(cleared, [polling], "要停的是那个真在跑的轮询");
  } finally { page.close(); }
});

test("停止时没有结果也进完成页（#632）", async () => {
  const page = await openPage({ api: { poll: () => pollResult({ results: [], cancel: true }) } });
  try {
    page.window.showRun();
    const polling = page.window.eval("pollJob");
    const cleared = spyClearInterval(page.window);

    await page.window.tick();

    assert.equal(heading(page), "已停止");
    assert.ok(stepOn(page, 5), "侧栏第 5 步应当高亮");
    assert.deepEqual(cleared, [polling]);
  } finally { page.close(); }
});

test("引擎还没收尾时不进完成页", async () => {
  // 用户点了停止、cancel 已经是 true，但进程还在跑（gui/app.py 的收尾阶段）
  const page = await openPage({ api: { poll: () => pollResult({ results: [], cancel: true, running: true }) } });
  try {
    page.window.showRun();
    const cleared = spyClearInterval(page.window);

    await page.window.tick();

    assert.equal(heading(page), "执行", "仍停的执行页，不能跳到完成页");
    assert.deepEqual(cleared, [], "轮询不能停");
  } finally { page.close(); }
});

test("完成页摘要认不出模式时显示最后一条非空行", async () => {
  const page = await openPage();
  try {
    assert.equal(page.window.summarize({ tail: ["开始执行", "人话：最后一句", ""] }), "人话：最后一句");
  } finally { page.close(); }
});

test("没勾的项在完成页是一行「跳过」，不算失败（#577）", async () => {
  const notRun = { title: "关闭各 App 里的广告开关", rc: 0, sec: 0, skipped: true, stopped: false,
                   tail: ["未勾选，本次没有执行"] };
  const page = await openPage({ api: { poll: () => pollResult({ results: [stepDone, notRun] }) } });
  try {
    page.window.showRun();
    await page.window.tick();

    assert.equal(heading(page), "完成", "没勾不等于没成功");
    const rows = [...page.document.querySelectorAll(".res")];
    assert.equal(rows.length, 2);
    assert.match(rows[1].textContent, /跳过/);
    assert.match(rows[1].textContent, /未勾选，本次没有执行/);
    assert.ok(rows[1].querySelector(".tag").classList.contains("warn"), "跳过用跳过样式，不用失败的红");
    assert.equal(page.document.querySelector(".note.bad"), null, "不提示上报");
  } finally { page.close(); }
});

test("真出错的跳过行仍然算失败（#577 不能掩盖它）", async () => {
  const busy = { title: "关闭营销通知", rc: 3, sec: 0, skipped: true, stopped: false,
                 tail: ["读屏服务仍被占用，跳过本步骤；请先解决读屏连接再重试。"] };
  const page = await openPage({ api: { poll: () => pollResult({ results: [busy, stepDone] }) } });
  try {
    page.window.showRun();
    await page.window.tick();

    assert.equal(heading(page), "已结束（有步骤没成功）");
    assert.notEqual(page.document.querySelector(".note.bad"), null, "要提示上报");
    const tag = page.document.querySelector(".res .tag");
    assert.ok(tag.classList.contains("bad"), "故障跳过的行要保持红色，不能被当成没勾");
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
