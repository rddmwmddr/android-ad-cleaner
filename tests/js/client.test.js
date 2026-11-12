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

/* 摘要由后端算（tool/summary.py，两个宿主共用，#1189）：结果页只渲染 results[].summary，
   口径本身在 tests/test_summary.py 里跑共享样例集。这里只管字段原样画出来、缺字段时不留旧逻辑。 */
test("完成页结果行只渲染后端给的摘要字段（#1189）", async () => {
  const page = await openPage();
  try {
    page.window.showDone(pollResult({ results: [
      { title: "关闭各 App 里的广告开关", rc: 0, sec: 7, summary: "关了 26 个开关",
        tail: ["机型脚本跑完：关了 26 个，210 秒"] },
      { title: "收尾", rc: 0, sec: 1, tail: ["插电常亮已改回 1"] },
    ]}));
    const cells = [...page.document.querySelectorAll(".res .d")].map(n => n.textContent);
    assert.equal(cells[0], "关了 26 个开关 · 7 秒");
    assert.equal(cells[1], " · 1 秒", "没有 summary 就显示空串，不回退去读 tail");
  } finally { page.close(); }
});

test("没勾的项在完成页是一行「跳过」，不算失败（#577）", async () => {
  const notRun = { title: "关闭各 App 里的广告开关", rc: 0, sec: 0, skipped: true, stopped: false,
                   summary: "未勾选，本次没有执行", tail: ["未勾选，本次没有执行"] };
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

test("没标录制版本的机型脚本不说「版本一致」（#942）", async () => {
  const status = {
    info: { model: "25060RK16C", brand: "Redmi", name: "REDMI K80 Ultra", os: "",
            build: "BP2A.250605.031.A3", android: "16" },
    recipe: "recipes/redmi-25060RK16C/recipe.py", recipe_ref: false,
    recipe_build: "", recipe_ok: true, steps: ["系统广告"],
    ads: [], quickapps: [], locked: false, dev: false, backup: null,
    fold_open: false, input_blocked: false, stay_on: "",
  };
  const page = await openPage({ api: { status: () => status } });
  try {
    page.window.eval("S.serial = 'X'");
    await page.window.showDetect();
    const kv = [...page.document.querySelectorAll(".kv")]
      .find(n => n.textContent.includes("机型脚本"));
    assert.match(kv.textContent, /录制版本未标/);
    assert.doesNotMatch(kv.textContent, /版本一致/);
  } finally { page.close(); }
});

/* #1188：验证档位提示的判据与措辞都在后端（tool/coverage_note.py，两个宿主同一份），
   网页只剩「字段有值就画一行、没值不画」这一层。判据本身由 tests/test_coverage_note.py 覆盖。 */
const coverageNotes = page => [...page.document.querySelectorAll("#main .note.info")]
  .map(n => n.textContent);

test("后端给了验证档位提示时，结果页画出来（#1188）", async () => {
  const page = await openPage();
  try {
    const note = "这套机型脚本只在一部分步骤上做过真机验证，其余步骤这次是照脚本直接跑的，建议在 App 里顺手核对一眼。";
    page.window.showDone(pollResult({ results: [stepDone], coverage_note: note }));
    assert.deepEqual(coverageNotes(page), [note]);
  } finally { page.close(); }
});

test("后端没给验证档位提示时，结果页不添任何行（#1188）", async () => {
  const page = await openPage();
  try {
    page.window.showDone(pollResult({ results: [stepDone] }));
    assert.deepEqual(coverageNotes(page), []);
    page.window.showDone(pollResult({ results: [stepDone], coverage_note: "" }));
    assert.deepEqual(coverageNotes(page), []);
    assert.equal(heading(page), "完成");
  } finally { page.close(); }
});

/* #973：选择页「挂起广告组件」的默认值来自 status-json 的 default_on ——
   小米 msa 预先勾上，其他品牌不勾，已挂起的项根本不出勾选框（走「已经挂起」那句）。 */
function chooseStatus(ads, over = {}) {
  return {
    info: { model: "2510DRK44C", brand: "Redmi", name: "REDMI K90", os: "OS4.0.5.0", build: "", android: "17" },
    recipe: "xiaomi-M154FF/recipe.py", recipe_ref: false, recipe_ok: true, recipe_build: "OS4.0",
    steps: ["主题"], ads, quickapps: [], locked: false, dev: false, backup: null,
    fold_open: false, input_blocked: false, stay_on: "",
    ...over,
  };
}

async function openChoose(ads, over = {}) {
  const status = chooseStatus(ads, over);
  const page = await openPage({ api: { status: () => status, chan_scan: () => ({ chans: [], notes: [] }) } });
  page.window.eval(`S.serial = "X"; S.status = ${JSON.stringify(status)}; S.chans = []; S.chanNotes = [];`);
  await page.window.showChoose();
  return page;
}

test("选择页：default_on 的广告包预先勾上（#973）", async () => {
  const page = await openChoose([{ pkg: "com.miui.systemAdSolution", suspended: false, default_on: true }]);
  try {
    const boxes = [...page.document.querySelectorAll(".c-ad")];
    assert.deepEqual(boxes.map(b => [b.value, b.checked]), [["com.miui.systemAdSolution", true]]);
  } finally { page.close(); }
});

test("选择页：非默认广告包不勾，已挂起的 msa 不出勾选框（#973）", async () => {
  const page = await openChoose([
    { pkg: "com.opos.ads", suspended: false, default_on: false },              // 非小米：不预勾
    { pkg: "com.miui.systemAdSolution", suspended: true, default_on: false },  // 小米已挂起：不出勾选框
  ]);
  try {
    const boxes = [...page.document.querySelectorAll(".c-ad")];
    assert.deepEqual(boxes.map(b => [b.value, b.checked]), [["com.opos.ads", false]]);
    assert.match(page.document.querySelector("#main").textContent, /挂起只是暂停运行/);
  } finally { page.close(); }
});

test("选择页：取消预勾后开始，计划里不含挂起（#973）", async () => {
  const started = [];
  const status = chooseStatus([{ pkg: "com.miui.systemAdSolution", suspended: false, default_on: true }]);
  const page = await openPage({ api: {
    status: () => status, chan_scan: () => ({ chans: [], notes: [] }),
    start: (serial, plan) => { started.push(plan); return { ok: true, total: 1 }; },
    poll: () => pollResult(),
  } });
  try {
    page.window.eval(`S.serial = "X"; S.status = ${JSON.stringify(status)}; S.chans = []; S.chanNotes = [];`);
    await page.window.showChoose();
    page.document.querySelector(".c-ad").checked = false;
    await page.window.go();
    assert.deepEqual(Array.from(started[0].ads), []);
  } finally {
    page.window.eval("clearInterval(pollJob); pollJob = null");
    page.close();
  }
});

test("选择页：直接开始就把 msa 排进计划（#973）", async () => {
  const started = [];
  const status = chooseStatus([{ pkg: "com.miui.systemAdSolution", suspended: false, default_on: true }]);
  const page = await openPage({ api: {
    status: () => status, chan_scan: () => ({ chans: [], notes: [] }),
    start: (serial, plan) => { started.push(plan); return { ok: true, total: 1 }; },
    poll: () => pollResult(),
  } });
  try {
    page.window.eval(`S.serial = "X"; S.status = ${JSON.stringify(status)}; S.chans = []; S.chanNotes = [];`);
    await page.window.showChoose();
    await page.window.go();
    assert.deepEqual(Array.from(started[0].ads), ["com.miui.systemAdSolution"]);   // 跨 realm 的数组要先摊成 Node 的
  } finally {
    page.window.eval("clearInterval(pollJob); pollJob = null");
    page.close();
  }
});

test("没有机型脚本时，桌面版手动清单认三星、华为、魅族（#952）", async () => {
  const urls = [];
  const cases = [["samsung", "三星 / One UI ", "三星-OneUI.md"],
                 ["huawei", "华为 / HarmonyOS ", "华为-HarmonyOS.md"],
                 ["meizu", "魅族 / Flyme ", "魅族-Flyme.md"]];
  for (const [brand, label, file] of cases) {
    const status = {
      info: { model: "X", brand, name: "Phone", os: "16", build: "", android: "16" },
      recipe: null, recipe_ref: false, recipe_ok: false, recipe_build: "",
      steps: [], ads: [], quickapps: [], locked: false, dev: false, backup: null,
      fold_open: false, input_blocked: false, stay_on: "",
    };
    const page = await openPage({ api: { status: () => status, open_url: url => urls.push(url) } });
    try {
      page.window.eval("S.serial = 'X'");
      await page.window.showDetect();
      const link = [...page.document.querySelectorAll("#main a")]
        .find(a => a.textContent.includes("手动清单"));
      assert.equal(link.textContent, `${label}手动清单`);
      link.dispatchEvent(new page.window.MouseEvent("click", { bubbles: true, cancelable: true }));
      assert.equal(urls.pop(), "https://github.com/rddmwmddr/android-ad-cleaner/blob/main/docs/"
        + encodeURIComponent("清单") + "/" + encodeURIComponent(file));
    } finally { page.close(); }
  }
});
