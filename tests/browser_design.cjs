// Requires the same isolated server as browser_audit.cjs.
const {chromium,request}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const base=process.env.AUDIT_URL||'http://127.0.0.1:8767';
const out=process.env.AUDIT_OUTPUT||'/private/tmp/elevator-style-qa';
const endpoint=new URL(base);
assert.ok(['127.0.0.1','[::1]','localhost'].includes(endpoint.hostname)&&!['8765','8766'].includes(endpoint.port),
 'Browser regression requires a loopback URL on a non-production port');
(async()=>{
 fs.mkdirSync(out,{recursive:true});
 const api=await request.newContext({baseURL:base});
 assert.equal((await api.get('/api/health')).status(),200,'Isolated loopback server must be healthy');


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
 // Synthetic setting: validate persistence and QR contents without contacting a LAN interface.
 // Real LAN reachability and phone scanning require on-site acceptance.
 const lan='http://192.168.1.20:8766';
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
 try{
  const context=await browser.newContext({viewport:{width:1500,height:1060}});
  await context.addInitScript(()=>{for(const name of ['toSorted','toReversed','toSpliced'])delete Array.prototype[name];delete Object.groupBy;delete Promise.withResolvers;});
  const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
  const requestedPaths=[];page.on('request',request=>requestedPaths.push(new URL(request.url()).pathname));
  await page.goto(base+'/admin');await page.getByLabel('局域网访问地址',{exact:true}).fill(lan);
  const saveResponse=page.waitForResponse(r=>r.url().endsWith('/api/network')&&r.request().method()==='PUT');await page.getByRole('button',{name:'保存访问地址',exact:true}).click();assert.equal((await saveResponse).status(),200);await page.getByText('已保存',{exact:true}).waitFor();
  assert.equal((await (await api.get('/api/network')).json()).configured_url,lan);
  const screens=[['home','/','.home-hero'],['archives','/elevators','.elevator-grid'],['detail','/elevators/'+lift.id,'.timeline-item'],['new-record','/events/new?elevator_id='+lift.id,'.form-panel'],['records','/records','.operation-workspace'],['reminders','/reminders','.list-row'],['export','/export','.archive-select-layout'],['search','/search?q=18栋%20门锁','.search-summary'],['search-empty','/search','.search-intro'],['admin','/admin','.network-settings form']];
  for(const [name,path,ready] of screens){
   requestedPaths.length=0;
   await page.setViewportSize({width:1500,height:1060});await page.goto(base+path);await page.locator(ready).first().waitFor();await page.waitForFunction(()=>!document.querySelector('.el-button.is-loading'));await page.evaluate(async()=>{await Promise.all([...document.images].filter(i=>i.offsetParent!==null).map(i=>i.decode()))});await page.screenshot({path:out+'/'+name+'-desktop.png',fullPage:true});
   for(const width of [390,320]){await page.setViewportSize({width,height:844});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),name+' overflow at '+width);if(width===390)await page.screenshot({path:out+'/'+name+'-mobile.png',fullPage:true})}
   assert.ok(!requestedPaths.some(path=>['/api/me','/api/login','/api/setup/status','/api/users'].includes(path)));
   if(name==='search'||name==='search-empty') assert.ok(!requestedPaths.includes('/api/elevators'),name+' requested the full ledger');
  }
  await page.setViewportSize({width:390,height:844});await page.getByRole('button',{name:'菜单 ☰',exact:true}).click();await page.getByRole('navigation',{name:'主菜单'}).getByRole('button',{name:'电梯档案',exact:true}).click();await page.waitForURL('**/elevators');assert.equal(await page.locator('.main-nav').isVisible(),false);
  const usedBuildings=new Set((await (await api.get('/api/buildings')).json()).map(item=>item.name));
  let fixtureRound=0, firstBuilding='2', lastBuilding='10';
  while(usedBuildings.has(firstBuilding+'栋')||usedBuildings.has(lastBuilding+'栋')){
   fixtureRound++;
   firstBuilding='2'+fixtureRound;
   lastBuilding='10'+fixtureRound;
  }
  const firstLift={building_name:firstBuilding+'栋',unit_name:'2单元',name:'1号梯'};
  await post('/api/elevators',firstLift);
  const tenthEntrance=await post('/api/elevators',{...firstLift,unit_name:'10单元'});
  await post('/api/elevators',{...firstLift,building_name:lastBuilding+'栋'});
  const numberedFixture={building_number:firstBuilding,unit_number:'2',elevator_number:'1'};
  assert.equal((await api.post('/api/elevators',{data:numberedFixture})).status(),409);
  const firstLabel=firstBuilding+'栋2口1号电梯';
  const secondLabel=firstBuilding+'栋2口2号电梯';
  const tenthLabel=firstBuilding+'栋10口1号电梯';
  const scopeLabels=[firstLabel,secondLabel,tenthLabel,lastBuilding+'栋2口1号电梯'];
  await page.getByRole('button',{name:'＋ 新增电梯',exact:true}).click();
  const addDialog=page.getByRole('dialog');await addDialog.waitFor();
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  const buildingNumber=addDialog.getByLabel('楼栋 *',{exact:true});
  assert.equal(await buildingNumber.getAttribute('inputmode'),'numeric');
  await buildingNumber.fill(firstBuilding+'栋');
  assert.equal(await buildingNumber.evaluate(input=>input.validity.patternMismatch),true);
  await buildingNumber.fill(firstBuilding);await addDialog.getByLabel('单元口 *',{exact:true}).fill('2');
  assert.equal(await addDialog.getByRole('radio').count(),2);
  await addDialog.getByRole('radio',{name:'1号电梯'}).waitFor();
  await addDialog.getByText('2号电梯',{exact:true}).click();
  assert.ok(await addDialog.getByRole('radio',{name:'2号电梯'}).isChecked());
  await page.screenshot({path:out+'/new-elevator-mobile.png',animations:'disabled'});
  await addDialog.getByRole('button',{name:'保存',exact:true}).click();await addDialog.waitFor({state:'hidden'});
  await page.getByRole('heading',{name:secondLabel,exact:true}).waitFor();
  await page.goto(base+'/events/new');
  const liftSelect=page.getByRole('combobox',{name:'选择电梯 *'});
  const liftTrigger=page.locator('.el-select').filter({has:liftSelect});
  await liftTrigger.click();
  const liftSearch=page.getByRole('searchbox',{name:'搜索电梯'});await liftSearch.waitFor();
  assert.deepEqual((await page.getByRole('option').allTextContents()).filter(label=>scopeLabels.includes(label)),scopeLabels);
  await liftSearch.fill('不存在');await page.getByText('没有匹配的电梯',{exact:true}).waitFor();
  await liftSearch.fill(firstBuilding+'栋2口2');await page.getByRole('option',{name:secondLabel,exact:true}).waitFor();
  await page.screenshot({path:out+'/new-record-elevator-search-mobile.png',animations:'disabled'});
  await liftSearch.press('Enter');await liftSearch.waitFor({state:'hidden'});
  await liftTrigger.getByText(secondLabel,{exact:true}).waitFor();
  await liftTrigger.click();await liftSearch.waitFor();assert.equal(await liftSearch.inputValue(),'');
  await liftSearch.fill('2单元1号');await page.getByRole('option',{name:firstLabel,exact:true}).click();
  await liftSearch.waitFor({state:'hidden'});await liftTrigger.getByText(firstLabel,{exact:true}).waitFor();
  await liftTrigger.click();await liftSearch.waitFor();
  await liftSearch.fill('10口');await liftSearch.press('Escape');await liftSearch.waitFor({state:'hidden'});
  await liftSelect.press('ArrowDown');await liftSearch.waitFor();assert.equal(await liftSearch.inputValue(),'');
  await liftSearch.fill(firstBuilding+'栋');
  const tenthOption=page.getByRole('option',{name:tenthLabel,exact:true});await tenthOption.waitFor();
  await liftSearch.press('ArrowDown');await page.keyboard.press('ArrowDown');await page.keyboard.press('ArrowDown');
  assert.equal(await tenthOption.evaluate(option=>option===document.activeElement),true);
  await page.keyboard.press('Enter');
  await liftSearch.waitFor({state:'hidden'});await liftTrigger.getByText(tenthLabel,{exact:true}).waitFor();
  await page.getByLabel('标题 *',{exact:true}).fill('键盘选择电梯验收');
  const savedRecord=page.waitForResponse(r=>r.url().endsWith('/api/events')&&r.request().method()==='POST');
  await page.getByRole('button',{name:'保存记录',exact:true}).click();
  const savedResponse=await savedRecord;assert.equal(savedResponse.status(),200);
  const persisted=await (await api.get('/api/events/'+(await savedResponse.json()).id)).json();
  assert.equal(persisted.elevator_id,tenthEntrance.id);

  await page.setViewportSize({width:1500,height:1060});
  await page.goto(base+'/records');
  await page.locator('button.operation-card').first().waitFor();
  // The device clock is still in March in UTC, but Shanghai has entered April and Q2.
  await page.clock.setFixedTime(new Date('2026-03-31T16:05:00Z'));
  for (const [label,start,end] of [
   ['今天','2026-04-01','2026-04-01'], ['近7天','2026-03-26','2026-04-01'],
   ['本月','2026-04-01','2026-04-30'], ['本季度','2026-04-01','2026-06-30']
  ]) {
   const query=recordsRequest();
   await page.getByRole('button',{name:label,exact:true}).click();
   const params=new URL((await query).url()).searchParams;
   assert.equal(params.get('start'),start);
   assert.equal(params.get('end'),end);
   assert.equal(params.get('month'),'2026-04-01');
   assert.equal(await page.getByRole('button',{name:label,exact:true}).getAttribute('aria-pressed'),'true');
  }
  await page.getByRole('button',{name:'上个月'}).click();
  await page.getByRole('heading',{name:'2026年3月',exact:true}).waitFor();
  const oneDay=recordsRequest();
  await page.getByRole('button',{name:/^2026年3月28日/}).click();
  const singleParams=new URL((await oneDay).url()).searchParams;
  assert.equal(singleParams.get('start'),'2026-03-28');assert.equal(singleParams.get('end'),'2026-03-28');
  await page.getByRole('button',{name:'下个月'}).click();
  await page.getByRole('heading',{name:'2026年4月',exact:true}).waitFor();
  await page.clock.setFixedTime(new Date());
  await page.getByRole('button',{name:'今天',exact:true}).click();
  await page.locator('.days button.today .pin').waitFor();
  const stamp=persisted.created_at;
  const expectedDay=new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'long',day:'numeric',weekday:'long'}).format(new Date(stamp));
  assert.equal((await page.locator('.date-rule').first().innerText()).replace(/\s/g,''),expectedDay.replace(/\s/g,''));
  const typeFilter=page.getByRole('combobox',{name:'类型',exact:true});
  const filtered=page.waitForResponse(r=>new URL(r.url()).searchParams.get('type')==='系统设置');
  await typeFilter.selectOption('系统设置');
  const systemEntries=await (await filtered).json();
  assert.ok(systemEntries.total>0);
  await page.locator('.range-note').filter({hasText:'共 '+systemEntries.total+' 条操作'}).waitFor();
  assert.equal(await page.locator('.operation.sys').count(),systemEntries.total);
  await typeFilter.selectOption('');
  await page.getByRole('button',{name:/键盘选择电梯验收/}).first().click();
  await page.waitForURL('**/elevators/'+tenthEntrance.id+'?event_id='+persisted.id);
  await page.goto(base+'/records');
  const recordsSelect=page.getByRole('combobox',{name:'电梯',exact:true});
  const recordsTrigger=page.locator('.el-select').filter({has:recordsSelect});
  const recordsOption=page.getByRole('option',{name:tenthLabel,exact:true});
  await recordsSelect.click();
  await recordsSelect.fill(firstBuilding+'栋 10单元 1号梯');
  const narrowed=recordsRequest();
  await recordsOption.click();
  assert.equal(new URL((await narrowed).url()).searchParams.get('elevator_id'),String(tenthEntrance.id));
  await recordsTrigger.getByText(tenthLabel,{exact:true}).waitFor();
  await recordsSelect.click();
  await recordsSelect.fill('不存在');await recordsOption.waitFor({state:'hidden'});
  await recordsSelect.press('Escape');await recordsOption.waitFor({state:'hidden'});
  await recordsSelect.click();await recordsOption.waitFor();assert.equal(await recordsSelect.inputValue(),'');
  await recordsSelect.fill('不存在');await recordsOption.waitFor({state:'hidden'});
  await page.getByRole('heading',{name:'工作记录',exact:true}).click();
  await recordsTrigger.getByText(tenthLabel,{exact:true}).waitFor();
  await recordsSelect.click();await recordsOption.waitFor();assert.equal(await recordsSelect.inputValue(),'');
  await page.getByRole('heading',{name:'工作记录',exact:true}).click();
  function recordsRequest(){return page.waitForRequest(request=>{
   const url=new URL(request.url());
   return url.pathname==='/api/timeline';
  })}
  const cleared=recordsRequest();
  await recordsTrigger.hover();await recordsTrigger.locator('.el-select__clear').click();
  assert.equal(new URL((await cleared).url()).searchParams.has('elevator_id'),false);

  // Current APIs prevent new aliases. Reproduce the old ledger response while keeping both saved IDs real.
  const ledger=await (await api.get('/api/elevators')).json();
  const original=ledger.find(e=>e.building_name===firstLift.building_name&&e.unit_name===firstLift.unit_name&&e.name===firstLift.name);
  assert.ok(original);
  const alias={...original,id:tenthEntrance.id,name:'01号电梯'};
  let similarId=Number('1'+alias.id);
  while(ledger.some(e=>e.id===similarId)) similarId=Number('1'+similarId);
  const similarAlias={...alias,id:similarId,name:'001号电梯'};
  const legacyLabel=e=>firstLabel+`（档案 ${e.id} · ${e.building_name} / ${e.unit_name} / ${e.name}）`;
  const wordLabel=`档案 ${alias.id} · ${firstLabel}`;
  const elevatorUrl=base+'/api/elevators';
  const aliasUrl=elevatorUrl+'/'+alias.id;
  await page.route(elevatorUrl,route=>route.fulfill({json:[...ledger.map(e=>e.id===alias.id?alias:e),similarAlias]}));
  await page.route(aliasUrl,async route=>{
   const response=await route.fetch();
   await route.fulfill({response,json:{...await response.json(),...alias}});
  });
  await page.setViewportSize({width:320,height:844});
  await page.goto(base+'/elevators');
  for(const e of [original,alias]) await page.getByRole('heading',{name:legacyLabel(e),exact:true}).waitFor();
  await page.goto(base+'/records');
  await page.locator('.el-select').filter({has:page.getByRole('combobox',{name:'电梯',exact:true})}).click();
  for(const e of [original,alias]) await page.getByRole('option',{name:legacyLabel(e),exact:true}).waitFor();
  await page.getByRole('option',{name:legacyLabel(similarAlias),exact:true}).waitFor();
  await recordsSelect.fill(wordLabel);
  await page.getByRole('option',{name:legacyLabel(similarAlias),exact:true}).waitFor({state:'hidden'});
  assert.deepEqual(await page.getByRole('listbox').getByRole('option').allTextContents(),[legacyLabel(alias)]);
  await page.goto(base+'/export');
  await page.getByText('某部电梯',{exact:true}).click();
  await page.locator('.el-select').filter({has:page.getByRole('combobox',{name:'楼栋',exact:true})}).click();
  await page.getByRole('option',{name:firstLift.building_name,exact:true}).click();
  await page.locator('.el-select').filter({has:page.getByRole('combobox',{name:'单元',exact:true})}).click();
  await page.getByRole('option',{name:firstLift.unit_name,exact:true}).click();
  await page.locator('.el-select').filter({has:page.getByRole('combobox',{name:'电梯',exact:true})}).click();
  for(const e of [original,alias]) await page.getByRole('option',{name:legacyLabel(e),exact:true}).waitFor();
  await page.goto(base+'/events/new');
  await liftTrigger.click();
  await liftSearch.fill(firstLabel);
  for(const e of [original,alias]) await page.getByRole('option',{name:legacyLabel(e),exact:true}).waitFor();
  const legacyOption=page.getByRole('option',{name:legacyLabel(alias),exact:true});
  assert.ok(await legacyOption.evaluate(option=>option.scrollWidth<=option.clientWidth&&option.scrollHeight<=option.clientHeight));
  await page.screenshot({path:out+'/legacy-elevator-options-mobile.png',animations:'disabled'});
  await liftSearch.fill(wordLabel);
  await page.getByRole('option',{name:legacyLabel(similarAlias),exact:true}).waitFor({state:'hidden'});
  assert.deepEqual(await page.getByRole('listbox').getByRole('option').allTextContents(),[legacyLabel(alias)]);
  await liftSearch.press('Enter');
  await liftTrigger.getByText(legacyLabel(alias),{exact:true}).waitFor();
  await liftTrigger.click();
  await liftSearch.fill('01号电梯');
  await legacyOption.click();
  await liftTrigger.getByText(legacyLabel(alias),{exact:true}).waitFor();
  assert.ok(await liftTrigger.locator('.el-select__placeholder').evaluate(label=>label.scrollWidth<=label.clientWidth));
  await page.getByLabel('标题 *',{exact:true}).fill('同名旧档案选择验收');
  const aliasRecord=page.waitForResponse(r=>r.url().endsWith('/api/events')&&r.request().method()==='POST');
  await page.getByRole('button',{name:'保存记录',exact:true}).click();
  const aliasResponse=await aliasRecord;assert.equal(aliasResponse.status(),200);
  const persistedAlias=await (await api.get('/api/events/'+(await aliasResponse.json()).id)).json();
  assert.equal(persistedAlias.elevator_id,alias.id);
  for(const e of [original,alias]){
   const recordUrl=base+'/elevators/'+e.id;
   await page.goto(recordUrl);
   await page.getByRole('button',{name:'查看、下载与打印',exact:true}).click();
   assert.equal(await page.locator('.qr-label h2').innerText(),legacyLabel(e));
   assert.equal(await page.locator('.qr-label .qr-target').innerText(),lan+'/elevators/'+e.id);
   const qrDownload=page.waitForEvent('download');
   await page.getByRole('button',{name:'下载二维码图片',exact:true}).click();
   assert.equal((await qrDownload).suggestedFilename(),firstLabel+`_档案${e.id}_二维码.png`);
   await page.emulateMedia({media:'print'});
   assert.equal(await page.locator('.qr-print-sheet h1').innerText(),legacyLabel(e));
   await page.emulateMedia({media:'screen'});
  }
  await page.unroute(elevatorUrl);
  await page.unroute(aliasUrl);

  await page.setViewportSize({width:1500,height:1060});await page.goto(base+'/elevators/'+lift.id);await page.getByRole('button',{name:'查看、下载与打印',exact:true}).click();await page.getByRole('dialog').waitFor();assert.equal(await page.locator('.qr-label .qr-target').innerText(),lan+'/elevators/'+lift.id);
  await page.locator('.qr-configuration summary').click();await page.getByLabel('主机局域网访问地址',{exact:true}).fill('http://127.0.0.1:8765');await page.getByRole('button',{name:'保存访问地址',exact:true}).click();await page.getByText('不能填写 127.0.0.1',{exact:false}).waitFor();assert.equal((await (await api.get('/api/network')).json()).configured_url,lan);
  await page.getByLabel('主机局域网访问地址',{exact:true}).fill(lan);
  await page.locator('.qr-configuration summary').click();await page.getByRole('dialog').screenshot({path:out+'/qr-desktop.png'});
  const download=page.waitForEvent('download');await page.getByRole('button',{name:'下载二维码图片',exact:true}).click();await (await download).saveAs(out+'/qr.png');assert.ok(fs.statSync(out+'/qr.png').size>300);
  await page.evaluate(()=>{window.print=()=>{window.__printed=true}});await page.getByRole('button',{name:'打印电梯标签',exact:true}).click();await page.waitForFunction(()=>window.__printed===true);await page.emulateMedia({media:'print'});assert.equal(await page.locator('.qr-print-sheet').isVisible(),true);assert.equal(await page.locator('.shell').isVisible(),false);await page.locator('.qr-print-sheet').screenshot({path:out+'/qr-label.png'});await page.pdf({path:out+'/qr-label.pdf',format:'A4',printBackground:true});await page.emulateMedia({media:'screen'});
  await page.setViewportSize({width:390,height:844});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.screenshot({path:out+'/qr-mobile.png',fullPage:true});
  const scanned=await browser.newContext({viewport:{width:390,height:844}});const scan=await scanned.newPage();scan.on('pageerror',e=>errors.push(e.message));
  await scan.goto(base+'/elevators/'+lift.id);await scan.getByRole('heading',{name:'18栋1口1号电梯',exact:true}).waitFor();assert.equal(scan.url(),base+'/elevators/'+lift.id);await scan.locator('.timeline-item').first().waitFor();await scan.screenshot({path:out+'/scan-detail-mobile.png',fullPage:true});
  await scan.reload();await scan.getByRole('heading',{name:'18栋1口1号电梯',exact:true}).waitFor();
  await scan.goto(base+'/elevators/999999');await scan.getByText('找不到这部电梯',{exact:false}).first().waitFor();assert.equal(await scan.locator('.detail-heading').count(),0);
  await scan.goto(base);await scan.locator('.home-hero h1').waitFor();
  assert.equal(await scan.locator('.stat').count(),6);
  assert.equal(await scan.locator('input[type=password],.user-avatar').count(),0);
  assert.deepEqual(await scanned.cookies(),[]);
  assert.deepEqual(errors,[]);console.log('PASS: numeric location form, separate lift numbers per entrance, natural record selector order and dropdown search, distinct legacy labels with saved ID and QR filenames, 10 desktop pages, 390/320px overflow checks, mobile menu/dialog, persisted LAN setting, reject loopback, QR download and print-only label, direct scan and reload, missing elevator, cookie-free home. LAN reachability not tested; loopback '+base+'; Chrome '+browser.version());
 }finally{await browser.close();await api.dispose()}
})().catch(e=>{console.error(e);process.exit(1)});
