// Run only against an isolated database (see TEST_REPORT.md).
const {chromium,request}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const base=process.env.AUDIT_URL||'http://127.0.0.1:8767';
const out=process.env.AUDIT_OUTPUT||path.resolve('outputs/export-format-20260930');
(async()=>{
 const api=await request.newContext({baseURL:base});
 async function post(url,data){const r=await api.post(url,{data});assert.equal(r.status(),200,await r.text());return r.json()}
 const credentials={username:'format',display_name:'排版测试管理员',password:'format-browser-123'};
 if((await (await api.get('/api/setup/status')).json()).needed)await post('/api/setup',credentials);
 await post('/api/login',credentials);
 const lift=await post('/api/elevators',{building_name:'排序测试18栋',unit_name:'1单元',name:'1号梯'});
 const event=await post('/api/events',{elevator_id:lift.id,type:'维修',title:'照片按现场处理顺序排列',occurred_on:'2026-09-30',work_content:'处理前检查、现场维修、处理后复核。'});
 const photos=[];
 for(const name of ['现场.png','现场.webp']){
  const r=await api.post(`/api/events/${event.id}/attachments`,{multipart:{category:'工作现场照片',file:{name,mimeType:name.endsWith('png')?'image/png':'image/webp',buffer:fs.readFileSync(path.join(out,name))}}});
  assert.equal(r.status(),200,await r.text());photos.push((await r.json()).id);
 }
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
 try{
  const context=await browser.newContext({viewport:{width:1440,height:1000},storageState:await api.storageState()});
  const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(`${base}/events/${event.id}/edit`);
  await page.locator('.existing-file').first().getByRole('button',{name:'下移',exact:true}).waitFor();
  const saved=page.waitForResponse(r=>r.url().endsWith('/attachment-order')&&r.request().method()==='PUT');
  await page.locator('.existing-file').first().getByRole('button',{name:'下移',exact:true}).click();
  assert.equal((await saved).status(),200);
  await page.waitForFunction(id=>document.querySelector('.existing-file .el-image img')?.src.includes(id),photos[1]);
  await page.reload();await page.waitForFunction(id=>document.querySelector('.existing-file .el-image img')?.src.includes(id),photos[1]);
  const record=await (await api.get(`/api/events/${event.id}`)).json();assert.deepEqual(record.attachments.map(a=>a.id),[photos[1],photos[0]]);
  await page.screenshot({path:path.join(out,'edit-order-desktop.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true,'Mobile form overflows');
  await page.screenshot({path:path.join(out,'edit-order-mobile.png'),fullPage:true});
  await page.goto(base+'/events/new');
  await page.locator('input[type=file][multiple]').setInputFiles([path.join(out,'现场.png'),path.join(out,'现场.webp')]);
  await page.locator('.queued-file').first().getByRole('button',{name:'下移',exact:true}).click();
  assert.equal(await page.locator('.queued-file span[title]').first().getAttribute('title'),'现场.webp');
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true,'Mobile upload queue overflows');
  await page.goto(base+'/export');await page.locator('.archive-selection-summary').waitFor();
  assert.equal(await page.locator('.archive-selection-summary small').textContent(),'编制单位：昌福里社区27区党群物业服务站');
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true,'Mobile export overflows');
  await page.screenshot({path:path.join(out,'export-mobile.png'),fullPage:true});
  await page.setViewportSize({width:1440,height:1000});await page.screenshot({path:path.join(out,'export-desktop.png'),fullPage:true});
  const downloadPromise=page.waitForEvent('download');await page.getByRole('button',{name:'直接导出原始档案'}).click();
  const download=await downloadPromise;assert.ok(download.suggestedFilename().startsWith('昌福里社区27区党群物业服务站'));
  await download.saveAs(path.join(out,'browser-export.docx'));
  assert.deepEqual(errors,[]);console.log('PASS: saved photo order, reload, queued order, mobile layouts, renamed cover, real DOCX download');
 }finally{await browser.close();await api.dispose()}
})().catch(e=>{console.error(e);process.exit(1)});
