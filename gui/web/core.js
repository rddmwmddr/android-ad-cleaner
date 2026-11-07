/* 纯逻辑面（#647）：index.html 的内联脚本从 window.GuiCore 取用，
   tests/js 用 require 直接加载同一份代码——行为变化在这里被测试守住。 */
const GuiCore = {
  /* 执行页是否该进完成页。停在第一步时还没有结果，也要进完成页（#632）：
     停止（r.cancel）或跑完有结果，否则执行页一直停着、没有出口。 */
  shouldFinish(r) {
    return Boolean(!r.running && r.results && (r.results.length || r.cancel));
  },

  /* 完成页每一项的一句话总结：按日志尾部各落点的措辞认领，认不出就回退到
     最后一个非空行。 */
  summarize(res) {
    const t = res.tail.join("\n");
    let m;
    if ((m = t.match(/机型脚本跑完：关了 (\d+) 个，(\d+) 秒/))) return `关了 ${m[1]} 个开关`;
    if ((m = t.match(/拨了 (\d+) 个/))) {
      const left = (t.match(/仍开着: (\d+) 个/) || [])[1];
      return `关了 ${m[1]} 个渠道` + (left !== undefined ? `，复查仍开着 ${left} 个` : "");
    }
    if (/快应用组件已关闭/.test(t)) return `${(t.match(/已关闭$/gm) || []).length} 个组件已关闭`;
    if (/快照已存/.test(t)) return "已保存";
    if ((m = t.match(/插电常亮已改回 (\d+)/))) return `插电常亮已改回 ${m[1]}`;
    if (/插电常亮未改动/.test(t)) return "插电常亮未改动";
    return res.tail.filter(Boolean).slice(-1)[0] || "";
  },
};

/* Node 测试走 require；页面里 window.GuiCore 供内联脚本取用。 */
if (typeof module === "object" && module.exports) module.exports = GuiCore;
if (typeof window === "object") window.GuiCore = GuiCore;
