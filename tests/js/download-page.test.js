/* 官网下载页：手机版 APK 那张卡与两条用法路径（票 #714，PR #715）。载入真实 index.html，只往 REL.files 里补条目。 */
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { JSDOM, VirtualConsole } = require("jsdom");

const ROOT = path.resolve(__dirname, "../..");
const PAGE = path.join(ROOT, "index.html");

const ANDROID = "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Mobile Safari/537.36";
// Firefox / 内置 WebView 没有 userAgentData，navigator.platform 报的是 Linux 而不是 Android
const ANDROID_FIREFOX = "Mozilla/5.0 (Android 14; Mobile; rv:126.0) Gecko/126.0 Firefox/126.0";
const MAC = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36";

const APK = (sub) => `    { id: "android", folder: "安卓手机", baidu: { url: "", code: "" }, title: "安卓手机 · 手机版", sub: "${sub}", file: "AndroidAdCleaner-0.4.0-android-arm64.apk", size: "50 MB",
      note: "不用连电脑", sha: "2" },
`;
const ENTRY = (id) => `    { id: "${id}", folder: "x", baidu: { url: "", code: "" }, title: "x · x", sub: "x", file: "AndroidAdCleaner-0.4.0-${id}", size: "1 MB",
      note: "x", sha: "3" },
`;

function open({ userAgent = MAC, platform = "", apk = true, sub = "安卓 11 及以上", extra = "" } = {}) {
  let html = fs.readFileSync(PAGE, "utf8");
  const added = (apk ? APK(sub) : "") + extra;
  if (added) html = html.replace("\n  ],\n};", "\n" + added + "  ],\n};");
  const errors = [];
  const virtualConsole = new VirtualConsole();
  virtualConsole.on("jsdomError", (error) => errors.push(error));
  const { window } = new JSDOM(html, {
    url: "file://" + PAGE,
    runScripts: "dangerously",
    virtualConsole,
    // jsdom 31 不认 userAgent 选项，得在页面脚本跑之前把 navigator 换掉
    beforeParse(w) {
      Object.defineProperty(w.navigator, "userAgent", { get: () => userAgent, configurable: true });
      Object.defineProperty(w.navigator, "platform", { get: () => platform, configurable: true });
    },
  });
  const document = window.document;
  return {
    errors,
    document,
    cards: () => [...document.querySelectorAll("#dl .card")],
    labels: () => [...document.querySelectorAll("#dl .card .os")].map((el) => el.textContent),
    highlighted: () => [...document.querySelectorAll("#dl .card.mine .os")].map((el) => el.textContent),
    hero: () => document.querySelector("#hero-meta").textContent,
    heroOs: () => document.querySelector("#hero-os").textContent,
    close: () => window.close(),
  };
}

test("安卓手机上打开，下载区高亮手机版那一张", () => {
  const page = open({ userAgent: ANDROID });
  try {
    assert.equal(page.cards().length, 5, "四个桌面卡片加手机版");
    assert.deepEqual(page.highlighted(), ["安卓手机"]);
    assert.deepEqual(page.errors, []);
  } finally { page.close(); }
});

test("安卓上的 Firefox / WebView 也能高亮：platform 报的是 Linux，ua 里才有 Android", () => {
  const page = open({ userAgent: ANDROID_FIREFOX, platform: "Linux armv8l" });
  try {
    assert.deepEqual(page.highlighted(), ["安卓手机"]);
  } finally { page.close(); }
});

// 旧树也绿，守的是不回退：桌面端的判定不该被安卓那条分支带偏
test("Mac 上仍只高亮 Apple 芯片那一张，手机版不抢镜", () => {
  const page = open({ userAgent: MAC });
  try {
    assert.deepEqual(page.highlighted(), ["MAC", "MAC"], "两张 Mac 卡片都算本机可用的");
  } finally { page.close(); }
});

test("hero 的适用范围跟着 REL.files 走，不是写死的", () => {
  const withApk = open({ sub: "安卓 12 及以上" });
  const without = open({ apk: false });
  try {
    assert.match(withApk.hero(), /安卓 12 及以上/, "换一个最低版本，hero 要跟着变");
    assert.doesNotMatch(without.hero(), /安卓/);
  } finally {
    withApk.close();
    without.close();
  }
});

test("安卓手机上主按钮的小字写「安卓」，桌面上才写 Mac / Windows", () => {
  const phone = open({ userAgent: ANDROID });
  const mac = open({ userAgent: MAC });
  const noApk = open({ userAgent: ANDROID, apk: false });   // 下载页还没上手机版时的样子
  try {
    assert.equal(phone.heroOs(), "安卓");
    assert.equal(mac.heroOs(), "Mac");
    assert.equal(noApk.heroOs(), "", "没有手机版条目时不该写「安卓」，那会指向一个不存在的包");
  } finally {
    phone.close();
    mac.close();
    noApk.close();
  }
});

test("「怎么用」给手机版和电脑版各一条路径", () => {
  const page = open();
  try {
    const phone = page.document.querySelector('#how [data-path="phone"]');
    const desk = page.document.querySelector('#how [data-path="desk"]');
    assert.ok(phone, "手机版那条路径要在页面上");
    assert.ok(desk, "电脑版那条路径也在");
    // 断言落在步骤列表上：只看标题小字的话，把 <ol> 整个删掉也照样绿
    const phoneSteps = [...phone.querySelectorAll(".steps li")];
    const deskSteps = [...desk.querySelectorAll(".steps li")];
    assert.equal(phoneSteps.length, 5, "手机版五个步骤");
    assert.equal(deskSteps.length, 5, "电脑版五个步骤");
    assert.match(phoneSteps[0].textContent, /3 个设置/);
    assert.match(deskSteps[0].textContent, /数据线/);
  } finally { page.close(); }
});

test("认不出的 id 用自己的名字当角标，不冒充 WINDOWS", () => {
  const page = open({ apk: false, extra: ENTRY("linux-deb") });
  try {
    assert.deepEqual(page.labels(), ["MAC", "MAC", "WINDOWS", "WINDOWS", "LINUX-DEB"]);
  } finally { page.close(); }
});
