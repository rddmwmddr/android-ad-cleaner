/* 桌面版：执行页的落点与完成页摘要的兜底（#632、#647）。 */
const test = require("node:test");
const assert = require("node:assert/strict");
const { openPage, pollResult, stepDone } = require("./page.js");
/* 与手机版 aac_android/view.py 的 summarize() 同一批 tail、同一批期望串（#758）：
   tests/test_android_view.py 读的是同一份文件，两处产出必须逐字相同。 */
const SUMMARY_CASES = require("../summary_cases.json");

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

/* 手动驱动轮询：先建好执行页，再把 500 ms 定时器摘掉，免得它在断言之间插进来。 */
function startPolling(page) {
  page.window.showRun();
  page.window.eval("clearInterval(pollJob); pollJob = null");
}

/* 让 api.poll 挂住，由用例决定哪一次先回包。tick() 会 await 它，所以返回的 Promise 不能由这里 await。 */
function hungPoll() {
  const calls = [];
  const poll = since => new Promise(resolve => calls.push({ since, resolve }));
  return { calls, poll };
}

const flush = () => new Promise(resolve => setTimeout(resolve, 0));

/* 假时钟起点用真实量级：#676 的 pollStart 初值是 0，用 1000 起步的话「每次发起都刷新起点」删掉也看不出来。 */
const EPOCH = 1_700_000_000_000;

function logText(page) {
  return page.document.querySelector("#log").textContent;
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

test("机型脚本摘要说清三类结局，与手机版逐字一致（#758）", async () => {
  const page = await openPage();
  try {
    for (const c of SUMMARY_CASES){
      assert.equal(page.window.summarize({ tail: c.tail }), c.want, c.name);
    }
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

// 守卫用例：旧树也绿——单飞行自 #662 起就在，这里守的是它不回退（#698）
test("上一次 poll 没回来时不发第二次（#698）", async () => {
  const hung = hungPoll();
  const page = await openPage({ api: { poll: hung.poll } });
  try {
    let now = EPOCH;
    page.window.Date.now = () => now;
    startPolling(page);

    page.window.tick();                          // 挂住：这个 Promise 永远不落地，不能 await
    await flush();
    assert.equal(hung.calls.length, 1);

    now += 5000; page.window.tick(); await flush();
    now += 1000; page.window.tick(); await flush();

    assert.equal(hung.calls.length, 1, "上一次还在路上，10 秒以内不该重发");
  } finally { page.close(); }
});

test("一次 poll 超时后重发，且只补没画过的那一段（#698）", async () => {
  // 守的是 #676 的超时重发：超过 POLL_TIMEOUT 允许重问，问的仍是没画过的那一段
  const hung = hungPoll();
  const page = await openPage({ api: { poll: hung.poll } });
  try {
    let now = EPOCH;
    page.window.Date.now = () => now;
    startPolling(page);

    page.window.tick();
    await flush();
    hung.calls[0].resolve(pollResult({ next: 2, lines: ["第一行", "第二行"] }));
    await flush();
    assert.equal(page.window.eval("S.logNext"), 2);

    page.window.tick();                          // 第二次挂住，起点是上一次画到的位置
    await flush();
    assert.equal(hung.calls[1].since, 2);

    now += 10500;
    page.window.tick();
    await flush();
    assert.equal(hung.calls.length, 3, "超过 POLL_TIMEOUT 要允许重发");
    assert.equal(hung.calls[2].since, 2, "重发时只问还没画过的那一段");

    hung.calls[2].resolve(pollResult({ next: 4, lines: ["第三行", "第四行"] }));
    await flush();

    assert.match(logText(page), /第一行\n第二行\n第三行\n第四行/);
    assert.equal(page.window.eval("S.logNext"), 4);
  } finally { page.close(); }
});

test("被后来一次接管的那份回包迟到时整份丢弃（#698）", async () => {
  // 守的是 #676 的序号作废：晚到的那份整份丢掉，不画、不改 S.logNext
  const hung = hungPoll();
  const page = await openPage({ api: { poll: hung.poll } });
  try {
    let now = EPOCH;
    page.window.Date.now = () => now;
    startPolling(page);

    page.window.tick();
    await flush();

    now += 10500;
    page.window.tick();
    await flush();
    hung.calls[1].resolve(pollResult({ next: 2, lines: ["第一行", "第二行"] }));
    await flush();

    // 挂住的那一次问的是 since=0，真回来时整段尾巴都在（Job.snapshot 的 next = since + len(lines)），
    // 所以它比后发的那次更大：只靠 `r.next > S.logNext` 挡不住，必须是序号作废。票面写的 next:1 挡得住，验不出这条。
    hung.calls[0].resolve(pollResult({ next: 3, lines: ["第一行", "第二行", "迟到的旧行"] }));
    await flush();

    assert.doesNotMatch(logText(page), /迟到的旧行/, "迟到的旧结果不能再画进来");
    assert.equal(page.window.eval("S.logNext"), 2, "作废的那份不能改 logNext");
  } finally { page.close(); }
});

test("有可重试的步时结果页给按钮，N 由后台算（#638）", async () => {
  const results = [stepDone, { title: "关闭各 App 里的广告开关", rc: 1, sec: 5, tail: ["未完成步骤：商店"], skipped: false, stopped: false }];
  let asked = 0;
  const page = await openPage({ api: { retry: () => { asked += 1; return { ok: true, total: 1 }; } } });
  try {
    page.window.showDone(pollResult({ results, retry: 1 }));
    const button = [...page.document.querySelectorAll("#main button")]
      .find(b => b.textContent.includes("重试没成功的步骤"));
    assert.ok(button, "结果页应当出现重试按钮");
    assert.match(button.textContent, /（1）/, "N 来自 poll 的 retry");

    button.click();                        // 走页面上的 onclick 绑定，不直接调函数
    await flush();
    page.window.eval("clearInterval(pollJob); pollJob = null");
    assert.equal(asked, 1, "点一下只该问后台一次");
    assert.equal(heading(page), "执行");
    assert.equal(page.window.eval("S.logNext"), 0);
  } finally { page.close(); }
});

test("没有可重试的步时结果页不给按钮（#638）", async () => {
  // 旧树也绿：守的是回退——按钮只在后台给出 N > 0 时出现，别在界面上自己猜。
  const page = await openPage();
  try {
    page.window.showDone(pollResult({ results: [stepDone] }));
    const button = [...page.document.querySelectorAll("#main button")]
      .find(b => b.textContent.includes("重试没成功的步骤"));
    assert.equal(button, undefined);
  } finally { page.close(); }
});
