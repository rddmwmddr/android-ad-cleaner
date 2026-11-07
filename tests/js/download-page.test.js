/* 官网下载页：手机版 APK 那张卡、两条用法路径（票 #714，PR #715），以及国内下载走 Gitee（#718）。
   载入真实 index.html，只往 REL.files 里补条目或按用例改写 REL。 */
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
const WIN = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36";

const APK = (sub) => `    { id: "android", folder: "安卓手机", baidu: { url: "", code: "" }, title: "安卓手机 · 手机版", sub: "${sub}", file: "AndroidAdCleaner-0.4.0-android-arm64.apk", size: "50 MB",
      note: "不用连电脑", sha: "2" },
`;
const ENTRY = (id) => `    { id: "${id}", folder: "x", baidu: { url: "", code: "" }, title: "x · x", sub: "x", file: "AndroidAdCleaner-0.4.0-${id}", size: "1 MB",
      note: "x", sha: "3" },
`;

function open({ userAgent = MAC, platform = "", apk = true, sub = "安卓 11 及以上", extra = "", transform = null } = {}) {
  // Windows 上这份文件是 CRLF，注入锚点必须按 LF 匹配，否则静默不注入
  let html = fs.readFileSync(PAGE, "utf8").replace(/\r\n/g, "\n");
  if (transform) html = transform(html);
  // 0.4.0 起页面自带手机版这一行；先拿掉，有没有手机版由用例的 apk 决定
  html = html.replace(/^    \{ id: "android",[^\n]*\n[^\n]*\},\n/m, "");
  const added = (apk ? APK(sub) : "") + extra;
  if (added) {
    const anchor = "\n  ],\n};";
    assert.ok(html.includes(anchor), "index.html 的 REL.files 结尾变了，注入锚点要跟着改");
    html = html.replace(anchor, "\n" + added + "  ],\n};");
  }
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
    card: (text) => [...document.querySelectorAll("#dl .card")].find((c) => c.querySelector("h3").textContent.includes(text)),
    button: (card, text) => [...card.querySelectorAll("a")].find((a) => a.textContent.includes(text)),
    hero: () => document.querySelector("#hero-meta").textContent,
    heroOs: () => document.querySelector("#hero-os").textContent,
    heroCn: () => document.querySelector("#hero-cn").href,
    heroGh: () => document.querySelector("#hero-gh").href,
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

test("页面上看不到百度网盘，国内下载指向这一版的 Gitee 路径", () => {
  const page = open();
  try {
    const shown = ["#dl", "#dl-after", "#dl-lead"].map((s) => page.document.querySelector(s).textContent).join("\n");
    for (const word of ["百度", "网盘", "提取码"]) assert.ok(!shown.includes(word), word);
    const mac = page.card("Apple");
    assert.match(page.button(mac, "国内下载").href,
      /^https:\/\/gitee\.com\/rddmw\/android-ad-cleaner\/releases\/download\/v[\d.]+\/AndroidAdCleaner-[\d.]+-mac-arm64\.dmg$/);
    assert.ok(page.document.querySelector("#dl-after").textContent.includes("Gitee 全部版本"));
    assert.deepEqual(page.errors, []);
  } finally { page.close(); }
});

test("Gitee 拒收的 Windows 安装版只给 GitHub，没有国内按钮", () => {
  const page = open({ userAgent: WIN, platform: "Win32", apk: false });
  try {
    const setup = page.card("安装版");
    assert.equal(page.button(setup, "国内下载"), undefined);
    assert.ok(page.button(setup, "GitHub").classList.contains("primary"));
    assert.match(page.button(page.card("免安装"), "国内下载").href, /gitee\.com.*windows-portable\.zip$/);
  } finally { page.close(); }
});

// #814：国内 Windows 访客只拿得到免安装版，它不替换已安装的旧版，升级后两个程序并存
test("免安装版不替换旧版这件事，下载页的四处说明缺一不可", () => {
  const page = open({ userAgent: WIN, platform: "Win32", apk: false });
  try {
    const zip = page.card("免安装").textContent;
    assert.match(zip, /不会替换/, "免安装卡片要写明它不替换、也不卸载已安装的旧版");
    assert.match(zip, /卸载/, "要给出卸载旧版的办法");
    assert.match(zip, /覆盖安装/, "另一条路是用安装版覆盖安装");
    assert.match(zip, /数据与备份保留/, "卸载不能丢数据与备份");

    assert.match(page.card("安装版").textContent, /国内下不到安装版/, "安装版卡片要说清国内拿不到它");

    const lead = page.document.querySelector("#dl-lead").textContent;
    assert.match(lead, /安装版会原地替换旧版/, "顶部总述不能无条件承诺「替换旧版程序」");

    const faq = page.document.querySelector("#faq").textContent;
    assert.match(faq, /已安装的应用/, "FAQ 要给 Windows 用户能照着点的卸载路径");
    assert.match(faq, /数据与备份保留/, "FAQ 要说明卸载不动数据与备份");

    assert.deepEqual(page.errors, []);
  } finally { page.close(); }
});

test("Windows 用户的首屏按钮和高亮都指向国内能下的免安装版", () => {
  const page = open({ userAgent: WIN, platform: "Win32", apk: false });
  try {
    assert.match(page.heroCn(), /gitee\.com.*windows-portable\.zip$/);
    assert.ok(page.card("免安装").classList.contains("mine"));
    assert.ok(!page.card("安装版").classList.contains("mine"));
  } finally { page.close(); }
});

test("手机上首屏的两个按钮都指向 APK", () => {
  const page = open({ userAgent: ANDROID });
  try {
    assert.match(page.heroCn(), /gitee\.com.*AndroidAdCleaner-[\d.]+-android-arm64\.apk$/);
    assert.match(page.heroGh(), /AndroidAdCleaner-[\d.]+-android-arm64\.apk$/);
  } finally { page.close(); }
});

// 旧树也绿，守的是不回退：注入 APK 不该把桌面端的高亮带偏
test("电脑上打开时，安卓卡片不高亮，卡片数只多一条", () => {
  const before = open({ apk: false });
  const after = open();
  try {
    assert.equal(after.cards().length, before.cards().length + 1);
    assert.ok(!after.card("手机版").classList.contains("mine"));
    assert.deepEqual(after.highlighted(), ["MAC", "MAC"]);
  } finally {
    before.close();
    after.close();
  }
});

test("Gitee 与网盘都在时，卡片同时给国内下载和百度网盘", () => {
  const page = open({
    apk: false,
    transform: (html) => html.replace(
      /(\{ id: "mac-arm64", folder: "[^"]+", )baidu: \{ url: "", code: "" \}/,
      '$1baidu: { url: "https://pan.baidu.com/s/x", code: "abcd" }'),
  });
  try {
    const mac = page.card("Apple");
    assert.match(page.button(mac, "国内下载").href, /gitee\.com.*mac-arm64\.dmg$/);
    assert.match(page.button(mac, "百度网盘").href, /pan\.baidu\.com\/s\/x\?pwd=abcd/);
    assert.match(mac.textContent, /提取码/);
  } finally { page.close(); }
});

test("国内下载的 Gitee 路径与页首写的版本号是同一个", () => {
  const page = open();
  try {
    const version = page.hero().match(/^v([\d.]+)/)[1];
    assert.ok(page.button(page.card("Apple"), "国内下载").href.includes(`/releases/download/v${version}/`),
      `Gitee 路径要跟着 REL.version（${version}）走，发版时改一处就够`);
  } finally { page.close(); }
});

test("退路：gitee 留空、填回网盘链接后，国内下载回到百度网盘", () => {
  const page = open({
    userAgent: WIN,
    platform: "Win32",
    apk: false,
    transform: (html) => html
      .replace(/gitee: "https:[^"]+",/, 'gitee: "",')
      .replace(/(\{ id: "win-setup", folder: "[^"]+", )baidu: \{ url: "", code: "" \}/,
        '$1baidu: { url: "https://pan.baidu.com/s/x", code: "abcd" }'),
  });
  try {
    const setup = page.card("安装版");
    assert.match(page.button(setup, "国内下载").href, /pan\.baidu\.com\/s\/x\?pwd=abcd/);
    assert.match(setup.textContent, /提取码/);
    assert.equal(page.button(setup, "百度网盘"), undefined);
    assert.ok(!page.document.querySelector("#dl-after").textContent.includes("Gitee"));
  } finally { page.close(); }
});
