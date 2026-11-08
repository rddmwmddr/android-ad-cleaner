/* 免安装版启动时那条一次性提示（#872）：出现、关掉、没有旧安装时不出现。 */
const test = require("node:test");
const assert = require("node:assert/strict");
const { openPage } = require("./page.js");

const flush = () => new Promise(resolve => setTimeout(resolve, 0));

const NOTE = "这台电脑上还装着旧版的「安卓去广告」（0.3.2 及更早版本装的名字）。";

async function openWith(api) {
  const page = await openPage({ api });
  await flush();
  return page;
}

test("旧名安装还在时第一步给出提示与「知道了」", async () => {
  const page = await openWith({ old_install_notice: () => ({ version: "test", text: NOTE }) });
  try {
    const box = page.document.querySelector("#oldver");
    assert.ok(box, "第一步要有一个放提示的位置");
    assert.match(box.textContent, /安卓去广告/, "提示要照后端给的原文显示");
    assert.match(box.textContent, /知道了/, "要能关掉这条提示");
  } finally { page.close(); }
});

test("点「知道了」后提示消失，并告诉后端这一版不用再提", async () => {
  const dismissed = [];
  const page = await openWith({
    old_install_notice: () => ({ version: "test", text: NOTE }),
    dismiss_old_install: () => { dismissed.push(1); return true; },
  });
  try {
    page.document.querySelector("#oldver button").click();
    await flush();
    assert.equal(page.document.querySelector("#oldver").textContent.trim(), "");
    assert.deepEqual(dismissed, [1]);
  } finally { page.close(); }
});

test("没有旧名安装时不出提示", async () => {
  const page = await openWith({ old_install_notice: () => ({}) });
  try {
    assert.equal(page.document.querySelector("#oldver").textContent.trim(), "");
  } finally { page.close(); }
});

test("检测失败时页面照常进第一步", async () => {
  const page = await openWith({ old_install_notice: () => Promise.reject(new Error("注册表读不了")) });
  try {
    assert.equal(page.document.querySelector("#main h1").textContent, "连接手机");
    assert.equal(page.document.querySelector("#oldver").textContent.trim(), "");
  } finally { page.close(); }
});
