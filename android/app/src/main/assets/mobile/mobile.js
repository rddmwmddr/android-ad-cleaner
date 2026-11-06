/* 手机版：页面加载完由 MainActivity 注入。
   1) pywebview 桥：api.xxx(...) → AacHost.call → Python 的 aac_android.main.call，结果经 __aacDone 回来；
   2) 首页换成 Shizuku 状态 + 「一键去广告」：自动走检测 → 扫描 → 开始执行，勾选与桌面版默认一致；
   3) 桌面专属的入口（adb 设置、打开备份文件夹）隐藏，「插着线」「电脑」类文案改成手机上的说法。 */
(function(){
  if (window.__aacMobile) return;
  window.__aacMobile = true;

  const pending = {};
  let seq = 0;
  window.__aacDone = (id, json) => {
    const p = pending[id]; delete pending[id];
    if (!p) return;
    const r = JSON.parse(json);
    if ("ok" in r) p.resolve(r.ok); else p.reject(new Error(r.error));
  };
  const bridge = new Proxy({}, {get: (_, m) => (...args) => new Promise((resolve, reject) => {
    const id = ++seq; pending[id] = {resolve, reject};
    AacHost.call(id, String(m), JSON.stringify(args));
  })});
  window.pywebview = {api: bridge};

  document.querySelectorAll(".side-foot .link").forEach(b => {
    const on = b.getAttribute("onclick") || "";
    if (on.includes("open_path") || on.includes("openSettings")) b.classList.add("hide");
  });

  const SHZ = {
    missing: [`需要先装 Shizuku`, `Shizuku 是免费开源的权限工具，让本 App 获得和电脑上 adb 一样的权限，不需要 root、不用连电脑。装好后回到这里。`, `下载 Shizuku`],
    stopped: [`Shizuku 还没启动`, `打开 Shizuku，按「通过无线调试启动」的说明启动（要连着 Wi-Fi，并在开发者选项里打开「无线调试」）。手机重启后要再启动一次。小米 / Redmi 还要在开发者选项里打开「USB 调试（安全设置）」，不然点不动开关。`, `打开 Shizuku`],
    old: [`Shizuku 版本太旧`, `请把 Shizuku 更新到最新版后回到这里。`, `打开 Shizuku`],
    ask: [`授权本 App 使用 Shizuku`, `点下面的按钮，在弹窗里选「始终允许」。`, `授权`],
    denied: [`之前拒绝了授权`, `打开 Shizuku →「已授权的应用」，把「安卓去广告」打开，再回到这里。`, `打开 Shizuku`],
  };

  showConnect = function(){
    setStep(1); clearInterval(pollDev);
    main().innerHTML = `<h1>安卓去广告</h1>
      <p class="lead">在这台手机上直接关：系统和各 App 里的广告开关、营销通知。开始前存一份快照，每一项都能还原。</p>
      <div id="shz"><div class="card"><div class="row"><span class="spin"></span>正在检查……</div></div></div>`;
    window.__aacShizuku();
    // 执行期间本 App 在后台，界面可能被系统回收；重新打开时后台的执行还在跑，接回执行页
    api.poll(0).then(r => { if (r && r.running && S.step === 1){ S.logNext = 0; showRun(); } }).catch(() => {});
  };

  window.__aacShizuku = async function(){
    const box = $("#shz");
    if (!box || S.step !== 1) return;
    const st = AacHost.shizuku();
    if (st !== "ready"){
      const [t, d, b] = SHZ[st] || SHZ.stopped;
      const act = st === "ask" ? "AacHost.requestShizuku()" : "AacHost.openShizuku()";
      box.innerHTML = `<div class="card"><h3>${t}</h3><p class="lead" style="margin:0 0 14px">${d}</p>
        <button class="btn big" onclick="${act}">${b}</button></div>
        <div class="note info">原生鸿蒙（HarmonyOS NEXT）不是安卓，装不了本 App；华为老机型与荣耀可以用。</div>`;
      return;
    }
    let d = null;
    try { d = ((await api.devices()).list || [])[0]; } catch(e){}
    if (!d){ box.innerHTML = `<div class="note bad">Shizuku 已授权，但读不到这台手机的信息。到 Shizuku 里停止后重新启动，再回到这里。</div>`; return; }
    S.local = d;
    S.serial = S.serial || d.serial; S.dev = S.dev || d;     // 「还原改动」要先有当前手机：手机版就是本机
    const name = d.name || `${d.brand} ${d.model}`;
    box.innerHTML = `<div class="dev"><div class="ico">📱</div><div class="meta"><b>${esc(name)}</b><small>${esc(d.model)} · Shizuku 已连接</small></div></div>
      <button class="btn big" onclick="oneTap()">一键去广告</button>
      <p class="lead" style="margin:12px 0 0">点了以后自动检测、扫描营销通知，按推荐勾选直接开始。多数手机上会在一块看不见的后台屏里自动点按，你可以照常用手机，做完发通知；不支持后台屏的手机会借用当前屏幕，那时<b>请不要碰手机</b>。</p>
      <div class="actions" style="justify-content:flex-start"><button class="btn plain" onclick="S.auto=false;pick(S.local)">自己选择要关的项目</button></div>`;
  };

  window.oneTap = function(){ S.auto = true; pick(S.local); };

  const detect = showDetect;
  showDetect = async function(){
    await detect();
    if (!S.auto) return;
    const next = [...main().querySelectorAll(".actions .btn")].find(b => b.textContent === "下一步");
    if (next && !next.disabled) showChoose(); else S.auto = false;
  };

  const choose = showChoose;
  showChoose = async function(){
    const auto = S.auto;
    const ready = choose();
    main().querySelectorAll(".note.info").forEach(n => {
      if (n.textContent.includes("插着线")) n.textContent = "执行期间本 App 会切到各个设置页自动点按，请不要碰手机，保持亮屏。";
    });
    await ready;
    if (auto && S.auto && S.step === 3){ S.auto = false; go(); }
  };

  askDevOff = function(){
    modal(`<h3>关闭开发者模式？</h3><p class="lead">关闭后无线调试一起关掉，Shizuku 随之停止。以后要还原改动，重新打开开发者模式和无线调试、启动 Shizuku 即可。</p>
      <div class="actions"><button class="btn plain" onclick="closeModal()">取消</button><button class="btn" onclick="devOff()">关闭</button></div>`);
  };

  // 执行页：能在后台屏上跑（#618）就告诉用户可以照常用手机；建不了屏的手机仍提示别碰
  const run = showRun;
  showRun = function(){
    run();
    setTimeout(() => api.run_mode().then(m => {
      const lead = main().querySelector("p.lead");
      if (m && m.background && lead && S.step === 4)
        lead.textContent = "在一块看不见的后台屏上逐项关闭，你可以照常用手机。做完会发通知。要看进度，回到这里。";
    }).catch(() => {}), 2500);
  };

  // 完成页：去掉「电脑调试」「USB 调试」的说法
  const done = showDone;
  showDone = function(r){
    done(r);
    main().querySelectorAll(".card p.lead").forEach(p => {
      p.innerHTML = p.innerHTML
        .replace("若还要排查或重试，请先保留 USB 调试", "若还要排查或重试，请先保留开发者模式")
        .replace("若不再使用电脑调试，建议关闭开发者模式和 USB 调试。", "若暂时不再用本 App，建议关闭开发者模式（Shizuku 会随之停止，下次用时重新启动）。");
    });
  };

  window.dispatchEvent(new Event("pywebviewready"));
})();
