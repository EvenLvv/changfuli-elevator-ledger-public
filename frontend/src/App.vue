<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import lobbyPhoto from './assets/elevator-lobby.jpg'
import OperationTimeline from './components/OperationTimeline.vue'
import { displayTimestamp, today } from './calendar'
import ArchiveEditor from './components/ArchiveEditor.vue'
import PhotoLibrary from './components/PhotoLibrary.vue'
import { conflictingPlaceLabels, locationNumber, matchingElevatorOptions, place, placeParts } from './location'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { SelectInstance } from 'element-plus'

const route = useRoute(), router = useRouter()
const startupError = ref('')
const busy = ref(false)
const buildings = ref<any[]>([]), units = ref<any[]>([]), elevators = ref<any[]>([])
const dashboard = ref<any>({stats:{},reminders:[],recent:[]})
const seedStatus = ref<any>(null)
const visibleSeedBanner = computed(() =>
  seedStatus.value?.seed_present && (seedStatus.value.status === 'imported' || seedStatus.value.status === 'failed') && seedStatus.value.message
    ? seedStatus.value
    : null
)
const reminders = ref<any[]>([]), timeline = ref<any[]>([]), history = ref<any[]>([]), currentElevator = ref<any>(null), hasMoreEvents=ref(false)
const selectedBuilding = ref<number|undefined>(), selectedUnit = ref<number|undefined>()
const sort = ref('desc'), query = ref(''), searchResult = ref<any>({elevators:[],events:[]})
const searchPending=ref(false), searched=ref(false)
let searchVersion=0
const archiveFile=ref<File|null>(null), importResult=ref<any>(null)
const canConfirmImport = computed(() => archiveFile.value && importResult.value?.valid && !importResult.value.committed
  && typeof importResult.value.preview_token === 'string' && importResult.value.preview_token.length > 0)
