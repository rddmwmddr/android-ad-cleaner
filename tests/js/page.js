/* 把真实页面装进 jsdom。桌面版脚本在加载时就注册 pywebviewready。
   每个用例收尾必须 close()：页面里有 setInterval，不关事件循环就不退出。 */
const fs = require("node:fs");
const path = require("node:path");
const { JSDOM, VirtualConsole } = require("jsdom");

const ROOT = path.resolve(__dirname, "../..");
const PAGE = path.join(ROOT, "gui/web/index.html");

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

async function openPage({ api = {} } = {}) {
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
  // 没定义的方法要当场暴露：记进 errors，用例收尾时判红。
  // 页面里不少调用带 .catch(() => {})，只抛不加记录会被它们吞掉。
  const answer = name => {
    if (!(name in all)) {
      const error = new Error(`窗口桥没有定义 ${name}()，用例要显式给出返回值`);
      errors.push(error.message);
      throw error;
    }
    const value = all[name];
    return (...args) => (typeof value === "function" ? value(...args) : value);
  };

  window.pywebview = {
    api: new Proxy({}, { get: (_, name) => typeof name === "string" ? (...args) => Promise.resolve(answer(name)(...args)) : undefined }),
  };
  window.dispatchEvent(new window.Event("pywebviewready"));
  await flush();
  if (errors.length) throw new Error(`页面在 jsdom 里报错：${errors.map(String).join("；")}`);

  return {
    window,
    document: window.document,
    errors,
    close: () => {
      window.close();
      // 交互期间页面报的错也在这里判：漏了这一步，带 .catch(() => {}) 的调用会静默通过
      if (errors.length) throw new Error(`用例期间页面报错：${errors.map(String).join("；")}`);
    },
  };
}

module.exports = { openPage, pollResult, stepDone };
