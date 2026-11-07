/* 把真实页面装进 jsdom。桌面版脚本在加载时就注册 pywebviewready；
   手机版按 MainActivity 的顺序注入（它自己 dispatch 那个事件）。
   每个用例收尾必须 close()：页面里有 setInterval，不关事件循环就不退出。 */
const fs = require("node:fs");
const path = require("node:path");
const { JSDOM, VirtualConsole } = require("jsdom");

const ROOT = path.resolve(__dirname, "../..");
const PAGE = path.join(ROOT, "gui/web/index.html");
const MOBILE = path.join(ROOT, "android/app/src/main/assets/mobile/mobile.js");

const flush = () => new Promise(resolve => setTimeout(resolve, 0));

/* 一条 poll 返回值，用例只覆盖要断言的字段。 */
function pollResult(over = {}) {
  return {
    next: 0, lines: [], title: "", idx: 0, total: 0, sec: 3,
    running: false, paused: false, pause: false, results: [], cancel: false,
    ...over,
  };
}

const stepDone = { title: "关闭营销通知", rc: 0, sec: 3, tail: ["拨了 2 个"], skipped: false, stopped: false };

async function openPage({ mobile = false, api = {} } = {}) {
  const errors = [];
  const virtualConsole = new VirtualConsole();
  virtualConsole.on("jsdomError", error => errors.push(error));
  virtualConsole.on("error", (...args) => errors.push(args.join(" ")));

  const dom = new JSDOM(fs.readFileSync(PAGE, "utf8"), {
    url: "file://" + PAGE,
    runScripts: "dangerously",
    virtualConsole,
  });
  const window = dom.window;

  const all = {
    env: () => ({ version: "test", adb: false }),
    adb_info: () => ({ path: null, source: "none" }),
    latest_version: () => null,
    poll: () => pollResult(),
    ...api,
  };
  const answer = name => {
    if (!(name in all)) throw new Error(`窗口桥没有定义 ${name}()，用例要显式给出返回值`);
    const value = all[name];
    return (...args) => (typeof value === "function" ? value(...args) : value);
  };

  const hostCalls = [];
  if (mobile) {
    // 手机版自己把 window.pywebview 换成走 AacHost.call 的桥，结果经 __aacDone 回来
    window.AacHost = {
      call(id, name, argsJson) {
        let reply;
        try { reply = { ok: answer(name)(...JSON.parse(argsJson)) }; }
        catch (error) { errors.push(String(error.message || error)); reply = { error: String(error.message || error) }; }
        window.__aacDone(id, JSON.stringify(reply));
      },
      checkState: () => hostCalls.push("checkState"),
      openSettings: at => hostCalls.push("openSettings:" + at),
      startPairing: () => hostCalls.push("startPairing"),
      requestShizuku: () => hostCalls.push("requestShizuku"),
      openShizuku: () => hostCalls.push("openShizuku"),
    };
    window.eval(fs.readFileSync(MOBILE, "utf8"));
  } else {
    window.pywebview = {
      api: new Proxy({}, { get: (_, name) => typeof name === "string" ? (...args) => Promise.resolve(answer(name)(...args)) : undefined }),
    };
    window.dispatchEvent(new window.Event("pywebviewready"));
  }
  await flush();
  if (errors.length) throw new Error(`页面在 jsdom 里报错：${errors.map(String).join("；")}`);

  return {
    window,
    document: window.document,
    errors,
    hostCalls,
    close: () => window.close(),
  };
}

module.exports = { openPage, pollResult, stepDone };
