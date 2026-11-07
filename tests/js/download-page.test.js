/* 根目录 index.html 的下载区：国内下载走 Gitee，页面上不出现百度网盘；Gitee 拒收的文件只给 GitHub；
   手机上打开时高亮 APK；gitee 留空、填回网盘链接后能恢复（#718）。 */
const { test } = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const { JSDOM, VirtualConsole } = require("jsdom");

const PAGE = path.resolve(__dirname, "../../index.html");
const MAC = { ua: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/130", platform: "MacIntel" };
const WIN = { ua: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130", platform: "Win32" };
const PHONE = { ua: "Mozilla/5.0 (Linux; Android 16; M154FF) Chrome/130 Mobile", platform: "Linux armv8l" };
const APK = `    { id: "android", folder: "安卓手机", baidu: { url: "", code: "" }, title: "安卓手机 · 手机版", sub: "安卓 11 及以上", file: "AndroidAdCleaner-9.9.9-android-arm64.apk", size: "50 MB",
      note: "不用连电脑", sha: "abc" },
  ],
};
const RELEASED`;

function open(device, edit = html => html) {
  const errors = [];
  const virtualConsole = new VirtualConsole();
  virtualConsole.on("jsdomError", error => errors.push(String(error)));
  const dom = new JSDOM(edit(fs.readFileSync(PAGE, "utf8")), {
    url: "file://" + PAGE,
    runScripts: "dangerously",
    virtualConsole,
    beforeParse(window) {
      Object.defineProperty(window.navigator, "userAgent", { value: device.ua });
      Object.defineProperty(window.navigator, "platform", { value: device.platform });
    },
  });
  const document = dom.window.document;
  const cards = [...document.querySelectorAll("#dl .card")];
  const card = text => cards.find(c => c.querySelector("h3").textContent.includes(text));
  const button = (c, text) => [...c.querySelectorAll("a")].find(a => a.textContent.includes(text));
  const finish = () => {
    dom.window.close();
    assert.deepStrictEqual(errors, []);
  };
  return { document, cards, card, button, finish };
}

const withApk = html => html.replace(/ {2}\],\n\};\nconst RELEASED/, APK);

test("页面上看不到百度网盘，国内下载指向这一版的 Gitee 路径", () => {
  const page = open(MAC);
  const shown = ["#dl", "#dl-after", "#dl-lead"].map(s => page.document.querySelector(s).textContent).join("\n");
  for (const word of ["百度", "网盘", "提取码"]) assert.ok(!shown.includes(word), word);
  const mac = page.card("Apple");
  assert.match(page.button(mac, "国内下载").href, /^https:\/\/gitee\.com\/rddmw\/android-ad-cleaner\/releases\/download\/v[\d.]+\/AndroidAdCleaner-[\d.]+-mac-arm64\.dmg$/);
  assert.ok(page.document.querySelector("#dl-after").textContent.includes("Gitee 全部版本"));
  page.finish();
});

test("Gitee 拒收的 Windows 安装版只给 GitHub，并提示选免安装版", () => {
  const page = open(WIN);
  const setup = page.card("安装版");
  assert.strictEqual(page.button(setup, "国内下载"), undefined);
  assert.ok(page.button(setup, "GitHub").classList.contains("primary"));
  assert.ok(setup.textContent.includes("国内网络建议下载免安装版"));
  assert.match(page.button(page.card("免安装"), "国内下载").href, /gitee\.com.*windows-portable\.zip$/);
  page.finish();
});

test("Windows 用户的首屏按钮和高亮都指向国内能下的免安装版", () => {
  const page = open(WIN);
  assert.match(page.document.querySelector("#hero-cn").href, /gitee\.com.*windows-portable\.zip$/);
  assert.ok(page.card("免安装").classList.contains("mine"));
  assert.ok(!page.card("安装版").classList.contains("mine"));
  page.finish();
});

test("有 APK 条目时出现安卓卡片，手机上高亮并指向首屏", () => {
  const page = open(PHONE, withApk);
  const phone = page.card("手机版");
  assert.strictEqual(phone.querySelector(".os").textContent, "安卓手机");
  assert.ok(phone.classList.contains("mine"));
  assert.ok(!page.card("Apple").classList.contains("mine"));
  assert.match(page.document.querySelector("#hero-cn").href, /gitee\.com.*android-arm64\.apk$/);
  assert.strictEqual(page.document.querySelector("#hero-os").textContent, "手机版");
  assert.ok(page.document.querySelector("#hero-meta").textContent.includes("安卓 11 及以上"));
  page.finish();
});

test("电脑上打开时，安卓卡片不高亮，别的卡片不变", () => {
  const before = open(MAC);
  const count = before.cards.length;
  before.finish();
  const page = open(MAC, withApk);
  assert.strictEqual(page.cards.length, count + 1);
  assert.ok(!page.card("手机版").classList.contains("mine"));
  assert.ok(page.card("Apple").classList.contains("mine"));
  page.finish();
});

test("退路：gitee 留空、填回网盘链接后，国内下载回到百度网盘", () => {
  const restore = html => html
    .replace(/gitee: "https:[^"]+",/, 'gitee: "",')
    .replace(/(\{ id: "win-setup", folder: "[^"]+", )baidu: \{ url: "", code: "" \}/, '$1baidu: { url: "https://pan.baidu.com/s/x", code: "abcd" }');
  const page = open(WIN, restore);
  const setup = page.card("安装版");
  assert.match(page.button(setup, "国内下载").href, /pan\.baidu\.com\/s\/x\?pwd=abcd/);
  assert.ok(setup.textContent.includes("提取码"));
  assert.strictEqual(page.button(setup, "百度网盘"), undefined);
  assert.ok(!page.document.querySelector("#dl-after").textContent.includes("Gitee"));
  page.finish();
});
