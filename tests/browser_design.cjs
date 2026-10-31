// Requires the same isolated server and credentials as browser_audit.cjs.
const {chromium,request}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const base=process.env.AUDIT_URL||'http://127.0.0.1:8766';
const out=process.env.AUDIT_OUTPUT||'/private/tmp/elevator-style-qa';
(async()=>{
 fs.mkdirSync(out,{recursive:true});
 const api=await request.newContext({baseURL:base});
 const credentials={username:'audit',password:'audit-password-123'};
 assert.equal((await api.post('/api/login',{data:credentials})).status(),200);
 const day=new Date().toISOString().slice(0,10);
 const shift=n=>new Date(Date.now()+n*86400000).toISOString().slice(0,10);
 async function post(path,data){const r=await api.post(path,{data});assert.equal(r.status(),200,await r.text());return r.json()}
 let elevators=await (await api.get('/api/elevators')).json();
 let lift=elevators.find(e=>e.building_name==='18栋');
 if(!lift){
  for(let building=18;building<=20;building++)for(let unit=1;unit<=2;unit++)for(let number=1;number<=2;number++){
   const created=await post('/api/elevators',{building_name:building+'栋',unit_name:unit+'单元',name:number+'号梯',equipment_number:`YFD-${building}-${unit}-${number}`,brand:'演示品牌',model:'示例型号',maintenance_company:'宜方达合作维保单位',maintenance_contact:'张师傅',maintenance_phone:'13800000000',maintenance_due_on:shift(number===1?-2:12),inspection_on:shift(20),status:building===20?'维修中':'正常'});
   if(building===18&&unit===1&&number===1)lift={id:created.id};
  }
  for(const [i,type] of ['维修','日常维保','故障','配件更换','检验/检查','资料补充','其他'].entries()){
   await post('/api/events',{elevator_id:lift.id,type,title:['更换门锁开关，完成试运行','完成半月维保与运行检查','厅门异常，现场检查处理中','更换控制板并登记质保','完成电梯运行检查','补充检验资料','机房现场情况登记'][i],occurred_on:shift(-i),work_content:'检查厅门、门锁与控制系统，完成现场核验并登记。',workers:'张师傅',company:'宜方达合作维保单位',completed:type!=='故障',parts:type==='配件更换'?[{name:'控制板',quantity:1,unit_price_yuan:'300',replaced_on:shift(-365),warranty_days:370}]:[]});
  }
 }
 const info=await (await api.get('/api/network')).json();let lan='';
 for(const candidate of info.candidates){try{const check=await api.get(candidate+'/api/health',{timeout:3000});if(check.ok()){lan=candidate;break}}catch{}}
 assert.ok(lan,'Need a reachable LAN interface for deep-link testing');
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
 try{
  const context=await browser.newContext({viewport:{width:1500,height:1060},storageState:await api.storageState()});
  await context.addInitScript(()=>{for(const name of ['toSorted','toReversed','toSpliced'])delete Array.prototype[name];delete Object.groupBy;delete Promise.withResolvers;});
  const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base+'/admin');await page.getByLabel('局域网访问地址',{exact:true}).fill(lan);
  const saveResponse=page.waitForResponse(r=>r.url().endsWith('/api/network')&&r.request().method()==='PUT');await page.getByRole('button',{name:'保存访问地址',exact:true}).click();assert.equal((await saveResponse).status(),200);await page.getByText('已保存',{exact:true}).waitFor();
  assert.equal((await (await api.get('/api/network')).json()).configured_url,lan);
  const screens=[['home','/','.home-hero'],['archives','/elevators','.elevator-grid'],['detail','/elevators/'+lift.id,'.timeline-item'],['new-record','/events/new?elevator_id='+lift.id,'.form-panel'],['records','/records','.records-layout'],['reminders','/reminders','.list-row'],['export','/export','.archive-select-layout'],['search','/search?q=18栋%20门锁','.search-summary'],['search-empty','/search','.search-intro'],['admin','/admin','.network-settings form']];
  for(const [name,path,ready] of screens){
   await page.setViewportSize({width:1500,height:1060});await page.goto(base+path);await page.locator(ready).first().waitFor();await page.waitForFunction(()=>!document.querySelector('.el-button.is-loading'));await page.evaluate(async()=>{await Promise.all([...document.images].filter(i=>i.offsetParent!==null).map(i=>i.decode()))});await page.screenshot({path:out+'/'+name+'-desktop.png',fullPage:true});
   for(const width of [390,320]){await page.setViewportSize({width,height:844});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),name+' overflow at '+width);if(width===390)await page.screenshot({path:out+'/'+name+'-mobile.png',fullPage:true})}
  }
  await page.setViewportSize({width:390,height:844});await page.getByRole('button',{name:'菜单 ☰',exact:true}).click();await page.getByRole('navigation',{name:'主菜单'}).getByRole('button',{name:'电梯档案',exact:true}).click();await page.waitForURL('**/elevators');assert.equal(await page.locator('.main-nav').isVisible(),false);
  await page.getByRole('button',{name:'＋ 新增电梯',exact:true}).click();await page.getByRole('dialog').waitFor();assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.screenshot({path:out+'/new-elevator-mobile.png',fullPage:true});await page.locator('.el-dialog__headerbtn').click();
  await page.setViewportSize({width:1500,height:1060});await page.goto(base+'/elevators/'+lift.id);await page.getByRole('button',{name:'查看、下载与打印',exact:true}).click();await page.getByRole('dialog').waitFor();assert.equal(await page.locator('.qr-label .qr-target').innerText(),lan+'/elevators/'+lift.id);
  await page.locator('.qr-configuration summary').click();await page.getByLabel('主机局域网访问地址',{exact:true}).fill('http://127.0.0.1:8765');await page.getByRole('button',{name:'保存访问地址',exact:true}).click();await page.getByText('不能填写 127.0.0.1',{exact:false}).waitFor();assert.equal((await (await api.get('/api/network')).json()).configured_url,lan);
  await page.getByLabel('主机局域网访问地址',{exact:true}).fill(lan);
  await page.locator('.qr-configuration summary').click();await page.getByRole('dialog').screenshot({path:out+'/qr-desktop.png'});
  const download=page.waitForEvent('download');await page.getByRole('button',{name:'下载二维码图片',exact:true}).click();await (await download).saveAs(out+'/qr.png');assert.ok(fs.statSync(out+'/qr.png').size>300);
  await page.evaluate(()=>{window.print=()=>{window.__printed=true}});await page.getByRole('button',{name:'打印电梯标签',exact:true}).click();await page.waitForFunction(()=>window.__printed===true);await page.emulateMedia({media:'print'});assert.equal(await page.locator('.qr-print-sheet').isVisible(),true);assert.equal(await page.locator('.shell').isVisible(),false);await page.locator('.qr-print-sheet').screenshot({path:out+'/qr-label.png'});await page.pdf({path:out+'/qr-label.pdf',format:'A4',printBackground:true});await page.emulateMedia({media:'screen'});
  await page.setViewportSize({width:390,height:844});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.screenshot({path:out+'/qr-mobile.png',fullPage:true});
  const scanned=await browser.newContext({viewport:{width:390,height:844}});const scan=await scanned.newPage();scan.on('pageerror',e=>errors.push(e.message));
  await scan.goto(lan+'/elevators/'+lift.id);await scan.getByText('登录后将直接打开扫码对应的电梯档案。').waitFor();await scan.screenshot({path:out+'/scan-login-mobile.png',fullPage:true});
  await scan.getByLabel('账号',{exact:true}).fill(credentials.username);await scan.getByLabel('密码',{exact:true}).fill(credentials.password);await scan.getByRole('button',{name:'登录',exact:true}).click();await scan.getByRole('heading',{name:'18栋1单元1号梯',exact:true}).waitFor();assert.equal(scan.url(),lan+'/elevators/'+lift.id);await scan.locator('.timeline-item').first().waitFor();await scan.screenshot({path:out+'/scan-detail-mobile.png',fullPage:true});
  await scan.reload();await scan.getByRole('heading',{name:'18栋1单元1号梯',exact:true}).waitFor();
  await scan.goto(lan+'/elevators/999999');await scan.getByText('找不到这部电梯',{exact:false}).first().waitFor();assert.equal(await scan.locator('.detail-heading').count(),0);
  const signedOut=await browser.newContext({viewport:{width:1500,height:1060}});const login=await signedOut.newPage();await login.goto(base);await login.getByRole('button',{name:'登录',exact:true}).waitFor();await login.screenshot({path:out+'/login-desktop.png',fullPage:true});
  assert.deepEqual(errors,[]);console.log('PASS: 10 desktop pages, 390/320px overflow checks, mobile menu/dialog, persisted LAN setting, reject loopback, QR download and print-only label, fresh LAN-origin login preserves elevator and reload, missing elevator, login design. LAN '+lan+'; Chrome '+browser.version());
 }finally{await browser.close();await api.dispose()}
})().catch(e=>{console.error(e);process.exit(1)});
