/* 连接页：周期性刷新不能改变用户点出来的折叠状态（#1292）。 */
const test = require("node:test");
const assert = require("node:assert/strict");
const { openPage } = require("./page.js");
const flush = () => new Promise(resolve => setTimeout(resolve, 0));

const NO_ANDROID = () => ({ list: [] });
const NO_HARMONY = () => ({ list: [] });
const harmonyDevice = { serial: "hdc-1", name: "鸿蒙测试机", model: "HOP-AL10", state: "Connected", supported: true };
const androidDevice = { serial: "abc123", state: "device", brand: "Xiaomi", model: "M2012K11AC", name: "小米测试机" };

function bridge(over = {}) {
  return {
    env: () => ({ version: "test", adb: true, harmony: true }),
    devices: NO_ANDROID,
    usb_hint: () => "",
    harmony: NO_HARMONY,
    ...over,
  };
}

test("收起图文教程后，后续刷新不会再把它展开", async () => {
  const page = await openPage({ api: bridge() });
  try {
    await flush();
    const tut = page.document.querySelector("#tutbox");
    assert.equal(tut.open, true, "0 台设备时第一次刷新给一次默认展开");

    tut.querySelector("summary").click();
    assert.equal(tut.open, false);

    await page.window.refreshDevices();
    await page.window.refreshDevices();
    assert.equal(tut.open, false, "刷新不得再改用户点出来的收起状态");
  } finally {
    page.close();
  }
});

test("列表没变的刷新不重建设备区节点，点击落点不会被换掉", async () => {
  const page = await openPage({ api: bridge({ devices: () => ({ list: [androidDevice] }) }) });
  try {
    await flush();
    const card = page.document.querySelector("#devbox .dev");
    const use = card.querySelector("button");
    assert.ok(card && use, "已连接的安卓手机要有一张卡与「用这台」");

    await page.window.refreshDevices();
    await page.window.refreshDevices();
    assert.equal(page.document.querySelector("#devbox .dev"), card);
    assert.equal(page.document.querySelector("#devbox .dev button"), use);
  } finally {
    page.close();
  }
});

test("先连着设备、之后才拔线：教程在第一次进入等待态时展开一次", async () => {
  let list = [androidDevice];
  const page = await openPage({ api: bridge({ devices: () => ({ list }) }) });
  try {
    await flush();
    const tut = page.document.querySelector("#tutbox");
    assert.equal(tut.open, false, "有设备时不该展开教程");

    list = [];
    await page.window.refreshDevices();
    assert.equal(tut.open, true, "第一次落到「没有设备」时给一次默认展开");

    tut.querySelector("summary").click();
    list = [androidDevice];
    await page.window.refreshDevices();
    list = [];
    await page.window.refreshDevices();
    assert.equal(tut.open, false, "之后再怎么插拔，展开与收起都由用户决定");
  } finally {
    page.close();
  }
});

test("点开连接鸿蒙手机后，刷新既不收回也不换掉这个节点", async () => {
  const page = await openPage({ api: bridge() });
  try {
    await flush();
    const help = page.document.querySelector("#harmonyhelp");
    assert.ok(help, "连接页要常驻一段鸿蒙连接说明");
    assert.equal(help.classList.contains("hide"), false, "没有鸿蒙设备时这段说明可见");

    help.querySelector("summary").click();
    assert.equal(help.open, true);

    await page.window.refreshHarmonyDevices();
    await page.window.refreshHarmonyDevices();
    assert.equal(page.document.querySelector("#harmonyhelp"), help, "刷新只换内容，不重建承载 open 的 <details>");
    assert.equal(help.open, true);
  } finally {
    page.close();
  }
});

test("鸿蒙设备列表变了，用户选定的展开状态仍保留", async () => {
  let list = [];
  const page = await openPage({ api: bridge({ harmony: () => ({ list }) }) });
  try {
    await flush();
    const help = page.document.querySelector("#harmonyhelp");
    help.querySelector("summary").click();

    list = [harmonyDevice];
    await page.window.refreshHarmonyDevices();
    assert.match(page.document.querySelector("#harmonydevbox").textContent, /鸿蒙测试机/);
    assert.equal(help.classList.contains("hide"), true, "有设备时说明让位给设备列表");

    list = [];
    await page.window.refreshHarmonyDevices();
    assert.equal(help.classList.contains("hide"), false);
    assert.equal(page.document.querySelector("#harmonyhelp").open, true, "设备拔掉后回来，还是用户当时展开的样子");
  } finally {
    page.close();
  }
});
