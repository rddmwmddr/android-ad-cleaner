const test = require('node:test');
const assert = require('node:assert/strict');
const {openPage} = require('./page');
const flush = () => new Promise(resolve => setTimeout(resolve, 0));
const available = {state:'available', version:'0.4.2', source:'gitee', busy:false, can_download:true};

test('in-app update defaults to Gitee, can switch to GitHub and install after verification', async () => {
  const calls = [];
  const p = await openPage({api:{
    check_update: () => available,
    update_state: () => available,
    download_update: source => {calls.push(['download',source]); return {...available,state:'ready',can_install:true,message:'校验通过'};},
    install_update: () => {calls.push(['install']); return {...available,state:'error',can_install:true,error:'正在执行去广告，请稍后'};},
  }});
  try {
    assert.match(p.document.querySelector('#newver').textContent, /0.4.2/);
    p.document.querySelector('#newver').click(); await flush();
    const selector = p.document.querySelector('#update-source');
    assert.equal(selector.value, 'gitee');
    selector.value = 'github'; selector.dispatchEvent(new p.window.Event('change'));
    [...p.document.querySelectorAll('#modal button')].find(b=>b.textContent==='下载更新').click(); await flush();
    assert.deepEqual(calls,[['download','github']]);
    assert.match(p.document.querySelector('#modal').textContent,/校验通过/);
    [...p.document.querySelectorAll('#modal button')].find(b=>b.textContent==='安装并重启').click(); await flush();
    assert.deepEqual(calls,[['download','github'],['install']]);
    assert.match(p.document.querySelector('[role=alert]').textContent,/正在执行/);
  } finally {p.close();}
});

test('download progress and cancel are inside the app; late polling does not replace another modal', async () => {
  let cancel = 0;
  const state = {...available,state:'downloading',busy:true,can_download:false,can_cancel:true,size:200,received:100};
  const p = await openPage({api:{check_update:()=>state,update_state:()=>state,
    cancel_update:()=>{cancel++;return {...available,message:'已取消下载'};}}});
  try {
    p.window.openUpdates(); await flush();
    assert.equal(p.document.querySelector('progress').value,50);
    assert.equal(p.document.querySelector('#update-source').disabled,true);
    [...p.document.querySelectorAll('#modal button')].find(b=>b.textContent==='取消下载').click();await flush();
    assert.equal(cancel,1);
    p.window.modal('<h3>another modal</h3>');
    await p.window.updateAction('update_state');
    assert.match(p.document.querySelector('#modal').textContent,/another modal/);
  } finally {p.close();}
});
