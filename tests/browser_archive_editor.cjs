// Run only against a separate test data directory and a non-production loopback port.
const {chromium,request}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const base=process.env.ARCHIVE_EDITOR_TEST_URL;
assert.ok(base,'Set ARCHIVE_EDITOR_TEST_URL to an isolated test server');
const target=new URL(base);
assert.ok(['127.0.0.1','localhost'].includes(target.hostname)&&target.port&&target.port!=='8765','Use an isolated loopback test port');
const out=process.env.AUDIT_OUTPUT||path.resolve('outputs/archive-editor-20261028/browser');
const credentials={username:process.env.ARCHIVE_EDITOR_USERNAME||'archive-ui',display_name:'编排验收管理员',password:process.env.ARCHIVE_EDITOR_PASSWORD||'archive-ui-test-2026'};
(async()=>{
 fs.mkdirSync(out,{recursive:true});
 const api=await request.newContext({baseURL:base});
 async function post(url,data){const r=await api.post(url,{data});assert.equal(r.status(),200,await r.text());return r.json()}
 if((await (await api.get('/api/setup/status')).json()).needed)await post('/api/setup',credentials);
 await post('/api/login',credentials);
 const unique=Date.now().toString(36),building='编排验收'+unique+'栋';
 const lift=await post('/api/elevators',{building_name:building,unit_name:'1单元',name:'1号梯',equipment_number:'ARCHIVE-TEST',brand:'测试品牌',model:'测试型号'});
 const event=await post('/api/events',{elevator_id:lift.id,type:'维修',title:'厅门检查与修复',occurred_on:'2026-10-20',started_at:'2026-10-20T09:00',ended_at:'2026-10-20T10:00',work_content:'检查门锁回路，调整厅门间隙。\n完成三次试运行，运行正常。',resolution:'已完成复核',workers:'测试人员',company:'测试维保单位',completed:true});
 const raw=fs.readFileSync(path.resolve('tests/fixtures/archive-photo.png'));
 const pictures=[];
 for(const [index,category] of ['检查照片','复核照片'].entries()){
  const r=await api.post(`/api/events/${event.id}/attachments`,{multipart:{category:'工作现场照片',file:{name:`cgi-bin_photo_${index}_very_long_source_filename.png`,mimeType:'image/png',buffer:raw}}});
  assert.equal(r.status(),200,await r.text());pictures.push((await r.json()).id);
 }
 const original=await (await api.get(`/api/events/${event.id}`)).json();
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
 try{
  const context=await browser.newContext({viewport:{width:1440,height:1000},storageState:await api.storageState()});
  await context.addInitScript(()=>{for(const name of ['toSorted','toReversed','toSpliced'])delete Array.prototype[name];delete Object.groupBy;delete Promise.withResolvers;if(globalThis.crypto)Object.defineProperty(globalThis.crypto,'randomUUID',{value:undefined,configurable:true})});
  const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base+'/export');await page.getByText('选择电梯范围',{exact:true}).waitFor();
  const shortcuts=page.getByRole('radiogroup',{name:'统计周期快捷选择'});
  const selectedPeriods=()=>shortcuts.locator('.el-radio-button.is-active').allTextContents();
  assert.deepEqual(await selectedPeriods(),['全部时间']);
  const realTime=new Date(),januaryYear=realTime.getFullYear();
  await page.clock.setFixedTime(new Date(januaryYear,0,15,10));
  await shortcuts.locator('.el-radio-button').filter({hasText:'本月'}).click();assert.deepEqual(await selectedPeriods(),['本月']);
  assert.equal(await page.getByLabel('开始日期',{exact:true}).inputValue(),`${januaryYear}-01-01`);assert.equal(await page.getByLabel('结束日期',{exact:true}).inputValue(),`${januaryYear}-01-15`);
  await shortcuts.locator('.el-radio-button').filter({hasText:'本年'}).click();assert.deepEqual(await selectedPeriods(),['本年']);
  await shortcuts.locator('.el-radio-button').filter({hasText:'本月'}).click();assert.deepEqual(await selectedPeriods(),['本月']);
  await page.getByLabel('开始日期',{exact:true}).fill('2000-02-03');assert.deepEqual(await selectedPeriods(),[]);
  await page.getByLabel('开始日期',{exact:true}).fill(`${januaryYear}-01-01`);assert.deepEqual(await selectedPeriods(),['本月']);
  await shortcuts.locator('.el-radio-button').filter({hasText:'全部时间'}).click();assert.deepEqual(await selectedPeriods(),['全部时间']);
  await page.clock.setFixedTime(realTime);
  await page.locator('.el-radio-button').filter({hasText:'某部电梯'}).click();
  async function select(label,name){await page.locator('.el-select').filter({has:page.getByLabel(label,{exact:true})}).click();await page.getByRole('option',{name,exact:true}).click()}
  await select('楼栋',building);await select('单元','1单元');await select('电梯',building+'1单元1号梯');
  await page.getByLabel('开始日期',{exact:true}).fill('2026-10-01');await page.getByLabel('结束日期',{exact:true}).fill('2026-10-31');
  await page.screenshot({path:path.join(out,'01-range-desktop.png'),fullPage:true});
  const originalDownload=page.waitForEvent('download');await page.getByRole('button',{name:'直接导出原始档案',exact:true}).click();await (await originalDownload).saveAs(path.join(out,'原始工作档案.docx'));
  const creating=page.waitForResponse(r=>r.url().endsWith('/api/export-drafts')&&r.request().method()==='POST');
  await page.getByRole('button',{name:'生成编排稿 →',exact:true}).click();const created=await (await creating).json();assert.ok(created.id);
  await page.locator('#archive-title').waitFor();assert.match(await page.locator('#archive-title').inputValue(),new RegExp(building));
  assert.match(await page.locator('.archive-edit-paper .archive-document-metadata').textContent(),/昌福里社区27区党群物业服务站/);
  assert.equal(await page.locator('.archive-block[data-block-type=image]').count(),2);
  assert.ok(await page.locator('.archive-block[data-block-type=paragraph]').count()>0);
  const title='27区电梯维修工作情况汇报';await page.locator('#archive-title').fill(title);
  const firstHeading=page.locator('.archive-block[data-block-type=heading]').first();await firstHeading.locator('textarea').fill('一、现场检查与处理');
  const firstParagraph=page.locator('.archive-block[data-block-type=paragraph]').first();await firstParagraph.locator('textarea').fill('本次检查发现厅门间隙需要调整。\n现场完成处理后，运行恢复正常。');
  assert.equal(await firstHeading.locator('textarea').getAttribute('maxlength'),'300');assert.equal(await firstParagraph.locator('textarea').getAttribute('maxlength'),'10000');
  // Unsaved navigation and logout both leave the editing scene intact when cancelled.
  await page.getByRole('navigation',{name:'主菜单'}).getByRole('button',{name:'工作记录',exact:true}).click();await page.getByRole('button',{name:'继续编辑',exact:true}).click();assert.equal(new URL(page.url()).pathname,'/export');
  await page.getByRole('button',{name:'退出',exact:true}).click();await page.getByRole('button',{name:'继续编辑',exact:true}).click();assert.equal(await page.locator('#archive-title').inputValue(),title);assert.equal((await api.get('/api/me')).status(),200);
  await page.route('**/api/logout',route=>route.fulfill({status:500,contentType:'application/json',body:JSON.stringify({detail:'测试退出失败'})}));
  await page.getByRole('button',{name:'退出',exact:true}).click();await page.getByRole('button',{name:'放弃修改并继续',exact:true}).click();await page.getByText('测试退出失败',{exact:true}).waitFor();assert.match(await page.locator('.archive-save-state').textContent(),/未保存/);assert.equal(await page.locator('#archive-title').inputValue(),title);await page.unroute('**/api/logout');await page.getByText('测试退出失败',{exact:true}).waitFor({state:'hidden'});
  // Remove one existing photo, then insert it between text blocks from the source library.
  const removed=page.locator('.archive-block[data-block-type=image]').first();await removed.getByRole('button',{name:/移除第/}).click();await page.getByRole('button',{name:'移除此段',exact:true}).click();assert.equal(await page.locator('.archive-block[data-block-type=image]').count(),1);
  await page.locator('.archive-insert-gap>button').nth(2).click();await page.locator('.archive-insert-menu').getByRole('button',{name:'图片',exact:true}).click();await page.getByRole('dialog',{name:'插入工作照片'}).waitFor();
  assert.equal(await page.locator('.archive-photo-grid button:disabled').count(),1);assert.equal(await page.locator('.archive-photo-grid').getByText(/cgi-bin/).count(),0);await page.waitForFunction(()=>!document.querySelector('.el-message'));await page.getByRole('dialog').screenshot({path:path.join(out,'02-photo-library-desktop.png')});
  await page.locator('.archive-photo-grid button:not(:disabled)').first().click();assert.equal(await page.locator('.archive-block[data-block-type=image]').count(),2);
  const firstImage=page.locator('.archive-block[data-block-type=image]').first();await firstImage.locator('.archive-caption-edit input').fill('调整门锁后进行运行复核');
  // Insert a new paragraph and heading at the start; use keyboard on the move button.
  await page.locator('.archive-insert-gap>button').first().click();await page.locator('.archive-insert-menu').getByRole('button',{name:'正文',exact:true}).click();await page.locator('.archive-block').first().locator('textarea').fill('编排验收新增正文，位于报告开头。');
  const movedId=await page.locator('.archive-block').first().getAttribute('data-block-id');await page.locator('.archive-block').first().getByRole('button',{name:/下移第/}).focus();await page.keyboard.press('Enter');assert.equal(await page.locator('.archive-block').nth(1).getAttribute('data-block-id'),movedId);
  await page.locator('.archive-insert-gap>button').first().click();await page.locator('.archive-insert-menu').getByRole('button',{name:'小标题',exact:true}).click();await page.locator('.archive-block').first().locator('textarea').fill('工作情况说明');
  // Native HTML drag/drop moves the whole block; a phone also has explicit move buttons.
  await page.setViewportSize({width:1440,height:1800});await page.evaluate(()=>scrollTo(0,0));
  const dragged=await page.locator('.archive-block').first().getAttribute('data-block-id');await page.locator('.archive-block').first().locator('.archive-drag-handle').dragTo(page.locator('.archive-insert-gap').nth(2));
  assert.equal(await page.locator('.archive-block').nth(1).getAttribute('data-block-id'),dragged);await page.setViewportSize({width:1440,height:1000});
  await page.evaluate(()=>scrollTo(0,0));await page.screenshot({path:path.join(out,'03-editor-desktop.png'),fullPage:true});await page.evaluate(()=>scrollTo(0,0));await page.screenshot({path:path.join(out,'03-editor-desktop-viewport.png')});
  // Move the final image ahead of the first, preview before saving, and compare directory order.
  const lastImage=page.locator('.archive-block[data-block-type=image]').last();const lastImageId=await lastImage.getAttribute('data-block-id');while(await page.locator('.archive-block').first().getAttribute('data-block-id')!==lastImageId)await page.locator(`[data-block-id="${lastImageId}"]`).getByRole('button',{name:/上移第/}).click();
  assert.equal(await page.locator('.archive-block').first().getAttribute('data-block-id'),lastImageId);
  await page.getByRole('button',{name:'预览',exact:true}).click();await page.locator('.archive-preview-paper h1').waitFor();assert.equal(await page.locator('.archive-preview-paper h1').textContent(),title);assert.equal(await page.locator('.archive-preview-paper textarea,.archive-preview-paper button').count(),0);
  const previewRefs=await page.locator('.archive-preview-directory tbody td:first-child').allTextContents();assert.deepEqual(previewRefs.slice(0,2),['图1','图2']);assert.equal(await page.locator('.archive-preview-directory').getByText(/cgi-bin/).count(),0);
  await page.evaluate(()=>scrollTo(0,0));await page.screenshot({path:path.join(out,'04-preview-desktop.png'),fullPage:true});
  await page.getByRole('button',{name:'返回编辑',exact:true}).click();
  const saveResponse=page.waitForResponse(r=>r.url().endsWith('/api/export-drafts/'+created.id)&&r.request().method()==='PUT');await page.getByRole('button',{name:'保存草稿',exact:true}).click();assert.equal((await saveResponse).status(),200);await page.waitForFunction(()=>document.querySelector('.archive-save-state')?.textContent.includes('已保存'));
  const saved=await (await api.get('/api/export-drafts/'+created.id)).json();assert.equal(saved.title,title);assert.deepEqual(saved.attachment_directory.map(x=>x.reference),previewRefs);
  await page.locator('#archive-title').fill(title+'（不保存的修改）');await page.getByRole('button',{name:'← 返回范围',exact:true}).click();await page.getByRole('button',{name:'放弃修改并继续',exact:true}).click();assert.equal(await page.locator('.archive-draft-list').getByText(/不保存的修改/).count(),0);await page.locator('.archive-draft-list button').filter({hasText:title}).first().click();assert.equal(await page.locator('#archive-title').inputValue(),title);
  await page.reload();await page.locator('.archive-draft-list button').filter({hasText:title}).first().click();assert.equal(await page.locator('#archive-title').inputValue(),title);assert.deepEqual(await page.locator('.archive-block').evaluateAll(nodes=>nodes.map(n=>n.dataset.blockId)),saved.blocks.map(x=>x.id));
  // A second writer cannot silently overwrite a stale editor.
  const external=await api.put('/api/export-drafts/'+created.id,{data:{title:title+'（另一窗口）',blocks:saved.blocks,revision:saved.revision}});assert.equal(external.status(),200);
  await page.locator('#archive-title').fill(title+'（当前未保存）');const rejected=page.waitForResponse(r=>r.url().endsWith('/api/export-drafts/'+created.id)&&r.request().method()==='PUT');await page.getByRole('button',{name:'保存草稿',exact:true}).click();assert.equal((await rejected).status(),409);assert.equal(await page.locator('#archive-title').inputValue(),title+'（当前未保存）');await page.screenshot({path:path.join(out,'05-conflict-preserves-edit.png'),fullPage:true});
  await page.getByRole('button',{name:'重新读取已保存稿',exact:true}).click();await page.getByRole('button',{name:'放弃修改并继续',exact:true}).click();await page.waitForFunction(()=>document.querySelector('#archive-title')?.value.endsWith('（另一窗口）'));
  await page.locator('#archive-title').fill(title);const downloadPromise=page.waitForEvent('download');await page.getByRole('button',{name:'导出 Word',exact:true}).click();const download=await downloadPromise;await download.saveAs(path.join(out,'编排工作档案.docx'));assert.ok(fs.statSync(path.join(out,'编排工作档案.docx')).size>1000);
  await page.locator('.archive-document-options .el-checkbox').filter({hasText:'打包原始附件（ZIP）'}).click();const zipPromise=page.waitForEvent('download');await page.getByRole('button',{name:'导出 ZIP',exact:true}).click();await (await zipPromise).saveAs(path.join(out,'编排完整档案.zip'));assert.ok(fs.statSync(path.join(out,'编排完整档案.zip')).size>1000);
  // Mobile editing, insertion, move, removal, undo, preview and persistence at 390px.
  await page.setViewportSize({width:390,height:844});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'mobile editor overflow');
  await page.locator('#archive-title').fill(title+'（手机复核）');await page.locator('.archive-insert-gap>button').first().click();await page.locator('.archive-insert-menu').getByRole('button',{name:'正文',exact:true}).click();await page.locator('.archive-block').first().locator('textarea').fill('手机端补充：复核完成。');
  await page.locator('.archive-block').first().getByRole('button',{name:/下移第/}).click();assert.match(await page.locator('.archive-block').nth(1).locator('textarea').inputValue(),/手机端补充/);
  await page.locator('.archive-block').nth(1).getByRole('button',{name:/移除第/}).click();await page.getByRole('button',{name:'移除此段',exact:true}).click();await page.getByRole('button',{name:'撤销本次移除',exact:true}).click();assert.match(await page.locator('.archive-block').nth(1).locator('textarea').inputValue(),/手机端补充/);
  await page.locator('.archive-block[data-block-type=image]').first().getByRole('button',{name:/移除第/}).click();await page.getByRole('button',{name:'移除此段',exact:true}).click();await page.locator('.archive-insert-gap>button').first().click();await page.locator('.archive-insert-menu').getByRole('button',{name:'图片',exact:true}).click();await page.waitForFunction(()=>!document.querySelector('.el-message'));await page.getByRole('dialog').screenshot({path:path.join(out,'06-photo-library-mobile.png')});await page.locator('.archive-photo-grid button:not(:disabled)').first().click();
  await page.getByRole('dialog').waitFor({state:'hidden'});await page.waitForFunction(()=>!document.querySelector('.el-message'));await page.evaluate(()=>scrollTo(0,0));
  await page.locator('#archive-title').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,'07-editor-mobile.png'),fullPage:true});await page.evaluate(()=>scrollTo(0,0));await page.screenshot({path:path.join(out,'07-editor-mobile-viewport.png')});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'mobile inserted editor overflow');
  await page.getByRole('button',{name:'保存草稿',exact:true}).click();await page.waitForFunction(()=>document.querySelector('.archive-save-state')?.textContent.includes('已保存'));await page.locator('.archive-document-options .el-checkbox').filter({hasText:'打包原始附件（ZIP）'}).click();const mobileDownload=page.waitForEvent('download');await page.getByRole('button',{name:'导出 Word',exact:true}).click();await(await mobileDownload).saveAs(path.join(out,'编排工作档案_手机.docx'));await page.getByRole('button',{name:'预览',exact:true}).click();assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'mobile preview overflow');await page.waitForFunction(()=>!document.querySelector('.el-message'));await page.evaluate(()=>scrollTo(0,0));await page.screenshot({path:path.join(out,'08-preview-mobile.png'),fullPage:true});
  await page.setViewportSize({width:320,height:844});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'320px preview overflow');
  const finalOriginal=await (await api.get(`/api/events/${event.id}`)).json();assert.equal(finalOriginal.title,original.title);assert.equal(finalOriginal.work_content,original.work_content);assert.deepEqual(finalOriginal.attachments.map(x=>x.id),original.attachments.map(x=>x.id));
  assert.deepEqual(errors,[]);
  fs.writeFileSync(path.join(out,'browser-result.json'),JSON.stringify({passed:true,browser:browser.version(),draftId:created.id,elevatorId:lift.id,eventId:event.id,checks:['scope/date generation','editable title/headings/paragraphs','interleaved source images and duplicate prevention','native drag and keyboard move','delete and undo','unsaved navigation, discard and logout cancellation', 'logout network failure preserves unsaved state','preview directory and Word ordering','draft save/reload','revision conflict preserves edits','real DOCX/ZIP downloads','390px edit and source photo insertion','320px preview no overflow','original records unchanged']},null,2));
  console.log('PASS: archive editor desktop/mobile, draft persistence, conflict, guard, photo insertion, ordering, preview, real Word/ZIP downloads, original ledger unchanged. Chrome '+browser.version());
 }finally{await browser.close();await api.dispose()}
})().catch(e=>{console.error(e);process.exit(1)});
