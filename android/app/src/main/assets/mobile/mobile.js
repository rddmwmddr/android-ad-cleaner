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

  // 权限状态 → [标题, 说明, 按钮, 按钮动作]。默认走内置无线调试（#622），不用另装 App；装了并授权 Shizuku 的也认
  const STEP = {
    need_dev: [`第 1 步：打开开发者选项`, `点下面的按钮进「关于手机」，连点「版本号」7 次（小米点「OS 版本」，vivo 在「版本信息」里点「软件版本号」），输入锁屏密码，看到「已处于开发者模式」后回到这里。`, `打开「关于手机」`, `AacHost.openSettings('about')`],
    need_wifi: [`第 2 步：打开无线调试`, `手机要连着 Wi-Fi。点下面的按钮进「开发者选项」，找到「无线调试」打开，弹窗选「允许」，然后回到这里。小米 / Redmi 顺便打开「USB 调试（安全设置）」，不然点不动开关。`, `打开开发者选项`, `AacHost.openSettings('dev')`],
    need_pair: [`第 3 步：配对一次（以后不用再配）`, `点下面的按钮，进「无线调试」→「使用配对码配对设备」，屏幕上会出现 6 位配对码。不要关掉它，下拉通知栏，在「安卓去广告」的通知里点「填写配对码」，把 6 位数字填进去。`, `开始配对`, `AacHost.startPairing()`],
    old: [`这台手机的安卓版本低于 11`, `安卓 11 起才有无线调试。可以装 Shizuku（免费开源）用电脑启动一次，或者直接用电脑版。`, `下载 Shizuku`, `AacHost.openShizuku()`],
    stopped: [`Shizuku 还没启动`, `打开 Shizuku 按它的说明启动（安卓 10 及以下要连一次电脑）。手机重启后要再启动一次。`, `打开 Shizuku`, `AacHost.openShizuku()`],
    ask: [`授权本 App 使用 Shizuku`, `点下面的按钮，在弹窗里选「始终允许」。`, `授权`, `AacHost.requestShizuku()`],
    denied: [`之前拒绝了 Shizuku 授权`, `打开 Shizuku →「已授权的应用」，把「安卓去广告」打开，再回到这里。`, `打开 Shizuku`, `AacHost.openShizuku()`],
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

  // 查状态要等几秒（找无线调试端口），由 Kotlin 在后台查完回调 __aacState
  window.__aacShizuku = function(){
    if ($("#shz") && S.step === 1) AacHost.checkState();
  };

  window.__aacState = async function(st){
    const box = $("#shz");
    if (!box || S.step !== 1) return;
    if (st !== "ready"){
      const [t, d, b, act] = STEP[st] || STEP.need_pair;
      box.innerHTML = `<div class="card"><h3>${t}</h3><p class="lead" style="margin:0 0 14px">${d}</p>
        <button class="btn big" onclick="${act}">${b}</button></div>
        <p class="lead" style="margin:0">全程不需要 root，也不用连电脑。只在这台手机自己的网络里连接，不经过任何服务器。</p>
        <div class="note info" style="margin-top:12px">原生鸿蒙（HarmonyOS NEXT）不是安卓，装不了本 App；华为老机型与荣耀可以用。</div>`;
      return;
    }
    let d = null;
    try { d = ((await api.devices()).list || [])[0]; } catch(e){}
    if (!d){ box.innerHTML = `<div class="note bad">已连接，但读不到这台手机的信息。到「开发者选项」里把「无线调试」关掉再打开，然后回到这里。</div>`; return; }
    S.local = d;
    S.serial = S.serial || d.serial; S.dev = S.dev || d;     // 「还原改动」要先有当前手机：手机版就是本机
    const name = d.name || `${d.brand} ${d.model}`;
    box.innerHTML = `<div class="dev"><div class="ico">📱</div><div class="meta"><b>${esc(name)}</b><small>${esc(d.model)} · 已连接</small></div></div>
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

  // 执行页：能在后台屏上跑（#618）就告诉用户可以照常用手机；建不了屏的手机仍提示别碰。
  // 建屏最长 8 秒，执行线程起来后也要一会儿才有结论：每秒问一次，到 deciding 为 false 为止（最多 15 秒）
  const run = showRun;
  showRun = function(){
    run();
    const until = Date.now() + 15000;
    const ask = () => {
      const again = () => { if (Date.now() < until) setTimeout(ask, 1000); };
      api.run_mode().then(m => {
        if (!m || S.step !== 4) return;
        const lead = main().querySelector("p.lead");
        if (m.background && lead)
          lead.textContent = "在一块看不见的后台屏上逐项关闭，你可以照常用手机。做完会发通知。要看进度，回到这里。";
        if (m.deciding) again();
      }).catch(again);
    };
    setTimeout(ask, 1000);
  };

  // 完成页：去掉「电脑调试」「USB 调试」的说法
  const done = showDone;
  showDone = function(r){
    done(r);
    main().querySelectorAll(".card p.lead").forEach(p => {
      p.innerHTML = p.innerHTML
        .replace("若还要排查或重试，请先保留 USB 调试", "若还要排查或重试，请先保留开发者模式")
        .replace("若不再使用电脑调试，建议关闭开发者模式和 USB 调试。", "若暂时不再用本 App，建议关闭开发者模式（无线调试随之关闭；下次用时打开开发者选项和无线调试即可，不用再配对）。");
    });
  };

  window.dispatchEvent(new Event("pywebviewready"));
})();
