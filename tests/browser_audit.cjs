// Run against an isolated test server only. See AUDIT_REPORT.md for the invocation.
const {chromium,request}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const base=process.env.AUDIT_URL||'http://127.0.0.1:8766';
const out=process.env.AUDIT_OUTPUT||'/private/tmp/elevator-audit-ui-output';
(async()=>{
 const api=await request.newContext({baseURL:base});
 const credentials={username:'audit',display_name:'测试管理员',password:'audit-password-123'};
 if((await (await api.get('/api/setup/status')).json()).needed) assert.equal((await api.post('/api/setup',{data:credentials})).status(),200);
 assert.equal((await api.post('/api/login',{data:credentials})).status(),200);
 async function post(path,data) {const r=await api.post(path,{data});assert.equal(r.status(),200,await r.text());return r.json()}
 const unique=Date.now().toString().slice(-8);
 const building=(await post('/api/buildings',{name:'验收'+unique+'栋'})).id;
 const unit=(await post('/api/units',{building_id:building,name:'1单元'})).id;
 const elevator=(await post('/api/elevators',{unit_id:unit,name:'1号梯'})).id;
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
 try {
 const context=await browser.newContext({viewport:{width:1366,height:900}});
 await context.addInitScript(()=>{for(const name of ['toSorted','toReversed','toSpliced']) delete Array.prototype[name];delete Object.groupBy;delete Promise.withResolvers;});
 const page=await context.newPage();const errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.goto(base);await page.getByLabel('账号',{exact:true}).fill(credentials.username);await page.getByLabel('密码',{exact:true}).fill(credentials.password);await page.getByRole('button',{name:'登录',exact:true}).click();await page.locator('.home-hero h1').waitFor();

 await page.goto(base+'/elevators');await page.getByRole('button',{name:'＋ 新增电梯',exact:true}).click();
 assert.equal(await page.getByRole('button',{name:'新增楼栋',exact:true}).count(),0);
 await page.getByLabel('楼栋 *',{exact:true}).fill('表单'+unique+'栋');await page.getByLabel('单元 *',{exact:true}).fill('3单元');await page.getByLabel('电梯名称 / 梯号 *',{exact:true}).fill('2号梯');
 await page.getByRole('dialog').getByRole('button',{name:'保存',exact:true}).click();await page.getByRole('dialog').waitFor({state:'hidden'});await page.getByRole('button',{name:new RegExp('表单'+unique+'栋')}).waitFor();
 await page.getByRole('button',{name:'导入档案',exact:true}).click();await page.locator('input[type=file][accept=".xlsx"]').setInputFiles(out+'/档案.xlsx');await page.getByRole('button',{name:'检查表格',exact:true}).click();await page.getByText('检查通过：',{exact:false}).waitFor();await page.getByRole('button',{name:/确认导入/}).click();await page.getByText('导入完成：',{exact:false}).waitFor();await page.getByRole('button',{name:'完成',exact:true}).click();
 const excelPromise=page.waitForEvent('download');await page.getByRole('button',{name:'导出 Excel',exact:true}).click();const excel=await excelPromise;await excel.saveAs(out+'/导出档案.xlsx');assert.ok(fs.statSync(out+'/导出档案.xlsx').size>1000);
 await page.screenshot({path:out+'/archives.png',fullPage:true});
 await page.goto(base+'/events/new?elevator_id='+elevator);
 async function pick(label,value){await page.locator('.el-select').filter({has:page.getByLabel(label,{exact:true})}).click();await page.getByRole('option',{name:value,exact:true}).click()}
 await pick('工作类型 *','维修');await page.getByLabel('标题 *',{exact:true}).fill('验收门锁'+unique);
 await page.getByLabel('工作内容',{exact:true}).fill('更换门锁开关并检查运行情况');
 await page.getByRole('button',{name:'＋ 添加配件',exact:true}).first().click();
 await page.getByLabel('配件名称 *',{exact:true}).fill('门锁开关');await page.getByLabel('单价（元）',{exact:true}).fill('260');
 await page.getByLabel('更换日期',{exact:true}).fill('2026-08-01');await page.getByLabel('质保天数',{exact:true}).fill('365');
 await page.getByText('质保截止：2027-08-01',{exact:false}).waitFor();
 await page.locator('input[type=file][multiple]').setInputFiles([out+'/现场.png',out+'/现场.webp',out+'/报价.docx']);
 assert.equal(await page.locator('.queued-file').count(),3);
 let failOnce=true;
 await page.route('**/api/events/*/attachments',async route=>{if(failOnce){failOnce=false;await route.fulfill({status:500,contentType:'application/json',body:JSON.stringify({detail:'模拟一次上传中断'})})}else await route.continue()});
 await page.getByRole('button',{name:'保存记录',exact:true}).click();await page.getByText('文字记录已保存；再次保存会更新同一条记录，不会重复新增。').waitFor();
 await page.waitForFunction(()=>document.querySelectorAll('.queued-file').length===1);
 await page.getByRole('button',{name:'保存记录',exact:true}).click();await page.waitForURL('**/elevators/'+elevator);
 let rows=await (await api.get('/api/events?elevator_id='+elevator)).json();assert.equal(rows.length,1);assert.equal(rows[0].attachments.length,3);assert.equal(rows[0].cost_cents,26000);
 const event=rows[0].id;
 await page.goto(base+'/events/'+event+'/edit');await page.getByLabel('标题 *',{exact:true}).waitFor();assert.equal(await page.getByRole('switch').getAttribute('aria-checked'),'true');assert.equal(await page.getByLabel('本次总费用（元，含配件）',{exact:true}).inputValue(),'');await page.getByLabel('单价（元）',{exact:true}).fill('300');await page.getByLabel('处理情况',{exact:true}).fill('试运行正常');await page.getByRole('button',{name:'保存记录',exact:true}).click();await page.waitForURL('**/elevators/'+elevator);
 assert.equal((await (await api.get('/api/events/'+event)).json()).cost_cents,30000);
 await page.goto(base+'/search');await page.getByRole('textbox',{name:'搜索全部档案和工作记录'}).fill('验收'+unique+'栋 门锁');await page.getByRole('button',{name:'搜索',exact:true}).click();await page.getByRole('button',{name:new RegExp('验收门锁'+unique)}).click();await page.waitForURL('**/elevators/'+elevator+'?event_id='+event);await page.getByText('试运行正常',{exact:false}).waitFor();
 await page.locator('.photo-item').nth(1).locator('.el-image').click();await page.locator('.el-image-viewer__img').first().waitFor();
 assert.ok((await page.locator('.el-image-viewer__img').first().getAttribute('src')).includes(rows[0].attachments.filter(a=>a.relative_path.startsWith('photos/'))[1].id));
 await page.locator('.el-image-viewer__close').click();
 await page.screenshot({path:out+'/desktop.png',fullPage:true});
 await page.setViewportSize({width:390,height:844});await page.goto(base+'/events/new?elevator_id='+elevator);await page.getByLabel('标题 *',{exact:true}).waitFor();assert.equal(await page.locator('input[capture=environment]').count(),1);assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));await page.screenshot({path:out+'/mobile.png',fullPage:true});
 await page.setViewportSize({width:1366,height:900});await page.goto(base+'/export');await page.getByText('选择电梯范围',{exact:true}).waitFor();await page.locator('.el-radio-button').filter({hasText:'某楼栋'}).click();await page.locator('.el-select').filter({has:page.getByLabel('楼栋',{exact:true})}).click();await page.getByRole('option',{name:'验收'+unique+'栋',exact:true}).click();assert.equal(await page.locator('.archive-selection-summary b').innerText(),'验收'+unique+'栋');await page.locator('.el-radio-button').filter({hasText:'全部电梯'}).click();await page.screenshot({path:out+'/export.png',fullPage:true});const downloadPromise=page.waitForEvent('download');await page.getByRole('button',{name:'直接导出原始档案',exact:true}).click();const download=await downloadPromise;await download.saveAs(out+'/browser-export.docx');assert.ok(fs.statSync(out+'/browser-export.docx').size>1000);
 await page.goto(base+'/records');await page.getByRole('button',{name:new RegExp('验收门锁'+unique)}).first().waitFor();
 await page.getByRole('heading',{name:'最近工作动态',exact:true}).waitFor();await page.screenshot({path:out+'/records.png',fullPage:true});
 for(const target of ['/elevators','/records','/search','/export']) {await page.setViewportSize({width:390,height:844});await page.goto(base+target);await page.getByRole('textbox',{name:'搜索全部档案和工作记录'}).waitFor();await page.waitForTimeout(250);assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),'mobile overflow: '+target)}
 await page.screenshot({path:out+'/export-mobile.png',fullPage:true});await page.setViewportSize({width:1366,height:900});
 await page.goto(base+'/admin');await page.getByRole('heading',{name:'已删除资料'}).waitFor();
 assert.deepEqual(errors,[]);console.log('PASS: inline elevator creation, Excel preview/import/export, export scope preview, responsive pages, login, repair with parts, warranty, three uploads, failed upload retry without duplicate, edit booleans, search focus, photo preview index, mobile form overflow, Word download, records, administration. Browser '+browser.version());
 } finally {await browser.close();await api.dispose()}
})().catch(e=>{console.error(e);process.exit(1)});
