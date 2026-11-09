const test = require('node:test');
const assert = require('node:assert/strict');
const {openPage} = require('./page');
const flush = () => new Promise(resolve => setTimeout(resolve, 0));
const device = {serial:'second', platform:'harmony', name:'鸿蒙测试机', model:'HOP-AL10', state:'Connected', supported:true};
function snapshot(extra={}){
  return {phase:'idle', mode:'clean', device, can_restore:true, message:'', lines:[],
    segments:[{id:'ads',name:'系统广告',status:'waiting',note:'',rows:[{title:'个性化广告',want:false,result:''}]},
      {id:'track',name:'跨应用关联',status:'waiting',note:'',rows:[{title:'要求应用请求关联',want:true,result:''}]}], ...extra};
}

test('没有 adb 也能列出和选择鸿蒙手机，不会调用安卓检测', async t => {
  const calls=[];
  const page=await openPage({api:{
    env:()=>({version:'test',adb:false,harmony:true}),
    harmony:(action,serial)=>{
      calls.push([action,serial]);
      return action==='devices' ? {list:[device]} : snapshot();
    },
  }});
  t.after(page.close);
  await flush();
  assert.match(page.document.querySelector('#harmonydevbox').textContent,/鸿蒙测试机/);
  page.document.querySelector('#harmonydevbox button').click();
  await flush();
  assert.ok(calls.some(([a,s])=>a==='select' && s==='second'));
  assert.match(page.document.querySelector('main').textContent,/跨应用关联/);
  assert.match(page.document.querySelector('main').textContent,/旧鸿蒙客户端/);
});

test('分组选择传给鸿蒙桥，运行中只能安全停止', async t => {
  const calls=[];
  const page=await openPage({api:{
    harmony:(action,serial,mode,segments)=>{
      calls.push([action,serial,mode,segments]);
      if(action==='select') return snapshot();
      if(action==='start') return {ok:true};
      return snapshot({phase:'running'});
    },
  }});
  t.after(page.close);
  await page.window.showHarmony('second');
  page.document.querySelector('input[value="ads"]').checked=false;
  await page.window.startHarmony();
  const start=calls.find(x=>x[0]==='start');
  assert.equal(start[1],'second');
  assert.equal(start[2],'clean');
  assert.deepEqual(Array.from(start[3]),['track']);
  assert.equal(page.document.querySelector('#harmony-actions').textContent.trim(),'停止');
  page.document.querySelector('#harmony-actions button').click();
  await flush();
  assert.ok(calls.some(([a])=>a==='stop'),'停止按钮必须调用鸿蒙桥的 stop');
});

test('还原必须确认且不会调用安卓还原入口', async t => {
  const calls=[];
  const page=await openPage({api:{
    harmony:(action,serial,mode)=>{calls.push([action,serial,mode]);return action==='start'?{ok:true}:snapshot();},
  }});
  t.after(page.close);
  await page.window.showHarmony('second');
  page.window.openRestore();
  assert.match(page.document.querySelector('#modalbox').textContent,/还原鸿蒙改动/);
  assert.equal(calls.filter(x=>x[0]==='start').length,0);
  [...page.document.querySelectorAll('#modalbox button')].find(b=>b.textContent==='开始还原').click();
  await flush();
  assert.ok(calls.some(([a,s,m])=>a==='start' && s==='second' && m==='restore'));
});

async function lateDeviceResult(t, switchAway){
  let resolve;
  const pending=new Promise(r=>resolve=r);
  const page=await openPage({api:{
    env:()=>({version:'test',adb:false,harmony:true}),
    harmony:()=>pending,
  }});
  t.after(page.close);
  page.window.eval(`S.deviceKind='android'; setStep(1); main().innerHTML='<div id="harmonydevbox"></div>'; refreshHarmonyDevices()`);
  await flush();
  page.window.eval(switchAway);
  resolve({list:[device]});
  await flush();
  return page.document.querySelector('#harmonydevbox').textContent;
}

test('改场次后迟到的设备结果被 epoch 守卫丢弃', async t => {
  assert.equal(await lateDeviceResult(t,'harmonyEpoch++'),'');
});

test('离开连接页后迟到的设备结果被步骤守卫丢弃', async t => {
  assert.equal(await lateDeviceResult(t,'setStep(2)'),'');
});

test('运行失败明确显示未完成和单段重试入口', async t => {
  const state=snapshot({phase:'done', message:'手机连接或读屏中断，请重新连接后重试。'});
  state.segments[0].status='partial';
  state.segments[1].status='done';
  const page=await openPage({api:{harmony:()=>state}});
  t.after(page.close);
  await page.window.showHarmony('second');
  const text=page.document.querySelector('main').textContent;
  assert.match(text,/部分未完成/);
  assert.match(text,/仅重试未完成/);
  assert.match(text,/开发者选项/);
});

test('启动后的首次进度读取失败仍会轮询，确认结束后才停止', async t => {
  let polls=0;
  const ticks=[], cleared=[];
  const page=await openPage({api:{harmony:action=>{
    if(action==='select') return snapshot();
    if(action==='start') return {ok:true};
    if(action==='poll'){
      polls++;
      if(polls===1) throw new Error('temporary bridge failure');
      return snapshot({phase:polls===2?'running':'done'});
    }
  }}});
  t.after(page.close);
  await page.window.showHarmony('second');
  page.window.setInterval=fn=>{ticks.push(fn);return 73;};
  page.window.clearInterval=id=>cleared.push(id);
  await page.window.startHarmony();
  assert.match(page.document.querySelector('#harmony-message').textContent,/正在重试/);
  assert.equal(ticks.length,1);
  assert.ok(!cleared.includes(73));
  await ticks[0]();
  assert.equal(page.document.querySelector('#harmony-actions').textContent.trim(),'停止');
  await ticks[0]();
  assert.ok(cleared.includes(73));
  assert.equal(polls,3);
});