const homeType=ref('全部'), mobileMenu=ref(false)
const homeRecords=computed(()=>dashboard.value.recent.filter((r:any)=>homeType.value==='全部'||r.type===homeType.value))
const calendarDate=new Date().toLocaleDateString('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'long',day:'numeric',weekday:'long'})
const networkReady=ref(false)
const network=ref<any>({candidates:[],base_url:'',configured_url:''}), networkDraft=ref('')
const qrInfo=ref<any>({url:''}), qrRevision=ref(0), detailError=ref('')
const qrImage=computed(()=>currentElevator.value?`/api/elevators/${currentElevator.value.id}/qr?v=${qrRevision.value}`:'')
const homeAlerts=computed(()=>[
  {label:'项配件质保已到期',note:'查看更换记录，核对质保信息',tone:'danger',count:dashboard.value.reminders.filter((r:any)=>r.kind==='配件质保'&&r.days_left<0).length},
  {label:'项质保将在30天内到期',note:'提前核对配件使用情况',tone:'warning',count:dashboard.value.reminders.filter((r:any)=>r.kind==='配件质保'&&r.days_left>=0).length},
  {label:'部电梯需要关注维保',note:'含已逾期及30天内到期',tone:'primary',count:dashboard.value.reminders.filter((r:any)=>r.kind==='维保').length},
  {label:'部电梯需要关注年检',note:'含已逾期及30天内到期',tone:'primary',count:dashboard.value.reminders.filter((r:any)=>r.kind==='年检').length}
].filter(r=>r.count))
async function loadNetwork(){networkReady.value=false;network.value=await api('/network');networkDraft.value=network.value.configured_url||network.value.base_url;networkReady.value=true}
async function saveNetwork(){await run(async()=>{network.value=await api('/network',{method:'PUT',body:JSON.stringify({base_url:networkDraft.value})});networkDraft.value=network.value.configured_url;if(currentElevator.value){qrInfo.value=await api(`/elevators/${currentElevator.value.id}/qr-info`);qrRevision.value++}ElMessage.success('局域网地址已保存，请先用手机测试，再打印二维码')})}
async function openQr(){await run(async()=>{await loadNetwork();qrInfo.value=await api(`/elevators/${currentElevator.value.id}/qr-info`);dialog.value='qr'})}

const navItems=[
  {path:'/',label:'首页',icon:'M3 10 12 3 21 10 M5 9v12h14V9 M9 21v-8h6v8'},
  {path:'/elevators',label:'电梯档案',icon:'M5 3h14v18H5z M12 7v14 M8 6h8 M8 11h1 M15 11h1'},
  {path:'/records',label:'工作记录',icon:'M6 3h12v18H6z M9 7h6 M9 11h6 M9 15h4'},
  {path:'/photos',label:'图片库',icon:'M3 5h18v14H3z M5 17l5-5 3 3 2-2 4 4'},
  {path:'/reminders',label:'提醒中心',icon:'M5 17h14l-2-4V9a5 5 0 0 0-10 0v4z M10 21h4'},
  {path:'/export',label:'工作档案导出',icon:'M5 3h10l4 4v5 M5 3v18h8 M15 3v5h4 M18 13v8 M15 18l3 3 3-3'},
  {path:'/admin',label:'系统设置',icon:'M4 7h16 M4 17h16 M8 4v6 M16 14v6'}
]
const dialog = ref(''), buildingForm = ref<any>({name:''}), unitForm = ref<any>({building_id:null,name:''})
const elevatorForm = ref<any>({})
const emptyEvent = () => ({elevator_id: Number(route.query.elevator_id)||null,type:'日常维保',title:'',occurred_on:today(),work_content:'',resolution:'',workers:'',company:'',completed:true,cost_yuan:'',uses_maintenance_fund:false,maintenance_fund_yuan:'',notes:'',elevator_status:'',symptom:'',cause:'',remedy:'',stopped:false,recovered:false,started_at:'',ended_at:'',fault_at:'',reported_at:'',arrived_at:'',restored_at:'',parts:[] as any[]})
const eventForm = ref<any>(emptyEvent()), eventFiles = ref<Array<{file:File,category:string}>>([]), existingFiles=ref<any[]>([])
const hasPartReplacement = computed(() => eventForm.value.type === '配件更换' || eventForm.value.parts.length > 0)
const savedGeneralCost = ref<number|null>(null)
const eventReady=ref(false), eventLoadError=ref('')
const savedEventId = ref<number|null>(null)
const eventElevatorQuery = ref('')
const eventElevatorSearch = ref<HTMLInputElement>()
const eventElevatorSelect = ref<SelectInstance>()
const elevatorLabels = computed(() => conflictingPlaceLabels(elevators.value))
function placeLabel(item: Parameters<typeof place>[0] & { id?: number; elevator_id?: number; location_label?: string }) {
  const id = item.elevator_id ?? item.id
  return item.location_label ?? (id === undefined ? undefined : elevatorLabels.value.get(id)) ?? place(item)
}
const qrFilename = computed(() => {
  const elevator = currentElevator.value
  if (!elevator) return ''
  const suffix = elevatorLabels.value.has(elevator.id) ? `_档案${elevator.id}` : ''
  return `${place(elevator)}${suffix}_二维码.png`
})
const collator = new Intl.Collator('zh-CN', { numeric: true })
const elevatorOptions = computed(() => elevators.value.map(item => ({ item, label: placeLabel(item) })))
const eventElevators = computed(() => elevatorOptions.value.map(option => ({ ...option, parts: placeParts(option.item) }))
  .sort((a, b) => collator.compare(a.parts[0], b.parts[0]) || collator.compare(a.parts[1], b.parts[1])
    || collator.compare(a.parts[2], b.parts[2]) || a.item.id - b.item.id))
const filteredEventElevators = computed(() => matchingElevatorOptions(eventElevators.value, eventElevatorQuery.value))
const trash=ref<any[]>([])
const eventTimes=[['started_at','开始时间'],['ended_at','结束时间'],['fault_at','故障发生'],['reported_at','报修时间'],['arrived_at','到场时间'],['restored_at','恢复时间']]
const attachmentCategories = ['工作现场照片','维修记录','维保记录','报价单','业主签字单','检测报告','验收资料','其他']
const page = computed(() => route.path === '/' ? 'home' : route.path.startsWith('/elevators/') ? 'detail' : route.path === '/elevators' ? 'elevators' : route.path.startsWith('/events/') ? 'event' : route.path.slice(1))
const visibleUnits = computed(() => units.value.filter(x => !selectedBuilding.value || x.building_id === selectedBuilding.value))
const visibleElevators = computed(() => elevators.value.filter(x => (!selectedBuilding.value || x.building_id === selectedBuilding.value) && (!selectedUnit.value || x.unit_id === selectedUnit.value)))
const imageList = (event:any) => event.attachments.filter((x:any)=> x.relative_path.startsWith('photos/')).map((x:any)=>`/api/attachments/${x.id}`)
const yuan = (cents:number) => `¥${((cents||0)/100).toFixed(2)}`
const partTotal = (part:any) => ((Number(part.quantity)||0)*(Number(part.unit_price_yuan)||0)).toFixed(2)
function warrantyUntil(part:any) {const base=part.warranty_from||part.replaced_on;if(!base||!Number(part.warranty_days)) return '未设置';const d=new Date(`${base}T00:00:00Z`);if(Number.isNaN(d.getTime())) return '日期无效';d.setUTCDate(d.getUTCDate()+Number(part.warranty_days));return d.toISOString().slice(0,10)}
const title = computed(() => ({home:'首页',elevators:'电梯档案',detail:'电梯档案',records:'工作记录',photos:'图片库',event:route.path.includes('/edit')?'修改工作记录':'新增工作记录',search:'搜索结果',reminders:'提醒中心',export:'工作档案导出',admin:'系统设置'} as any)[page.value] || '')

async function api(path:string, options:any={}) {
  const response = await fetch('/api'+path,{credentials:'same-origin',...options,headers:options.body instanceof FormData?options.headers:{'Content-Type':'application/json',...options.headers}})
  if (!response.ok) { let message='操作失败，请检查填写内容'; try {const detail=(await response.json()).detail;if(typeof detail==='string') message=detail} catch {} throw Object.assign(new Error(message),{status:response.status}) }
  return response.json()
}
async function run(action:()=>Promise<any>) { if(busy.value) return;busy.value=true; try {await action()} catch(e:any) {ElMessage.error(e.message || '操作失败')} finally {busy.value=false} }
function nav(path:string) { mobileMenu.value=false;router.push(path) }
async function loadSeedStatus() { try { seedStatus.value = await api('/seed-status') } catch {} }
async function loadBase() { const result=await Promise.all([api('/buildings'),api('/units'),api('/elevators')]); [buildings.value,units.value,elevators.value]=result }
async function load() {
  startupError.value=''
  if(page.value==='event') {eventReady.value=false;eventLoadError.value=''}
  try {
    if (page.value==='home') { dashboard.value=await api('/dashboard'); seedStatus.value=dashboard.value.seed_status||null }
    if (['elevators','detail','event','records','photos','export','admin'].includes(page.value)) await loadBase()
    if (page.value==='elevators') await loadSeedStatus()
    if (page.value==='detail') { detailError.value='';currentElevator.value=null;qrInfo.value={url:''};const id=Number(route.params.id); [currentElevator.value,timeline.value,history.value]=await Promise.all([api(`/elevators/${id}`),api(`/events?elevator_id=${id}&order=${sort.value}`),api(`/elevators/${id}/parts`)]);hasMoreEvents.value=timeline.value.length===100; if(route.query.event_id) {const focused=await api(`/events/${Number(route.query.event_id)}`);if(focused.elevator_id!==id) throw new Error('工作记录与电梯不匹配');timeline.value=[focused];hasMoreEvents.value=false} qrInfo.value=await api(`/elevators/${id}/qr-info`);qrRevision.value++ }
    if (page.value==='event') {
      savedGeneralCost.value=null
      if (route.path.includes('/edit')) {
        const record=await api(`/events/${route.params.id}`)
        if (record.cost_cents || !record.cost_auto) savedGeneralCost.value=record.cost_cents/100
        eventForm.value={...record,elevator_status:'',cost_yuan:savedGeneralCost.value ?? '',
          maintenance_fund_yuan:record.maintenance_fund_yuan ?? '',parts:record.parts.map((p:any)=>({...p,unit_price_yuan:p.unit_price_cents/100}))}
        existingFiles.value=record.attachments
      } else {eventForm.value=emptyEvent();existingFiles.value=[]}
      savedEventId.value=route.path.includes('/edit')?Number(route.params.id):null
      eventFiles.value=[]
      eventReady.value=true
    }
    if (page.value==='search') {query.value=String(route.query.q||'');await performSearch()}
    if (page.value==='reminders') reminders.value=await api('/reminders')
    if (page.value==='admin') {trash.value=await api('/trash');await loadNetwork()}
  } catch (e:any) {if(page.value==='detail') detailError.value=e.message;if(page.value==='event') eventLoadError.value=e.message;startupError.value=e.message }
}
watch(()=>route.fullPath,load)
watch(sort,()=>{if(page.value==='detail') load()})
onMounted(load)

function openBuilding(item?:any) {buildingForm.value=item?{...item}:{name:''};dialog.value='building'}
function openUnit(item?:any) {unitForm.value=item?{...item}:{building_id:selectedBuilding.value||null,name:''};dialog.value='unit'}
async function addBuilding() {await run(async()=>{const id=buildingForm.value.id;await api(id?`/buildings/${id}`:'/buildings',{method:id?'PUT':'POST',body:JSON.stringify(buildingForm.value)});dialog.value='';buildingForm.value={name:''};await loadBase();ElMessage.success('楼栋已保存')})}
async function addUnit() {await run(async()=>{const id=unitForm.value.id;await api(id?`/units/${id}`:'/units',{method:id?'PUT':'POST',body:JSON.stringify(unitForm.value)});dialog.value='';unitForm.value={building_id:null,name:''};await loadBase();ElMessage.success('单元已保存')})}
async function removePlace(kind:'building'|'unit', id:number) {try {await ElMessageBox.confirm('仅空楼栋或空单元可以删除。确定继续？','确认删除',{type:'warning'});await api(`/${kind==='building'?'buildings':'units'}/${id}`,{method:'DELETE'});await load()} catch(e:any) {if(e!=='cancel'&&e!=='close') ElMessage.error(e.message)}}
function openElevator(item?:any) {
  const unit = units.value.find(u => u.id === selectedUnit.value)
  const building = buildings.value.find(b => b.id === (selectedBuilding.value || unit?.building_id))
  const building_number = locationNumber('building', item?.building_name ?? building?.name)
  const unit_number = locationNumber('unit', item?.unit_name ?? unit?.name)
  const elevator_number = item ? locationNumber('elevator', item.name) : '1'
  const validNumber = (number: string) => /^[1-9][0-9]{0,38}$/.test(number)
  const numbered = !item || (validNumber(building_number) && validNumber(unit_number) && ['1', '2'].includes(elevator_number))
  elevatorForm.value = { status:'正常', ...item, ...(numbered ? {building_number, unit_number, elevator_number} : {}) }
  dialog.value='elevator'
}
async function focusEventElevatorSearch(open: boolean) {
  if (!open) {eventElevatorQuery.value='';return}
  await nextTick()
  eventElevatorSearch.value?.focus()
}
async function closeElevatorSearch(select?: SelectInstance) {
  select?.blur()
  await nextTick()
  select?.focus()
}
function selectFilteredElevator(event: KeyboardEvent) {
  if (event.isComposing) return
  event.preventDefault()
  if (filteredEventElevators.value.length !== 1) return
  eventForm.value.elevator_id = filteredEventElevators.value[0].item.id
  void closeElevatorSearch(eventElevatorSelect.value)
}
function focusFirstEventElevator(event: KeyboardEvent) {
  if (event.isComposing) return
  event.preventDefault()
  document.querySelector<HTMLElement>('.event-elevator-options [role="option"]')?.focus()
}
function moveEventElevatorFocus(event: KeyboardEvent, direction: 'next' | 'previous') {
  const option = event.currentTarget as HTMLElement
  const sibling = (direction === 'next' ? option.nextElementSibling : option.previousElementSibling) as HTMLElement | null
  if (sibling) sibling.focus()
  else if (direction === 'previous') eventElevatorSearch.value?.focus()
}
function openImport() {archiveFile.value=null;importResult.value=null;dialog.value='import'}
function archiveChanged(event:Event) {archiveFile.value=(event.target as HTMLInputElement).files?.[0]||null;importResult.value=null}
async function importArchives(commit=false) {
  await run(async()=>{
    const file=archiveFile.value
    if(!file || (commit && !canConfirmImport.value)) return
    const data=new FormData()
    data.append('file',file)
    if(commit) data.append('preview_token',importResult.value.preview_token)
    importResult.value=null
    const result=await api(`/elevator-archives/import?dry_run=${!commit}`,{method:'POST',body:data}).catch(e=>{
      if(e.status!==409) throw e
      return {valid:false,errors:[e.message],error_count:1}
    })
    if(archiveFile.value===file) importResult.value=result
    if(commit&&result.valid&&result.committed){
      await loadBase()
      await loadSeedStatus()
      ElMessage.success(`已新增${result.added}部电梯，跳过${result.skipped}部已有档案`)
    }
  })
}
function exportArchives() {const params=new URLSearchParams();if(selectedBuilding.value) params.set('building_id',String(selectedBuilding.value));if(selectedUnit.value) params.set('unit_id',String(selectedUnit.value));download('/api/elevator-archives/export?'+params)}
async function saveElevator() {await run(async()=>{const id=elevatorForm.value.id;await api(id?`/elevators/${id}`:'/elevators',{method:id?'PUT':'POST',body:JSON.stringify(elevatorForm.value)});dialog.value='';await loadBase();if(page.value==='elevators') await loadSeedStatus();if(page.value==='detail') await load();ElMessage.success('电梯档案已保存')})}
async function removeElevator() {try {await ElMessageBox.confirm('删除后不会在列表中显示，历史数据仍保留。确定删除？','确认删除',{type:'warning'});await api(`/elevators/${currentElevator.value.id}`,{method:'DELETE'});nav('/elevators')} catch(e:any) {if(e!=='cancel'&&e!=='close') ElMessage.error(e.message)}}
function addPart() {eventForm.value.parts.push({name:'',model:'',quantity:1,unit_price_yuan:0,replaced_on:eventForm.value.occurred_on,reason:'',brand:'',warranty_days:0,warranty_from:'',notes:''})}
function removePart(index:number) {
  eventForm.value.parts.splice(index,1)
}
function filesChanged(e:Event, category?:string) {
  const input=e.target as HTMLInputElement
  for(const file of Array.from(input.files||[])) {
    if(!/\.(jpe?g|png|webp|pdf|docx?|xlsx?)$/i.test(file.name) || file.size===0 || file.size>20*1024*1024) {
      ElMessage.error(`${file.name}：请选择支持的格式，文件需大于0且不超过20 MB`);continue
    }
    eventFiles.value.push({file,category:category || (file.type.startsWith('image/')?'工作现场照片':'其他')})
  }
  input.value=''
}
function moveQueuedFile(index:number, step:number) {const to=index+step;if(to<0||to>=eventFiles.value.length)return;const [item]=eventFiles.value.splice(index,1);eventFiles.value.splice(to,0,item)}
async function moveExistingFile(index:number, step:number) {await run(async()=>{const to=index+step;if(to<0||to>=existingFiles.value.length)return;const reordered=[...existingFiles.value];const [item]=reordered.splice(index,1);reordered.splice(to,0,item);await api(`/events/${savedEventId.value}/attachment-order`,{method:'PUT',body:JSON.stringify({ids:reordered.map(f=>f.id)})});existingFiles.value=reordered;ElMessage.success('附件顺序已保存')})}
async function saveEvent() {
  await run(async()=>{
    const id=savedEventId.value
    const payload={...eventForm.value,cost_yuan:hasPartReplacement.value ? savedGeneralCost.value ?? '' : eventForm.value.cost_yuan}
    const result=await api(id?`/events/${id}`:'/events',{method:id?'PUT':'POST',body:JSON.stringify(payload)})
    const eventId=id||result.id
    savedEventId.value=eventId
    if (!hasPartReplacement.value) savedGeneralCost.value=payload.cost_yuan === '' ? null : Number(payload.cost_yuan)
    eventForm.value.updated_at=result.updated_at
    eventForm.value.elevator_status=''
    const failed: typeof eventFiles.value=[]
    for(const item of eventFiles.value) {
      const form=new FormData();form.append('file',item.file);form.append('category',item.category)
      try {await api(`/events/${eventId}/attachments`,{method:'POST',body:form})}
      catch(e:any) {failed.push(item);ElMessage.error(`${item.file.name}：${e.message}`)}
    }
    eventFiles.value=failed
    if(failed.length) {existingFiles.value=(await api(`/events/${eventId}`)).attachments;ElMessage.warning('文字已保存。失败附件仍保留在下方，修正后再次保存即可重试。');return}
    ElMessage.success('工作记录已保存')
    nav(`/elevators/${eventForm.value.elevator_id}`)
  })
}
async function restoreItem(item:any) {
  try {await ElMessageBox.confirm(`恢复“${item.name}”？若上级楼栋或电梯也已删除，请先恢复上级。`,'恢复资料');await api(`/trash/${item.kind}/${item.id}/restore`,{method:'POST'});await load();ElMessage.success('资料已恢复')}
  catch(e:any) {if(e!=='cancel'&&e!=='close') ElMessage.error(e.message)}
}
async function removeEvent(id:number) {try {await ElMessageBox.confirm('确定删除这条记录？','确认删除',{type:'warning'});await api(`/events/${id}`,{method:'DELETE'});await load()} catch(e:any) {if(e!=='cancel'&&e!=='close') ElMessage.error(e.message)}}
async function loadMoreEvents() {await run(async()=>{const more=await api(`/events?elevator_id=${currentElevator.value.id}&order=${sort.value}&offset=${timeline.value.length}`);timeline.value.push(...more);hasMoreEvents.value=more.length===100})}
async function removeAttachment(id:string) {try {await ElMessageBox.confirm('确定移除此附件？','确认移除',{type:'warning'});await api(`/attachments/${id}`,{method:'DELETE'});existingFiles.value=existingFiles.value.filter(x=>x.id!==id)} catch(e:any) {if(e!=='cancel'&&e!=='close') ElMessage.error(e.message)}}
async function search() {const q=query.value.trim();if(route.path==='/search'&&route.query.q===q) await performSearch();else router.push({path:'/search',query:q?{q}:{}})}
async function performSearch() {const version=++searchVersion;searched.value=false;searchResult.value={elevators:[],events:[]};if(!query.value.trim()){searchPending.value=false;return}searchPending.value=true;try {const result=await api(`/search?q=${encodeURIComponent(query.value.trim())}`);if(version===searchVersion){searchResult.value=result;searched.value=true}}catch(e:any){ElMessage.error(e.message)}finally{if(version===searchVersion)searchPending.value=false}}
function download(path:string, filename='') {const link=document.createElement('a');link.href=path;link.download=filename;document.body.appendChild(link);link.click();link.remove()}
async function backup() {await run(async()=>{const result=await api('/backup',{method:'POST'});download(result.download);ElMessage.success('备份已生成并开始下载')})}
async function printPage() {await run(async()=>{if(!qrInfo.value.url) throw new Error('请先设置局域网地址');const picture=new Image();picture.src=qrImage.value;await picture.decode();window.print()})}
</script>

<template>
  <div class="shell">
    <div class="main-area">
      <header class="topbar">
        <button class="brand-lockup" @click="nav('/')" aria-label="昌福里社区27区党群物业服务站工作台"><span class="brand-mark">27</span><span><b>昌福里社区</b><small>27区党群物业服务站</small></span></button>
        <button class="mobile-menu-toggle" :aria-expanded="mobileMenu" aria-controls="main-navigation" @click="mobileMenu=!mobileMenu">{{mobileMenu?'收起菜单':'菜单'}} ☰</button>
        <nav id="main-navigation" class="main-nav" :class="{expanded:mobileMenu}" aria-label="主菜单"><button v-for="item in navItems" :key="item.path" :class="{active:route.path===item.path||(item.path==='/elevators'&&page==='detail')||(item.path==='/records'&&page==='event')}" @click="nav(item.path)">{{item.label}}</button></nav>
        <div class="top-actions"><form class="global-search" role="search" @submit.prevent="search"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/></svg><input v-model="query" aria-label="搜索全部档案和工作记录" placeholder="搜索全部资料"/><button type="submit" aria-label="搜索">搜索</button></form><span class="local-status"><span class="local-dot"></span>局域网运行</span></div>
      </header>
      <main :class="{'records-page':page==='records'}">
        <div class="page-context"><span>27区党群物业服务站 <i>/</i> {{page==='home'?calendarDate:title}}</span><span>打开即可使用 · 无需登录 · 2.0.2</span></div>
        <p v-if="startupError && !['event','detail'].includes(page)" role="alert">{{startupError}} <el-button @click="load">重试</el-button></p>
        <section v-if="page==='home'" class="home-page">
          <div class="home-hero"><div class="hero-copy"><div class="eyebrow">日常维护 · 长期留档</div><h1>电梯的每一天，<br>都有迹可循<span>。</span></h1><p>打开软件即可进入工作台。从一次维保，到一份完整档案。<br>记录、查找、整理，每一次操作都会留在时间轴上。</p><div class="hero-actions"><el-button type="primary" size="large" @click="nav('/events/new')">＋ 新增工作记录</el-button><el-button text @click="nav('/elevators')">查看电梯档案 ↗</el-button></div></div><figure class="hero-art"><img :src="lobbyPhoto" alt="电梯厅"><figcaption><b>27</b> 昌福里社区27区党群物业服务站</figcaption></figure></div>
          <div v-if="visibleSeedBanner" class="seed-banner" :class="{warn:visibleSeedBanner.status==='failed'}" role="status"><span class="seed-dot"></span><span>{{visibleSeedBanner.message}}</span></div>
          <div class="stats-grid"><div v-for="item in [{label:'电梯总数',value:dashboard.stats.total||0,unit:'部'},{label:'正常运行',value:dashboard.stats.normal||0,unit:'部'},{label:'故障电梯',value:dashboard.stats.fault||0,unit:'部'},{label:'维修中',value:dashboard.stats.repairing||0,unit:'部'},{label:'本月维修',value:dashboard.stats.monthly_repairs||0,unit:'次'},{label:'本月更换配件',value:dashboard.stats.monthly_parts||0,unit:'件'}]" :key="item.label" class="stat"><span>{{item.label}}</span><b>{{item.value}}<small>{{item.unit}}</small></b></div></div>
          <div class="home-workspace"><section class="panel home-ledger"><div class="panel-head"><h2>最近工作</h2><div class="ledger-tabs" aria-label="最近工作类型"><button v-for="t in ['全部','日常维保','维修','配件更换']" :key="t" :class="{active:homeType===t}" @click="homeType=t">{{t==='日常维保'?'维保':t}}</button></div><el-button text @click="nav('/records')">查看全部 ↗</el-button></div><div class="ledger-columns"><span>工作内容</span><span>电梯位置</span><span>日期</span><span>状态</span></div><div v-if="!homeRecords.length" class="empty">暂无此类工作记录，点击“新增工作记录”开始留档。</div><button v-for="r in homeRecords" :key="r.id" class="ledger-row" @click="nav(`/elevators/${r.elevator_id}?event_id=${r.id}`)"><span class="ledger-title"><span class="record-icon">{{r.type==='日常维保'?'✓':r.type==='配件更换'?'↕':'↗'}}</span><span><b>{{r.title}}</b><small>{{r.type}}</small></span></span><span class="ledger-location">{{placeLabel(r)}}</span><time>{{r.occurred_on}}</time><span class="work-state" :class="{pending:!r.completed}">{{r.completed?'已完成':'待完成'}}</span></button><div class="ledger-footer">按工作日期排列 · 最近 {{dashboard.recent.length}} 条 <button @click="nav('/records')">查看工作台账 →</button></div></section>
          <aside class="home-rail"><div class="panel-head"><h2>待关注</h2><span class="count">{{dashboard.reminders.length}}</span></div><div v-if="!homeAlerts.length" class="empty compact">目前没有到期提醒</div><button v-for="r in homeAlerts" :key="r.label" class="alert-row" @click="nav('/reminders')"><span class="alert-number" :class="r.tone">{{r.count}}</span><span><b>{{r.label}}</b><small>{{r.note}}</small></span><span class="row-arrow">→</span></button><section class="export-link"><h3>整理一份工作档案</h3><p>按楼栋和时间选择范围，<br>导出 Word 与完整附件资料。</p><el-button text @click="nav('/export')">开始导出 ↗</el-button></section></aside></div>
        </section>
        <section v-if="page==='detail'&&detailError" class="panel empty">{{detailError}}<div><el-button @click="nav('/elevators')">返回电梯档案</el-button></div></section>

        <section v-if="page==='elevators'"><div class="page-heading"><div><div class="eyebrow">一梯一档 · 基础资料</div><h1>电梯档案</h1><p>每部电梯的资料与工作历史，都在这里。</p></div><div class="button-group"><el-button @click="exportArchives">导出 Excel</el-button><el-button @click="openImport">导入档案</el-button><el-button type="primary" @click="openElevator()">＋ 新增电梯</el-button></div></div>
          <div v-if="visibleSeedBanner" class="seed-banner archive-seed-banner" :class="{warn:visibleSeedBanner.status==='failed'}" role="status"><span class="seed-dot"></span><span>{{visibleSeedBanner.message}}</span></div>
          <div class="filter-bar"><label>楼栋 <el-select v-model="selectedBuilding" clearable placeholder="全部楼栋" @change="selectedUnit=undefined"><el-option v-for="b in buildings" :key="b.id" :label="b.name" :value="b.id" /></el-select></label><label>单元 <el-select v-model="selectedUnit" clearable placeholder="全部单元"><el-option v-for="u in visibleUnits" :key="u.id" :label="u.name" :value="u.id" /></el-select></label><span>{{visibleElevators.length}} 部电梯</span></div>
          <div v-if="!visibleElevators.length" class="panel empty">暂无电梯档案。点击“新增电梯”填写楼栋、单元和梯号，也可批量导入。</div>
          <div class="elevator-grid"><button v-for="e in visibleElevators" :key="e.id" class="elevator-card" @click="nav(`/elevators/${e.id}`)"><div class="card-top"><span class="lift-symbol">↕</span><span class="status" :class="e.status==='正常'?'ok':'alert'">{{e.status}}</span></div><h3>{{placeLabel(e)}}</h3><p>{{e.equipment_number||'使用登记证号未填写'}}</p><div class="card-bottom">查看档案 <span>→</span></div></button></div>
        </section>

        <section v-if="page==='detail' && currentElevator"><div class="breadcrumbs"><button @click="nav('/elevators')">电梯档案</button><span>›</span>{{placeLabel(currentElevator)}}</div><div class="page-heading detail-heading"><div><h1>{{placeLabel(currentElevator)}}</h1><p>使用登记证号：{{currentElevator.equipment_number||'未填写'}}　<span class="status" :class="currentElevator.status==='正常'?'ok':'alert'">{{currentElevator.status}}</span></p></div><div class="button-group"><el-button @click="openElevator(currentElevator)">编辑档案</el-button><el-button type="primary" @click="nav(`/events/new?elevator_id=${currentElevator.id}`)">＋ 新增工作记录</el-button></div></div>
          <div class="detail-layout"><div><section class="panel"><div class="panel-head"><h2>工作时间线</h2><el-button v-if="route.query.event_id" @click="nav(`/elevators/${currentElevator.id}`)">查看全部历史</el-button><el-select v-else v-model="sort" size="small" style="width:120px"><el-option label="最新优先" value="desc"/><el-option label="最早优先" value="asc"/></el-select></div><div v-if="!timeline.length" class="empty">暂无工作记录。点击“新增工作记录”开始。</div><article v-for="event in timeline" :key="event.id" class="timeline-item"><div class="timeline-date">{{event.occurred_on}} <span>{{event.type}}</span></div><h3>{{event.title}}</h3><p>{{event.work_content||event.symptom||'未填写工作内容'}}</p><el-collapse :model-value="route.query.event_id?[event.id]:[]"><el-collapse-item :name="event.id" title="查看详情"><div class="detail-lines"><p v-for="[key,label] in eventTimes.filter(([key])=>event[key])" :key="key"><b>{{label}}：</b>{{event[key].replace('T',' ')}}</p><p v-if="event.type==='故障'">发生停梯：{{event.stopped?'是':'否'}} · {{event.recovered?'已恢复正常':'尚未恢复'}}</p><p v-if="event.symptom"><b>故障现象：</b>{{event.symptom}}</p><p v-if="event.cause"><b>故障原因：</b>{{event.cause}}</p><p v-if="event.remedy"><b>处理办法：</b>{{event.remedy}}</p><p v-if="event.resolution"><b>处理情况：</b>{{event.resolution}}</p><p v-if="event.workers"><b>工作人员：</b>{{event.workers}}</p><p v-if="event.company"><b>工作单位：</b>{{event.company}}</p><p v-if="event.uses_maintenance_fund"><b>住宅维修基金金额：</b>{{event.maintenance_fund_cents == null ? '已动用，金额未登记' : yuan(event.maintenance_fund_cents)}}</p><p v-if="event.cost_cents || !event.cost_auto"><b>{{event.parts.length || event.type==='配件更换' ? '历史登记费用' : '一般登记费用'}}：</b>{{yuan(event.cost_cents)}}</p><p><b>状态：</b>{{event.completed?'已完成':'未完成'}}</p><p v-if="event.notes"><b>备注：</b>{{event.notes}}</p></div><div v-for="part in event.parts" :key="part.id" class="part-line"><b>{{part.name}} × {{part.quantity}}</b><span>型号：{{part.model||'未填写'}} · 品牌：{{part.brand||'未填写'}}</span><span v-if="part.unit_price_cents">历史配件单价 {{yuan(part.unit_price_cents)}} · 历史配件合计 {{yuan(part.total_price_cents)}}</span><span>更换 {{part.replaced_on}} · 质保 {{part.warranty_days}} 天 · 截止 {{part.warranty_until||'未设置'}}</span><span v-if="part.reason">原因：{{part.reason}}</span><span v-if="part.notes">备注：{{part.notes}}</span></div><div v-if="event.attachments.length" class="attachment-area"><div class="photo-grid"><figure v-for="(f,index) in event.attachments.filter((x:any)=>x.relative_path.startsWith('photos/'))" :key="f.id" class="photo-item"><el-image :src="`/api/attachments/${f.id}`" :preview-src-list="imageList(event)" :initial-index="index" fit="cover" class="photo-thumb" loading="lazy" /><figcaption>{{f.category}} <a :href="`/api/attachments/${f.id}`" target="_blank" rel="noopener">原图</a> · <a :href="`/api/attachments/${f.id}?download=true`">下载</a></figcaption></figure></div><p v-for="f in event.attachments.filter((x:any)=>!x.relative_path.startsWith('photos/'))" :key="f.id"><a :href="`/api/attachments/${f.id}?download=true`">{{f.original_name}} ↓</a> <small>{{f.category}}</small></p></div><div class="record-actions"><el-button size="small" @click="nav(`/events/${event.id}/edit`)">修改</el-button><el-button size="small" type="danger" text @click="removeEvent(event.id)">删除</el-button></div></el-collapse-item></el-collapse></article><el-button v-if="hasMoreEvents" class="full" :loading="busy" @click="loadMoreEvents">加载更多工作记录</el-button></section></div>
          <div class="side-stack"><section class="panel"><h2>基本情况</h2><dl class="facts"><template v-for="row in [{label:'所属小区',value:currentElevator.community},{label:'内部编号',value:currentElevator.internal_number},{label:'品牌',value:currentElevator.brand},{label:'设备型号',value:currentElevator.model},{label:'出厂日期',value:currentElevator.manufactured_on},{label:'投入使用时间',value:currentElevator.started_on},{label:'备注',value:currentElevator.notes},{label:'维保单位',value:currentElevator.maintenance_company},{label:'维保人姓名',value:currentElevator.maintenance_contact},{label:'维保联系人电话',value:currentElevator.maintenance_phone},{label:'下次维保',value:currentElevator.maintenance_due_on},{label:'年检日期',value:currentElevator.inspection_on},{label:'住宅维修基金金额累计',value:currentElevator.total_maintenance_fund_cents?yuan(currentElevator.total_maintenance_fund_cents):'无金额记录'},...(currentElevator.total_cost_cents?[{label:'一般登记费用累计',value:yuan(currentElevator.total_cost_cents)}]:[])]" :key="row.label"><dt>{{row.label}}</dt><dd>{{row.value||'未填写'}}</dd></template></dl><el-button text type="danger" @click="removeElevator">删除这部电梯</el-button></section><section class="panel"><h2>配件更换历史</h2><div v-if="!history.length" class="empty compact">暂无配件记录</div><div v-for="part in history" :key="part.id" class="history-row"><b>{{part.name}}</b><small>{{part.replaced_on}} · {{part.quantity}}件</small><small>质保：{{part.warranty_until||'未设置'}}<template v-if="part.days_since_previous!==null"> · 距上次{{part.days_since_previous}}天</template></small></div></section><section class="panel qr-panel"><div class="panel-head"><h2>扫码查看档案</h2><span class="small-label">本部电梯</span></div><img v-if="qrInfo.url" :src="qrImage" alt="本部电梯档案二维码"><div v-else class="qr-placeholder">请先设置局域网地址</div><p>手机连接物业站网络，扫码即可<br>查看这部电梯的资料。</p><el-button class="full" @click="openQr">{{qrInfo.url?'查看、下载与打印':'设置二维码地址'}}</el-button></section></div></div>
        </section>

        <section v-if="page==='event'"><div class="page-heading"><div><div class="eyebrow">现场工作 · 及时记录</div><h1>{{title}}</h1><p>填写必要内容，照片和文件可以一次上传多张。</p></div></div><div v-if="!eventReady" class="panel">{{eventLoadError||'正在读取电梯与工作记录…'}} <el-button v-if="eventLoadError" @click="load">重试</el-button></div><div v-else class="form-panel panel"><el-form label-position="top" @submit.prevent="saveEvent"><div class="form-grid"><el-form-item label="选择电梯 *"><el-select ref="eventElevatorSelect" v-model="eventForm.elevator_id" :class="{'elevator-select-conflict': elevatorLabels.has(eventForm.elevator_id)}" :disabled="!!savedEventId" placeholder="按楼栋、单元口、梯号选择" class="full" popper-class="event-elevator-options" no-data-text="没有匹配的电梯" @visible-change="focusEventElevatorSearch">
              <template #header>
                <input ref="eventElevatorSearch" v-model="eventElevatorQuery" type="search" class="event-elevator-search"
                  aria-label="搜索电梯" placeholder="搜索楼栋、单元口或梯号"
                  @keydown.enter.stop="selectFilteredElevator" @keydown.esc.stop.prevent="closeElevatorSearch(eventElevatorSelect)"
                  @keydown.down="focusFirstEventElevator" />
              </template>
              <el-option v-for="{ item, label } in filteredEventElevators" :key="item.id" :label="label" :value="item.id" tabindex="-1"
                :class="{'elevator-option-conflict': elevatorLabels.has(item.id)}"
                @keydown.down.prevent="moveEventElevatorFocus($event, 'next')" @keydown.up.prevent="moveEventElevatorFocus($event, 'previous')"
                @keydown.enter.space.prevent="($event.currentTarget as HTMLElement).click()" @keydown.esc.stop.prevent="closeElevatorSearch(eventElevatorSelect)" />
            </el-select></el-form-item><el-form-item label="工作类型 *"><el-select v-model="eventForm.type" class="full"><el-option v-for="t in ['日常维保','故障','维修','配件更换','检验/检查','资料补充','其他']" :key="t" :label="t" :value="t" /></el-select></el-form-item><el-form-item label="工作日期 *"><el-input v-model="eventForm.occurred_on" type="date" /></el-form-item><el-form-item label="标题 *"><el-input v-model="eventForm.title" placeholder="例如：更换3层厅门锁开关" maxlength="120" /></el-form-item></div><el-form-item label="工作内容"><el-input v-model="eventForm.work_content" type="textarea" :rows="4" placeholder="做了什么工作？" /></el-form-item><el-form-item label="处理情况"><el-input v-model="eventForm.resolution" type="textarea" :rows="3" placeholder="目前结果如何？" /></el-form-item>
          <div v-if="eventForm.type==='故障'" class="sub-form"><h2>故障情况</h2><div class="form-grid"><el-form-item label="故障现象"><el-input v-model="eventForm.symptom" /></el-form-item><el-form-item label="故障原因"><el-input v-model="eventForm.cause" /></el-form-item><el-form-item label="处理办法"><el-input v-model="eventForm.remedy" /></el-form-item><el-form-item label="故障发生时间"><el-input v-model="eventForm.fault_at" type="datetime-local" /></el-form-item><el-form-item label="报修时间"><el-input v-model="eventForm.reported_at" type="datetime-local" /></el-form-item><el-form-item label="到场时间"><el-input v-model="eventForm.arrived_at" type="datetime-local" /></el-form-item><el-form-item label="恢复时间"><el-input v-model="eventForm.restored_at" type="datetime-local" /></el-form-item><el-form-item><el-checkbox v-model="eventForm.stopped">发生停梯</el-checkbox><el-checkbox v-model="eventForm.recovered">已恢复正常</el-checkbox></el-form-item></div></div>
          <div class="sub-form">
            <div class="panel-head parts-header">
              <div class="parts-heading"><h2>更换配件</h2><el-checkbox v-model="eventForm.uses_maintenance_fund" @change="eventForm.maintenance_fund_yuan=''">动用住宅维修资金</el-checkbox></div>
              <el-button @click="addPart">＋ 添加配件</el-button>
            </div>
            <div v-if="eventForm.uses_maintenance_fund" class="form-grid"><el-form-item label="住宅维修基金金额">
              <el-input v-model="eventForm.maintenance_fund_yuan" type="number" min="0.01" max="100000000" step="0.01" />
              <p class="hint">单位为元。金额未知可留空，已知时按整条记录填写一次。</p>
            </el-form-item></div>
            <p v-if="hasPartReplacement && savedGeneralCost!==null" class="hint">历史登记费用 {{yuan(Math.round(savedGeneralCost*100))}}</p>
            <div v-for="(part,index) in eventForm.parts" :key="index" class="part-editor"><div class="form-grid"><el-form-item label="配件名称 *"><el-input v-model="part.name" /></el-form-item><el-form-item label="型号"><el-input v-model="part.model" /></el-form-item><el-form-item label="数量"><el-input v-model="part.quantity" type="number" min="1" /></el-form-item><el-form-item label="更换日期"><el-input v-model="part.replaced_on" type="date" /></el-form-item><el-form-item label="质保天数"><el-input v-model="part.warranty_days" type="number" min="0" /></el-form-item><el-form-item label="质保开始日期（留空按更换日期）"><el-input v-model="part.warranty_from" type="date" /></el-form-item><el-form-item label="厂家 / 品牌"><el-input v-model="part.brand" /></el-form-item><el-form-item label="更换原因"><el-input v-model="part.reason" /></el-form-item><el-form-item label="配件备注"><el-input v-model="part.notes" /></el-form-item></div><p v-if="part.unit_price_cents" class="hint">历史配件单价 {{yuan(part.unit_price_cents)}} · 历史配件合计 ¥{{partTotal(part)}}</p><p class="hint">质保截止：{{warrantyUntil(part)}}</p><el-button text type="danger" @click="removePart(index)">移除配件</el-button></div></div>
          <div class="form-grid"><el-form-item label="开始时间"><el-input v-model="eventForm.started_at" type="datetime-local" /></el-form-item><el-form-item label="结束时间"><el-input v-model="eventForm.ended_at" type="datetime-local" /></el-form-item><el-form-item label="工作人员"><el-input v-model="eventForm.workers" /></el-form-item><el-form-item label="维保 / 维修单位"><el-input v-model="eventForm.company" /></el-form-item><el-form-item v-if="!hasPartReplacement" label="一般登记费用（元）"><el-input v-model="eventForm.cost_yuan" type="number" min="0" step="0.01" /></el-form-item><el-form-item label="同时更新电梯状态（可选）"><el-select v-model="eventForm.elevator_status" placeholder="不改变当前状态"><el-option label="不改变当前状态" value=""/><el-option v-for="state in ['正常','故障','维修中','停梯','待处理']" :key="state" :label="state" :value="state"/></el-select></el-form-item><el-form-item label="完成情况"><el-switch v-model="eventForm.completed" active-text="已完成" inactive-text="未完成" /></el-form-item></div><el-form-item label="备注"><el-input v-model="eventForm.notes" type="textarea" :rows="2" /></el-form-item><div class="sub-form">
            <h2>照片和附件</h2><p class="hint">请按现场处理过程排列照片，可用“上移、下移”调整。导出图号与这里的照片顺序一致。</p>
            <div class="upload-choices">
              <label>选择照片或文件（每个不超过 20 MB）<input type="file" multiple accept=".jpg,.jpeg,.png,.webp,.pdf,.doc,.docx,.xls,.xlsx" @change="filesChanged($event)"></label>
              <label>手机拍现场照片<input type="file" accept="image/*" capture="environment" @change="filesChanged($event,'工作现场照片')"></label>
            </div>
            <div v-for="(item,index) in eventFiles" :key="index" class="queued-file">
              <span :title="item.file.name">{{item.file.name}}</span>
              <el-select v-model="item.category" aria-label="附件分类">
                <el-option v-for="category in attachmentCategories" :key="category" :label="category" :value="category" />
              </el-select>
              <div class="file-order-actions"><el-button text :disabled="index===0" @click="moveQueuedFile(index,-1)">上移</el-button><el-button text :disabled="index===eventFiles.length-1" @click="moveQueuedFile(index,1)">下移</el-button><el-button text type="danger" @click="eventFiles.splice(index,1)">移除</el-button></div>
            </div>
            <div v-for="(f,index) in existingFiles" :key="f.id" class="existing-file"><el-image v-if="f.relative_path.startsWith('photos/')" :src="`/api/attachments/${f.id}`" fit="cover" class="order-photo" :preview-src-list="existingFiles.filter(x=>x.relative_path.startsWith('photos/')).map(x=>`/api/attachments/${x.id}`)" :initial-index="existingFiles.slice(0,index).filter(x=>x.relative_path.startsWith('photos/')).length"/><a :href="`/api/attachments/${f.id}?download=true`">{{f.relative_path.startsWith('photos/')?'照片 '+(existingFiles.slice(0,index).filter(x=>x.relative_path.startsWith('photos/')).length+1):f.original_name}}</a><div class="file-order-actions"><el-button text :disabled="busy||index===0" @click="moveExistingFile(index,-1)">上移</el-button><el-button text :disabled="busy||index===existingFiles.length-1" @click="moveExistingFile(index,1)">下移</el-button><el-button text type="danger" @click="removeAttachment(f.id)">移除</el-button></div></div>
          </div>
          <p v-if="savedEventId && !route.path.includes('/edit')" class="hint">文字记录已保存；再次保存会更新同一条记录，不会重复新增。</p><div class="form-actions"><el-button @click="router.back()">取消</el-button><el-button native-type="submit" type="primary" size="large" :loading="busy">保存记录</el-button></div></el-form></div></section>

        <OperationTimeline v-if="page==='records'" :options="eventElevators" :elevator-labels="elevatorLabels" :api="api"/>

        <section v-if="page==='search'" class="search-page"><div class="page-heading"><div><div class="eyebrow">跨档案检索</div><h1>{{query.trim()?'搜索结果':'查找电梯与工作记录'}}</h1><p>在顶部输入关键词并回车。楼栋、编号、配件、维修内容都可以查找。</p></div></div><div v-if="searchPending" class="panel empty">正在查找…</div><div v-else-if="!searched" class="search-intro panel"><svg class="search-illustration" viewBox="0 0 80 80" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="15" y="8" width="38" height="55" rx="3"/><path d="M23 20h22 M23 29h22 M23 38h12"/><circle cx="51" cy="52" r="14"/><path d="m61 62 13 13"/></svg><h2>记得一点线索，就能开始查找</h2><p>例如输入“18栋 门锁”，查找这栋楼有关门锁的记录。</p><div class="search-examples"><button @click="query='门锁';search()">配件名称：门锁 →</button><button @click="query='维保';search()">工作内容：维保 →</button></div></div><template v-else><div class="search-summary">“{{String(route.query.q||'')}}” <span>找到 {{searchResult.elevators.length}} 部电梯 · {{searchResult.events.length}} 条工作记录</span></div><p v-if="searchResult.truncated" class="hint">结果较多，仅显示前100项，请补充楼栋或日期缩小范围。</p><div class="search-results"><section class="panel"><h2>电梯档案 <span class="small-label">{{searchResult.elevators.length}}</span></h2><div v-if="!searchResult.elevators.length" class="empty compact">没有匹配的电梯档案</div><button v-for="e in searchResult.elevators" :key="e.id" class="list-row" @click="nav(`/elevators/${e.id}`)"><b>{{placeLabel(e)}}</b><span>{{e.status}} →</span></button></section><section class="panel"><h2>工作记录 <span class="small-label">{{searchResult.events.length}}</span></h2><div v-if="!searchResult.events.length" class="empty compact">没有匹配的工作记录，试试更短的关键词。</div><button v-for="e in searchResult.events" :key="e.id" class="list-row" @click="nav(`/elevators/${e.elevator_id}?event_id=${e.id}`)"><span><b>{{e.title}}</b><small>{{placeLabel(e)}} · {{e.type}} · {{e.occurred_on}}</small></span><span>→</span></button></section></div></template></section>

        <section v-if="page==='reminders'"><div class="page-heading"><div><div class="eyebrow">按期维护 · 提前安排</div><h1>提醒中心</h1><p>质保、维保和年检到期情况由现有资料自动计算。</p></div></div><section class="panel"><div v-if="!reminders.length" class="empty">当前没有到期或临近到期项目</div><button v-for="r in reminders" :key="r.kind+(r.part_id||r.elevator_id)" class="list-row" @click="nav(`/elevators/${r.elevator_id}`)"><span><b>{{placeLabel(r)}} · {{r.kind}} {{r.name||''}}</b><small>到期日期：{{r.due_on}}</small></span><em :class="r.days_left<0?'danger':'warning'">{{r.level}}</em></button></section></section>

        <PhotoLibrary v-if="page==='photos'" :elevators="eventElevators" :api="api"/>
        <ArchiveEditor v-if="page==='export'" :buildings="buildings" :units="units" :elevators="elevators" :elevator-labels="elevatorLabels" :api="api" :download="download"/>

        <section v-if="page==='admin'"><div class="page-heading"><div><div class="eyebrow">本机与局域网 · 版本 2.0.2</div><h1>系统设置</h1><p>备份资料、设置二维码地址、管理楼栋与单元，或恢复误删资料。</p></div></div><section class="panel"><h2>数据备份</h2><p>备份包含数据库和全部附件。下载后请另存到移动硬盘或另一台电脑。</p><el-button type="primary" :loading="busy" @click="backup">立即备份并下载</el-button><p class="hint">服务器保留最近30份备份。恢复方法见 BACKUP_AND_RESTORE.md。</p></section><section class="panel network-settings"><div class="panel-head"><div><h2>局域网访问与二维码</h2><p class="hint">填写主机在物业站网络中的地址，所有电梯二维码统一使用这个地址。</p></div><span class="small-label">{{network.source==='saved'?'已保存':'尚未固定地址'}}</span></div><p v-if="!networkReady" class="hint">正在读取局域网设置…</p><el-form v-else label-position="top" @submit.prevent="saveNetwork"><el-form-item label="局域网访问地址"><el-input v-model="networkDraft" placeholder="http://192.168.1.20:8766"/></el-form-item><div v-if="network.candidates.length" class="network-candidates"><span>主机检测到：</span><button v-for="address in network.candidates" :key="address" type="button" @click="networkDraft=address">{{address}}</button></div><p class="hint">用手机连接同一网络，先打开此地址确认可以访问，再保存并打印。建议固定主机 IP；更换地址后需要重新打印旧二维码。</p><el-button type="primary" native-type="submit" :loading="busy">保存访问地址</el-button></el-form></section><section class="panel"><div class="panel-head"><h2>楼栋与单元</h2><div class="button-group"><el-button @click="openBuilding()">新增楼栋</el-button><el-button :disabled="!buildings.length" @click="openUnit()">新增单元</el-button></div></div><div v-for="b in buildings" :key="b.id" class="manage-place"><b>{{b.name}}</b><el-button size="small" @click="openBuilding(b)">改名</el-button><el-button size="small" type="danger" text @click="removePlace('building',b.id)">删除空楼栋</el-button><div v-for="u in units.filter(x=>x.building_id===b.id)" :key="u.id" class="manage-unit">{{u.name}}<el-button size="small" @click="openUnit(u)">改名</el-button><el-button size="small" type="danger" text @click="removePlace('unit',u.id)">删除空单元</el-button></div></div></section><section class="panel"><h2>已删除资料</h2><p class="hint">可恢复误删资料。恢复下级资料前，请先恢复所属楼栋、单元或电梯。状态变更需人工核对。</p><div v-if="!trash.length" class="empty compact">暂无已删除资料</div><div v-for="item in trash" :key="item.kind+item.id" class="list-row"><span><b>{{item.label}} · {{item.name}}</b><small>{{displayTimestamp(item.deleted_at)}}</small></span><el-button @click="restoreItem(item)">恢复</el-button></div></section></section>
        <footer v-if="page!=='records'" class="app-footer"><span><span class="local-dot"></span>昌福里社区27区党群物业服务站 · 电梯管理台账</span><span>一梯一档 · 2.0.2</span></footer>
      </main>
    </div>
  </div>

  <el-dialog :model-value="dialog!==''" @update:model-value="v => { if (!v) dialog = '' }" :title="dialog==='qr'?'电梯档案二维码':dialog==='building'?(buildingForm.id?'编辑楼栋':'新增楼栋'):dialog==='unit'?(unitForm.id?'编辑单元':'新增单元'):dialog==='elevator'?(elevatorForm.id?'编辑电梯':'新增电梯'):'导入电梯档案'" width="min(94vw,560px)">
    <div v-if="dialog==='qr'&&currentElevator" class="qr-dialog"><div class="qr-label"><div class="eyebrow">昌福里社区27区党群物业服务站 · 一梯一档</div><h2>{{placeLabel(currentElevator)}}</h2><p>{{currentElevator.equipment_number||'电梯工作档案'}}</p><img v-if="qrInfo.url" :src="qrImage" alt="本部电梯档案二维码"><div v-else class="qr-placeholder">尚未确定局域网地址，暂不生成二维码。</div><strong>连接物业站网络 · 扫码查看档案</strong><a v-if="qrInfo.url" class="qr-target" :href="qrInfo.url" target="_blank" rel="noopener">{{qrInfo.url}}</a></div><p class="hint">手机连接物业站网络后，扫码直接打开这部电梯的档案。</p><details class="qr-configuration" :open="!qrInfo.url"><summary>设置局域网访问地址</summary><p v-if="!networkReady" class="hint">正在读取局域网设置…</p><el-form v-else label-position="top" @submit.prevent="saveNetwork"><el-form-item label="主机局域网访问地址"><el-input v-model="networkDraft" placeholder="http://192.168.1.20:8766"/></el-form-item><div class="network-candidates"><button v-for="address in network.candidates" :key="address" type="button" @click="networkDraft=address">使用 {{address}}</button></div><p class="hint">请先用手机打开上方地址确认能访问。保存后所有电梯二维码都会使用该主机地址；更改地址需重印旧标签。</p><el-button native-type="submit" :loading="busy">保存访问地址</el-button></el-form></details><div class="form-actions"><el-button :disabled="!qrInfo.url" @click="download(qrImage,qrFilename)">下载二维码图片</el-button><el-button type="primary" :disabled="!qrInfo.url" :loading="busy" @click="printPage">打印电梯标签</el-button></div></div>
    <el-form v-if="dialog==='building'" label-position="top" @submit.prevent="addBuilding"><el-form-item label="楼栋名称"><el-input v-model="buildingForm.name" placeholder="例如：18栋" /></el-form-item><el-button type="primary" native-type="submit" :loading="busy">保存</el-button></el-form>
    <el-form v-if="dialog==='unit'" label-position="top" @submit.prevent="addUnit"><el-form-item label="所属楼栋"><el-select v-model="unitForm.building_id" :disabled="!!unitForm.id" class="full"><el-option v-for="b in buildings" :key="b.id" :label="b.name" :value="b.id" /></el-select></el-form-item><el-form-item label="单元名称"><el-input v-model="unitForm.name" placeholder="例如：1单元" /></el-form-item><el-button type="primary" native-type="submit" :loading="busy">保存</el-button></el-form>
    <el-form v-if="dialog==='elevator'" label-position="top" @submit.prevent="saveElevator"><div class="form-grid">
      <template v-if="elevatorForm.building_number !== undefined">
        <el-form-item label="楼栋 *">
          <el-input v-model="elevatorForm.building_number" inputmode="numeric" pattern="[0-9]+" maxlength="39" required placeholder="例如 18">
            <template #append>栋</template>
          </el-input>
        </el-form-item>
        <el-form-item label="单元口 *">
          <el-input v-model="elevatorForm.unit_number" inputmode="numeric" pattern="[0-9]+" maxlength="39" required placeholder="例如 1">
            <template #append>口</template>
          </el-input>
        </el-form-item>
        <el-form-item label="梯号 *">
          <el-radio-group v-model="elevatorForm.elevator_number">
            <el-radio value="1">1号电梯</el-radio>
            <el-radio value="2">2号电梯</el-radio>
          </el-radio-group>
        </el-form-item>
      </template>
      <template v-else>
        <el-form-item label="楼栋 *"><el-input v-model="elevatorForm.building_name" /></el-form-item>
        <el-form-item label="单元 *"><el-input v-model="elevatorForm.unit_name" /></el-form-item>
        <el-form-item label="电梯名称 / 梯号 *"><el-input v-model="elevatorForm.name" /></el-form-item>
      </template>
      <el-form-item label="内部编号"><el-input v-model="elevatorForm.internal_number" /></el-form-item><el-form-item label="使用登记证号"><el-input v-model="elevatorForm.equipment_number" /></el-form-item><el-form-item label="品牌"><el-input v-model="elevatorForm.brand" /></el-form-item><el-form-item label="设备型号"><el-input v-model="elevatorForm.model" /></el-form-item><el-form-item label="投入使用时间"><el-input v-model="elevatorForm.started_on" type="date" /></el-form-item><el-form-item label="出厂日期"><el-input v-model="elevatorForm.manufactured_on" type="date" /></el-form-item><el-form-item label="维保单位"><el-input v-model="elevatorForm.maintenance_company" /></el-form-item><el-form-item label="维保人姓名"><el-input v-model="elevatorForm.maintenance_contact" /></el-form-item><el-form-item label="维保联系人电话"><el-input v-model="elevatorForm.maintenance_phone" /></el-form-item><el-form-item label="下次维保日期"><el-input v-model="elevatorForm.maintenance_due_on" type="date" /></el-form-item><el-form-item label="年检日期"><el-input v-model="elevatorForm.inspection_on" type="date" /></el-form-item><el-form-item label="该电梯状态"><el-select v-model="elevatorForm.status" class="full"><el-option v-for="s in ['正常','故障','维修中','停梯','待处理']" :key="s" :label="s" :value="s" /></el-select></el-form-item></div><el-form-item label="备注"><el-input v-model="elevatorForm.notes" type="textarea" /></el-form-item><el-button type="primary" native-type="submit" :loading="busy">保存</el-button></el-form>
    <div v-if="dialog==='import'" class="import-dialog"><p>可选择电梯档案模板，或同时含“特种设备台账”和“故障消缺记录”的正式表格。</p><a class="template-link" href="/api/elevator-archives/export?template=true" download>↓ 下载 Excel 填写模板</a><label class="import-picker">选择台账表格<input type="file" accept=".xlsx" :disabled="busy" @change="archiveChanged"/></label><p class="hint">支持 .xlsx，最多 5 MB、500 行电梯档案。检查表格后核对报告，再确认写入。档案模板按位置跳过已有电梯。正式表格同时检查故障记录，标有“维修资金”时勾选动用住宅维修资金，金额可留空。</p><div v-if="importResult" aria-live="polite"><div v-if="!importResult.valid" class="import-errors"><b>本次未写入任何档案。请核对下方提示后重新检查表格。</b><p v-for="error in importResult.errors" :key="error">{{error}}</p><p v-if="importResult.error_count>20">还有 {{importResult.error_count-20}} 个问题。</p></div><template v-else><div class="import-summary">{{importResult.committed?'导入完成':'检查通过'}}：{{importResult.added}} 部{{importResult.committed?'已新增':'待新增'}} · {{importResult.skipped}} 部已有档案跳过</div><section v-if="importResult.format==='official'">
        <p>工作记录 {{importResult.events_added}} 条{{importResult.committed?'已新增':'待新增'}}，{{importResult.events_skipped}} 条重复跳过，{{importResult.templates_skipped}} 行空白模板跳过。</p>
        <p v-for="warning in importResult.warnings" :key="warning">{{warning}}</p>
        <template v-if="importResult.unmatched.length"><b>待核对位置（{{importResult.unmatched.length}} 条，本次跳过）</b>
          <p v-for="item in importResult.unmatched" :key="item.row">故障表第 {{item.row}} 行 · {{item.location||'位置空白'}} · {{item.reason}}</p>
          <p>请在原表中补全位置，再次导入。</p>
        </template>
      </section><div class="import-rows"><div v-for="r in importResult.rows" :key="r.row"><span>{{r.place}}</span><b>{{r.action}}</b></div></div></template></div>
      <div class="form-actions"><el-button v-if="!importResult?.committed" :disabled="!archiveFile" :loading="busy" @click="importArchives(false)">检查表格</el-button>
        <el-button v-if="canConfirmImport" type="primary" :disabled="busy" @click="importArchives(true)">确认导入 {{importResult.added}} 部电梯<template v-if="importResult.format==='official'">、{{importResult.events_added}} 条工作记录</template></el-button>
        <el-button v-if="importResult?.committed" type="primary" @click="dialog=''">完成</el-button></div>
    </div>
  </el-dialog>
  <section v-if="page==='detail'&&currentElevator&&qrInfo.url" class="qr-print-sheet"><div class="brand-mark">27</div><p>昌福里社区27区党群物业服务站 · 电梯电子档案</p><h1>{{placeLabel(currentElevator)}}</h1><p>{{currentElevator.equipment_number}}</p><img :src="qrImage" alt="电梯档案二维码"><h2>连接物业站网络 · 扫码查看档案</h2><p>扫码即可查看本部电梯的资料和工作记录</p><p class="qr-target">{{qrInfo.url}}</p></section>
</template>
