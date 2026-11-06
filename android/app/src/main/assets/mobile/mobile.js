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

  // 图标：一套线性图标，描边随文字粗细，颜色跟 currentColor
  const svg = (d, w) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="${w || 1.75}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`;
  const I = {
    more: svg(`<circle cx="5" cy="12" r="1.4" fill="currentColor"/><circle cx="12" cy="12" r="1.4" fill="currentColor"/><circle cx="19" cy="12" r="1.4" fill="currentColor"/>`),
    phone: svg(`<rect x="6" y="2.5" width="12" height="19" rx="3"/><path d="M10.5 18.5h3"/>`),
    undo: svg(`<path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>`),
    chat: svg(`<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20.5l1.4-4.9A8 8 0 1 1 21 12Z"/>`),
    book: svg(`<path d="M4 19.5V5a2 2 0 0 1 2-2h13v15H6a2 2 0 0 0-2 2Zm0 0a2 2 0 0 0 2 2h13"/>`),
    up: svg(`<path d="M12 19V5"/><path d="m5 12 7-7 7 7"/>`),
    check: svg(`<path d="m5 12.5 4.5 4.5L19 7.5"/>`, 2.5),
    stop: svg(`<rect x="7" y="7" width="10" height="10" rx="2"/>`, 2.25),
    alert: svg(`<path d="M12 8v5"/><path d="M12 16.5v.01"/><circle cx="12" cy="12" r="9"/>`, 2.25),
    moon: svg(`<path d="M8 4h8M8 20h8M6 4v3l6 5-6 5v3M18 4v3l-6 5 6 5v3"/>`),
    shield: svg(`<path d="M12 3 5 6v5c0 4.5 3 8.3 7 10 4-1.7 7-5.5 7-10V6l-7-3Z"/><path d="m9 12 2 2 4-4"/>`),
    lock: svg(`<rect x="5" y="10.5" width="14" height="10" rx="2"/><path d="M8 10.5V8a4 4 0 0 1 8 0v2.5"/>`),
  };
  window.__aacIcon = I;

  const brand = document.querySelector(".brand");
  brand.insertAdjacentHTML("afterend", `<button class="more" aria-label="更多" onclick="openMore()">${I.more}<span class="dot hide" id="moredot"></span></button>`);
  const nv = $("#newver");
  new MutationObserver(() => $("#moredot").classList.toggle("hide", nv.classList.contains("hide"))).observe(nv, {attributes: true});
  window.openMore = function(){
    const item = (icon, text, act, cls) => `<button class="${cls || ""}" onclick="closeModal();${act}">${icon}<span>${text}</span></button>`;
    const fresh = !nv.classList.contains("hide");
    modal(`<h3>更多</h3><div class="sheet-list">
      ${fresh ? item(I.up, esc(nv.textContent), "$('#newver').click()", "newv") : ""}
      ${item(I.undo, "还原改动", "openRestore()")}
      ${item(I.chat, "反馈问题", "openFeedback()")}
      ${item(I.book, "使用说明", "api.open_url('https://github.com/rddmwmddr/android-ad-cleaner')")}
    </div><p class="sheet-ver">${esc($("#ver").textContent)}</p>`);
  };
  // 点面板外的遮罩关掉面板
  $("#modal").addEventListener("click", e => { if (e.target.id === "modal") closeModal(); });

  // 换页回到顶部
  const step = setStep;
  setStep = function(n){ step(n); main().scrollTop = 0; };

  // 首次设置的三步（#622 内置无线调试）。状态 need_dev / need_wifi / need_pair 对应第 1 / 2 / 3 步
  const SETUP = [
    ["打开开发者选项", `点下面的按钮进「关于手机」，连点「版本号」7 下（小米点「OS 版本」，vivo 在「版本信息」里点「软件版本号」），输入锁屏密码，看到「已处于开发者模式」后回到这里。`, `打开「关于手机」`, `AacHost.openSettings('about')`],
    ["打开无线调试", `手机要连着 Wi-Fi。进「开发者选项」找到「无线调试」打开，弹窗里勾选「始终允许」再点「允许」。小米 / Redmi 还要打开「USB 调试（安全设置）」，不然点不动开关。`, `打开开发者选项`, `AacHost.openSettings('dev')`],
    ["授权本 App", `安卓要求你在手机上确认一次，本 App 才能关系统里的广告开关。点「开始授权」，系统问能否截取屏幕时点「立即开始」；然后在打开的页面里点「无线调试」→「使用配对码配对设备」。本 App 会读出屏幕上的 6 位数字自己完成授权，你不用输入。<br><br>截屏只在这台手机上识别数字，不保存、不上传，授权完成就停止。这台手机授权给它自己，不连接其他设备，以后不用再做。以后重启手机或换了 Wi-Fi，本 App 会自己重新打开无线调试并连上（第一次在新网络上，系统会要你再确认一次）；正在执行时它这么做，会在通知栏说一声。`, `开始授权`, `AacHost.startPairing()`],
  ];
  const SETUP_AT = {need_dev: 0, need_wifi: 1, need_pair: 2};
  // 装了 Shizuku 的另走 Shizuku 的状态
  const SHIZUKU = {
    old: [`安卓版本太低`, `安卓 11 以下没有无线调试，要装 Shizuku 并按它的说明连一次电脑启动。`, `打开 Shizuku`, `AacHost.openShizuku()`],
    stopped: [`Shizuku 还没启动`, `打开 Shizuku 按它的说明启动（安卓 10 及以下要连一次电脑）。手机重启后要再启动一次。`, `打开 Shizuku`, `AacHost.openShizuku()`],
    ask: [`允许本 App 使用 Shizuku`, `点下面的按钮，在弹窗里选「始终允许」。`, `授权`, `AacHost.requestShizuku()`],
    denied: [`之前拒绝了 Shizuku 授权`, `打开 Shizuku →「已授权的应用」，把「安卓去广告」打开，再回到这里。`, `打开 Shizuku`, `AacHost.openShizuku()`],
  };
  const FINE = `<p class="fine">不需要 root，也不用连电脑；只在这台手机自己里面连接，不经过任何服务器。原生鸿蒙（HarmonyOS NEXT）不是安卓，装不了本 App；华为老机型与荣耀可以用。</p>`;

  showConnect = function(){
    setStep(1); clearInterval(pollDev); S.home = "";
    main().innerHTML = `<h1>一键关掉手机广告</h1>
      <p class="lead">关系统和各 App 里的广告开关、营销通知。开始前存一份快照，每一项都能还原。</p>
      <div id="shz"><div class="card"><div class="row"><span class="spin"></span>正在检查授权……</div></div></div>`;
    window.__aacShizuku();
    // 执行期间本 App 在后台，界面可能被系统回收；重新打开时后台的执行还在跑，接回执行页
    api.poll(0).then(r => { if (r && r.running && S.step === 1){ S.logNext = 0; showRun(); } }).catch(() => {});
  };

  // 查状态要等几秒（找无线调试端口），由 Kotlin 在后台查完回调 __aacState
  window.__aacShizuku = function(){
    if ($("#shz") && S.step === 1) AacHost.checkState();
  };

  // 首页整页按状态重画：标题、内容、底部主操作；状态没变（从设置页回来）不重画，免得重放渐入
  function home(key, head, lead, body, actions){
    if (S.home === key) return;
    S.home = key;
    main().innerHTML = `<h1>${head}</h1><p class="lead">${lead}</p><div id="shz">${body}</div>${actions ? `<div class="actions">${actions}</div>` : ""}`;
  }

  window.__aacState = async function(st){
    if (!$("#shz") || S.step !== 1) return;
    if (st in SETUP_AT){
      const at = SETUP_AT[st];
      home(st, "先做 3 个设置", "第一次使用要做，大约 1 分钟。以后打开就能直接用。",
        `<div class="steps">${SETUP.map(([t, d], k) => `<div class="step-row ${k < at ? "done" : k === at ? "now" : ""}">
          <span class="num">${k < at ? I.check : k + 1}</span><div class="body"><b>${t}</b>${k === at ? `<p>${d}</p>` : ""}</div></div>`).join("")}</div>${FINE}
        <div class="actions" style="justify-content:flex-start"><button class="btn plain" onclick="AacHost.requestShizuku()">已装 Shizuku？改用 Shizuku</button></div>`,
        `<button class="btn big" onclick="${SETUP[at][3]}">${SETUP[at][2]}</button>`);
      return;
    }
    if (st in SHIZUKU){
      const [t, d, b, act] = SHIZUKU[st];
      home(st, t, d, FINE, `<button class="btn big" onclick="${act}">${b}</button>`);
      return;
    }
    let d = null;
    try { d = ((await api.devices()).list || [])[0]; } catch(e){}
    if (!d){
      home("nodev", "读不到这台手机", "已经授权，但读不到手机信息。到「开发者选项」里把「无线调试」关掉再打开，然后回到这里。", FINE,
        `<button class="btn big" onclick="AacHost.openSettings('dev')">打开开发者选项</button>`);
      return;
    }
    S.local = d;
    S.serial = S.serial || d.serial; S.dev = S.dev || d;     // 「还原改动」要先有当前手机：手机版就是本机
    const name = d.name || `${d.brand} ${d.model}`;
    home("ready", "一键关掉手机广告", "关系统和各 App 里的广告开关、营销通知。",
      `<div class="dev"><div class="ico">${I.phone}</div><div class="meta"><b>${esc(name)}</b><small><span class="live"></span>${esc(d.model)} · 已就绪</small></div></div>
      <div class="card"><ul class="feats">
        <li>${I.moon}<span><b>可以照常用手机</b><small>多数手机上在一块看不见的后台屏里点按，做完发通知。不支持的手机会借用当前屏幕，那时请不要碰手机。</small></span></li>
        <li>${I.shield}<span><b>先存快照，都能还原</b><small>右上角「更多 → 还原改动」可以把关掉的项目打开。</small></span></li>
        <li>${I.lock}<span><b>只在这台手机上进行</b><small>不需要 root，不连电脑，不经过任何服务器。</small></span></li>
      </ul></div>`,
      `<button class="btn plain" onclick="S.auto=false;pick(S.local)">自己选择要关的</button><button class="btn big" onclick="oneTap()">一键去广告</button>`);
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
  // 日志默认收起：普通用户看进度条和当前步骤就够
  showRun = function(){
    run();
    const log = $("#log");
    if (log && !log.closest("details")){
      const box = document.createElement("details");
      box.className = "more-log";
      box.innerHTML = "<summary>详细记录</summary>";
      log.parentNode.insertBefore(box, log);
      box.appendChild(log);
    }
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

  // 完成页：顶部状态图标；底部「重新开始 / 回到首页」（#632：手机版没有侧栏，停止后回不去）
  const done = showDone;
  showDone = function(r){
    done(r);
    const ok = r.results.every(x => x.rc === 0) && !r.cancel;
    const failed = r.results.some(x => x.rc !== 0 && !x.stopped);
    const h1 = main().querySelector("h1");
    h1.insertAdjacentHTML("beforebegin", `<div class="hero"><span class="badge ${ok ? "ok" : failed ? "bad" : "warn"}">${ok ? I.check : failed ? I.alert : I.stop}</span></div>`);
    // 关开发者模式是建议，不是这一页的主操作
    main().querySelectorAll(".card .row .btn:not(.plain)").forEach(b => b.classList.add("ghost"));
    main().insertAdjacentHTML("beforeend", ok
      ? `<div class="actions"><button class="btn plain" onclick="oneTap()">再做一次</button><button class="btn big" onclick="showConnect()">完成</button></div>`
      : `<div class="actions"><button class="btn plain" onclick="showConnect()">回到首页</button><button class="btn big" onclick="oneTap()">重新开始</button></div>`);
    main().querySelectorAll(".card p.lead").forEach(p => {
      p.innerHTML = p.innerHTML
        .replace("若还要排查或重试，请先保留 USB 调试", "若还要排查或重试，请先保留开发者模式")
        .replace("若不再使用电脑调试，建议关闭开发者模式和 USB 调试。", "若暂时不再用本 App，建议关闭开发者模式（无线调试随之关闭；下次用时打开开发者选项和无线调试即可，不用再配对）。");
    });
  };

  window.dispatchEvent(new Event("pywebviewready"));
})();
