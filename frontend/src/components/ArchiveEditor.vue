<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

type Block = { id:string; type:'heading'|'paragraph'|'image'; text?:string; attachment_id?:string; caption?:string }
type Photo = { id:string; category:string; original_name:string; display_name?:string; event_title:string; event_date:string; elevator_label:string; url:string; available:boolean; unavailable_reason?:string }
type Draft = { id:number; title:string; revision:number; created_by_name:string; updated_at:string; filters:any; metadata:{community:string;scope_label:string;period_label:string}; source_warnings:string[]; blocks:Block[]; images:Photo[]; attachment_directory:any[] }
const props = defineProps<{
  buildings:any[]; units:any[]; elevators:any[];
  api:(path:string, options?:any)=>Promise<any>;
  download:(path:string, filename?:string)=>void;
}>()
const router = useRouter()
const filters = ref<any>({scope:'all',building_id:null,unit_id:null,elevator_id:null,start:'',end:'',type:'全部',photos:true,directory:true,package:false})
const draft = ref<Draft|null>(null), drafts = ref<any[]>([])
const mode = ref<'select'|'edit'|'preview'>('select')
const busy = ref(false), listLoading = ref(false), listError = ref(''), error = ref(''), conflict = ref(false)
const savedContent = ref(''), cost = ref<any>(null)
const pickerAt = ref<number|null>(null), pickerSearch = ref(''), insertAt = ref<number|null>(null)
const dragging = ref(''), dropAt = ref<number|null>(null), announcement = ref('')
const lastDeleted = ref<{block:Block;index:number}|null>(null)
const directory = ref(true), packageOriginals = ref(false)
const periodChoice = ref('all')
const activePeriod = computed(() => [periodChoice.value,'all','month','year'].find(value=>{
  const range=periodRange(value)
  return filters.value.start===range.start&&filters.value.end===range.end
})||'')
const workTypes = ['全部','日常维保','故障','维修','配件更换','检验/检查','资料补充','其他']
const content = () => JSON.stringify({title:draft.value?.title,blocks:draft.value?.blocks})
const dirty = computed(() => !!draft.value && content() !== savedContent.value)
const exportUnits = computed(() => props.units.filter(x=>x.building_id===filters.value.building_id))
const exportElevators = computed(() => props.elevators.filter(x=>(!filters.value.building_id||x.building_id===filters.value.building_id)&&(!filters.value.unit_id||x.unit_id===filters.value.unit_id)))
const place = (x:any) => `${x.building_name}${x.unit_name}${x.elevator_name||x.name}`
const scopeName = computed(() => {
  const f=filters.value
  if(f.scope==='all') return '全部电梯'
  const building=props.buildings.find(x=>x.id===f.building_id)?.name||'请选择楼栋'
  if(f.scope==='building') return building
  const unit=props.units.find(x=>x.id===f.unit_id)?.name||'请选择单元'
  if(f.scope==='unit') return `${building} ${unit}`
  const elevator=props.elevators.find(x=>x.id===f.elevator_id)
  return elevator?place(elevator):'请选择电梯'
})
const exportCount = computed(() => props.elevators.filter(e=>filters.value.scope==='all'||(e.building_id===filters.value.building_id&&(filters.value.scope==='building'||(e.unit_id===filters.value.unit_id&&(filters.value.scope==='unit'||e.id===filters.value.elevator_id))))).length)
const imageNumbers = computed(() => {
  let number=0
  return Object.fromEntries((draft.value?.blocks||[]).filter(x=>x.type==='image').map(x=>[x.id,++number]))
})
const photos = computed(() => (draft.value?.images||[]).filter(x=>!pickerSearch.value||`${x.event_title} ${x.event_date} ${x.elevator_label} ${x.category}`.includes(pickerSearch.value.trim())))
const unusedPhotos = computed(() => (draft.value?.images||[]).filter(x=>x.available&&!draft.value?.blocks.some(b=>b.type==='image'&&b.attachment_id===x.id)).length)
const previewDirectory = computed(() => {
  const numbers=Object.fromEntries((draft.value?.blocks||[]).filter(x=>x.type==='image').map(x=>[x.attachment_id,`图${imageNumbers.value[x.id]}`]))
  const entries=(draft.value?.attachment_directory||[]).map(x=>({...x,reference:x.is_photo?(numbers[x.id]||'未编入正文'):x.reference}))
  const position=Object.fromEntries((draft.value?.blocks||[]).filter(x=>x.type==='image').map((x,index)=>[x.attachment_id,index]))
  return entries.sort((a,b)=>(position[a.id]??Number.MAX_SAFE_INTEGER)-(position[b.id]??Number.MAX_SAFE_INTEGER)||(a.source_order??0)-(b.source_order??0))
})
const photoFor = (block:Block) => draft.value?.images.find(x=>x.id===block.attachment_id)
const photoUsed = (id:string) => !!draft.value?.blocks.some(x=>x.type==='image'&&x.attachment_id===id)
const savedTime = computed(() => draft.value?.updated_at?.replace('T',' ').slice(0,19)||'')
const blockLabel = (block:Block) => block.type==='heading'?'小标题':block.type==='paragraph'?'正文':`图片 · 图${imageNumbers.value[block.id]}`

async function confirmDiscard() {
  if(!dirty.value) return true
  try {await ElMessageBox.confirm('当前编排尚未保存，继续会丢失这些修改。','离开未保存的编排',{confirmButtonText:'放弃修改并继续',cancelButtonText:'继续编辑',type:'warning'});return true}
  catch {return false}
}
async function act(action:()=>Promise<void>) {
  if(busy.value) return
  busy.value=true;error.value=''
  try {await action()}
  catch(e:any) {conflict.value=e.status===409;error.value=e.message||'操作失败，请重试';ElMessage.error(error.value)}
  finally {busy.value=false}
}
function setDraft(value:Draft) {
  draft.value=value;savedContent.value=content();conflict.value=false;error.value='';lastDeleted.value=null;insertAt.value=null
  const summary={id:value.id,title:value.title,revision:value.revision,created_by_name:value.created_by_name,updated_at:value.updated_at}
  const index=drafts.value.findIndex(x=>x.id===value.id)
  if(index>=0) drafts.value.splice(index,1,summary)
  else drafts.value.unshift(summary)
}
async function loadDrafts() {
  listLoading.value=true;listError.value=''
  try {drafts.value=await props.api('/export-drafts')}
  catch(e:any) {listError.value=e.message||'草稿列表读取失败'}
  finally {listLoading.value=false}
}
function periodRange(value:string) {
  const d=new Date(),year=d.getFullYear(),month=String(d.getMonth()+1).padStart(2,'0'),day=String(d.getDate()).padStart(2,'0')
  return {start:value==='year'?`${year}-01-01`:value==='month'?`${year}-${month}-01`:'',end:value==='all'?'':`${year}-${month}-${day}`}
}
function period(value:string) {
  const range=periodRange(value)
  periodChoice.value=value
  filters.value.start=range.start
  filters.value.end=range.end
  cost.value=null
}
function validateScope() {
  const f=filters.value
  if(!exportCount.value) throw new Error('请先选择完整的电梯范围')
  if(f.start&&f.end&&f.start>f.end) throw new Error('开始日期不能晚于结束日期')
}
async function generate() {
  if(!await confirmDiscard()) return
  await act(async()=>{
    validateScope()
    const result=await props.api('/export-drafts',{method:'POST',body:JSON.stringify(filters.value)})
    setDraft(result);directory.value=filters.value.directory;packageOriginals.value=filters.value.package;mode.value='edit'
    ElMessage.success('编排稿已生成，可以逐段修改')
  })
}
async function openDraft(id:number) {
  if(!await confirmDiscard()) return
  await act(async()=>{
    const result=await props.api(`/export-drafts/${id}`)
    setDraft(result);directory.value=result.filters.directory!==false;packageOriginals.value=!!result.filters.package;mode.value='edit'
  })
}
async function backToRange() {
  if(!await confirmDiscard()) return
  draft.value=null;mode.value='select';error.value='';conflict.value=false;insertAt.value=null
}
async function persist() {
  if(!draft.value) throw new Error('请先生成或打开编排稿')
  const result=await props.api(`/export-drafts/${draft.value.id}`,{method:'PUT',body:JSON.stringify({title:draft.value.title,blocks:draft.value.blocks,revision:draft.value.revision})})
  setDraft(result)
  return result as Draft
}
async function save() {await act(async()=>{await persist();ElMessage.success('草稿已保存')})}
async function exportDraft() {
  await act(async()=>{
    const current=dirty.value?await persist():draft.value
    if(!current) throw new Error('请先生成编排稿')
    const result=await props.api(`/export-drafts/${current.id}/prepare`,{method:'POST',body:JSON.stringify({revision:current.revision,package:packageOriginals.value,directory:directory.value})})
    props.download(result.download,result.filename);ElMessage.success('编排档案已生成并开始下载')
  })
}
async function exportOriginal() {
  await act(async()=>{validateScope();const result=await props.api('/export/prepare',{method:'POST',body:JSON.stringify(filters.value)});props.download(result.download,result.filename);ElMessage.success('原始档案已生成并开始下载')})
}
async function lookupCosts() {
  await act(async()=>{
    validateScope();const f=filters.value,params=new URLSearchParams({type:f.type})
    const key=({building:'building_id',unit:'unit_id',elevator:'elevator_id'} as any)[f.scope]
    if(key) params.set(key,String(f[key]))
    for(const key of ['start','end']) if(f[key]) params.set(key,f[key])
    cost.value=await props.api('/costs?'+params)
  })
}
function newId() {return `block-${Date.now().toString(36)}-${Math.random().toString(36).slice(2,10)}`}
async function insertBlock(type:'heading'|'paragraph',index:number) {
  if(!draft.value) return
  if(draft.value.blocks.length>=5000) {ElMessage.warning('编排稿最多5000段，请先移除部分内容');return}
  const block:Block={id:newId(),type,text:''}
  draft.value.blocks.splice(index,0,block);insertAt.value=null;announcement.value=`已插入${type==='heading'?'小标题':'正文'}`
  await nextTick();document.getElementById(`input-${block.id}`)?.focus()
}
function openPhotos(index:number) {pickerAt.value=index;pickerSearch.value='';insertAt.value=null}
function insertPhoto(photo:Photo) {
  if(!draft.value||pickerAt.value===null||!photo.available||photoUsed(photo.id)) return
  if(draft.value.blocks.length>=5000) {ElMessage.warning('编排稿最多5000段，请先移除部分内容');return}
  draft.value.blocks.splice(pickerAt.value,0,{id:newId(),type:'image',attachment_id:photo.id,caption:photo.category||''})
  pickerAt.value=null;announcement.value='图片已插入编排稿'
}
function moveBlock(index:number,step:number) {
  if(!draft.value) return
  const to=index+step
  if(to<0||to>=draft.value.blocks.length) return
  const [block]=draft.value.blocks.splice(index,1);draft.value.blocks.splice(to,0,block)
  announcement.value=`${blockLabel(block)}已移至第${to+1}段`;insertAt.value=null
}
async function removeBlock(index:number) {
  if(!draft.value) return
  try {
    await ElMessageBox.confirm('从编排稿中移除此段？原工作记录和原始照片会保留。','移除段落',{confirmButtonText:'移除此段',cancelButtonText:'取消',type:'warning'})
    const [block]=draft.value.blocks.splice(index,1);lastDeleted.value={block,index};insertAt.value=null;announcement.value='已移除一段，可撤销本次移除'
  } catch {}
}
function undoDelete() {
  if(!draft.value||!lastDeleted.value) return
  const {block,index}=lastDeleted.value
  if(block.type==='image'&&photoUsed(block.attachment_id||'')) {ElMessage.warning('这张照片已重新插入');lastDeleted.value=null;return}
  draft.value.blocks.splice(Math.min(index,draft.value.blocks.length),0,block);lastDeleted.value=null;announcement.value='已撤销移除'
}
function startDrag(event:DragEvent,id:string) {
  if(!event.dataTransfer) return
  dragging.value=id;event.dataTransfer.effectAllowed='move';event.dataTransfer.setData('text/plain',id)
}
function finishDrag() {dragging.value='';dropAt.value=null}
function dropBlock(event:DragEvent,index:number) {
  event.preventDefault()
  const from=draft.value?.blocks.findIndex(x=>x.id===dragging.value)??-1
  if(!draft.value||from<0) return finishDrag()
  const [block]=draft.value.blocks.splice(from,1),to=index>from?index-1:index
  draft.value.blocks.splice(to,0,block);announcement.value=`${blockLabel(block)}已移至第${to+1}段`;insertAt.value=null;finishDrag()
}
function beforeUnload(event:BeforeUnloadEvent) {if(dirty.value){event.preventDefault();event.returnValue=''}}
defineExpose({confirmLeave:confirmDiscard})
const removeGuard=router.beforeEach(async()=>!dirty.value||await confirmDiscard())
onMounted(()=>{loadDrafts();window.addEventListener('beforeunload',beforeUnload)})
onBeforeUnmount(()=>{removeGuard();window.removeEventListener('beforeunload',beforeUnload)})
</script>

<template>
  <section class="archive-workspace">
    <div class="page-heading">
      <div><div class="eyebrow">检查汇报 · 资料归档</div><h1>{{mode==='select'?'工作档案导出':mode==='edit'?'编排工作档案':'工作档案预览'}}</h1><p>{{mode==='select'?'先选择工作范围，再把文字与照片整理成一份正式档案。':mode==='edit'?'逐段修改文字、穿插照片，按汇报需要调整顺序。':'按当前编排显示内容顺序；实际分页以 Word / WPS 为准。'}}</p></div>
      <span class="format-badge">WORD / DOCX</span>
    </div>
    <div v-if="error" class="archive-error" role="alert"><span>{{error}}</span><el-button v-if="conflict&&draft" text :disabled="busy" @click="openDraft(draft.id)">重新读取已保存稿</el-button></div>

    <div v-if="mode==='select'" class="archive-select-layout">
      <section class="panel export-settings">
        <el-form label-position="top" :disabled="busy" @change="cost=null">
          <section class="export-step"><div class="step-heading"><span>1</span><div><h2>选择电梯范围</h2><p>可以为一部电梯，也可以为整栋楼整理资料。</p></div></div>
            <el-radio-group v-model="filters.scope" class="scope-options"><el-radio-button value="all">全部电梯</el-radio-button><el-radio-button value="building">某楼栋</el-radio-button><el-radio-button value="unit">某单元</el-radio-button><el-radio-button value="elevator">某部电梯</el-radio-button></el-radio-group>
            <div class="form-grid scope-fields">
              <el-form-item v-if="filters.scope!=='all'" label="楼栋"><el-select v-model="filters.building_id" placeholder="选择楼栋" @change="filters.unit_id=null;filters.elevator_id=null"><el-option v-for="b in buildings" :key="b.id" :label="b.name" :value="b.id"/></el-select></el-form-item>
              <el-form-item v-if="['unit','elevator'].includes(filters.scope)" label="单元"><el-select v-model="filters.unit_id" placeholder="选择单元" @change="filters.elevator_id=null"><el-option v-for="u in exportUnits" :key="u.id" :label="u.name" :value="u.id"/></el-select></el-form-item>
              <el-form-item v-if="filters.scope==='elevator'" label="电梯"><el-select v-model="filters.elevator_id" placeholder="选择电梯"><el-option v-for="e in exportElevators" :key="e.id" :label="place(e)" :value="e.id"/></el-select></el-form-item>
            </div>
          </section>
          <section class="export-step"><div class="step-heading"><span>2</span><div><h2>确定统计周期</h2><p>不填写日期时，包含全部历史工作。</p></div></div>
            <el-radio-group :model-value="activePeriod" class="period-shortcuts scope-options" aria-label="统计周期快捷选择" @change="value=>period(String(value))"><el-radio-button value="month">本月</el-radio-button><el-radio-button value="year">本年</el-radio-button><el-radio-button value="all">全部时间</el-radio-button></el-radio-group>
            <div class="form-grid"><el-form-item label="开始日期"><el-input v-model="filters.start" type="date"/></el-form-item><el-form-item label="结束日期"><el-input v-model="filters.end" type="date"/></el-form-item></div>
            <el-form-item label="工作类型"><el-select v-model="filters.type"><el-option v-for="t in workTypes" :key="t" :label="t" :value="t"/></el-select></el-form-item>
          </section>
          <section class="export-step"><div class="step-heading"><span>3</span><div><h2>选择档案内容</h2></div></div>
            <div class="export-options"><el-checkbox v-model="filters.photos">带入工作照片<small>生成后可在任意段落之间重新插入和排序</small></el-checkbox><el-checkbox v-model="filters.directory">附上附件目录<small>列出本次范围内的照片、维修单等原始资料</small></el-checkbox><el-checkbox v-model="filters.package">同时打包原始附件<small>下载 ZIP，内含 Word 和原始资料</small></el-checkbox></div>
          </section>
          <div class="archive-create-actions"><el-button type="primary" size="large" class="full" :loading="busy" :disabled="!exportCount" @click="generate">生成编排稿 →</el-button><p class="hint">{{scopeName}} · {{exportCount}} 部电梯。编排稿独立保存，修改稿件不改变工作台账。</p><el-button text :loading="busy" :disabled="!exportCount" @click="exportOriginal">直接导出原始档案</el-button><el-button text :loading="busy" :disabled="!exportCount" @click="lookupCosts">查看费用汇总</el-button><p v-if="cost" class="cost-result">{{cost.record_count}} 条记录 · ¥{{((cost.cost_cents||0)/100).toFixed(2)}}</p></div>
        </el-form>
      </section>
      <aside class="archive-draft-rail"><div class="panel-head"><h2>已保存的编排稿</h2><el-button text :loading="listLoading" @click="loadDrafts">刷新</el-button></div><p class="hint">继续整理以前的稿件，或在左侧生成一份新稿。</p><div v-if="listError" class="archive-list-error" role="alert">{{listError}}<el-button text @click="loadDrafts">重试</el-button></div><p v-else-if="!drafts.length&&!listLoading" class="archive-no-drafts">尚无编排稿</p><div v-else class="archive-draft-list"><button v-for="item in drafts" :key="item.id" type="button" :disabled="busy" @click="openDraft(item.id)"><b>{{item.title}}</b><span>{{item.updated_at?.replace('T',' ').slice(0,16)}}</span><small>{{item.created_by_name}} · 第 {{item.revision}} 版</small></button></div><div class="archive-selection-summary"><b>{{scopeName}}</b><span>{{filters.start||'最早记录'}} 至 {{filters.end||'最新记录'}}</span><small>编制单位：昌福里社区27区党群物业服务站</small></div><div class="archive-rail-note"><b>像整理一份纸质档案</b><p>正文、小标题、照片都可单独调整。生成后先编排，再预览，最后导出。</p></div></aside>
    </div>

    <template v-else-if="draft">
      <div v-if="draft.source_warnings?.length" class="archive-error" role="alert"><span>{{draft.source_warnings.join('；')}}。请恢复来源资料，或保留当前稿后重新生成。缺失的源资料恢复前无法导出。</span></div>
      <div class="archive-toolbar"><div class="archive-toolbar-start"><el-button :disabled="busy" @click="backToRange">← 返回范围</el-button><span class="archive-save-state" :class="{unsaved:dirty}" aria-live="polite"><i></i>{{dirty?'有未保存的修改':`已保存 · ${savedTime}`}}</span></div><div class="archive-toolbar-actions"><el-button v-if="mode==='preview'" :disabled="busy" @click="mode='edit'">返回编辑</el-button><el-button v-else :disabled="busy" @click="mode='preview';insertAt=null">预览</el-button><el-button :loading="busy" @click="save">保存草稿</el-button><el-button type="primary" :loading="busy" @click="exportDraft">{{packageOriginals?'导出 ZIP':'导出 Word'}}</el-button></div></div>
      <div class="archive-document-options"><span>本稿 {{draft.blocks.length}} 段 · {{draft.blocks.filter(x=>x.type==='image').length}} 张照片</span><div><el-checkbox v-model="directory" :disabled="busy">附上附件目录</el-checkbox><el-checkbox v-model="packageOriginals" :disabled="busy">打包原始附件（ZIP）</el-checkbox></div></div>
      <div v-if="mode==='edit'" class="archive-editor-layout">
        <div class="archive-paper-stack">
          <div class="archive-edit-note"><span>编辑稿件</span><span>拖动右侧 ⋮⋮ 调序，也可用上移 / 下移</span></div>
          <fieldset class="archive-paper archive-edit-paper" :disabled="busy"><label class="archive-title-label" for="archive-title">档案标题</label><textarea id="archive-title" v-model="draft.title" class="archive-title-input" rows="3" maxlength="200" placeholder="填写档案标题" aria-label="档案标题"></textarea><div class="archive-document-metadata"><p>编制单位：{{draft.metadata?.community}}</p><p>资料范围：{{draft.metadata?.scope_label}}</p><p>统计周期：{{draft.metadata?.period_label}}</p></div>
            <template v-for="(block,index) in draft.blocks" :key="block.id">
              <div class="archive-insert-gap" :class="{'is-drop-target':dropAt===index}" @dragover.prevent="dropAt=index" @drop="dropBlock($event,index)"><button type="button" :aria-label="`在第${index+1}段前插入`" :aria-expanded="insertAt===index" @click="insertAt=insertAt===index?null:index">＋</button><div v-if="insertAt===index" class="archive-insert-menu"><button type="button" @click="insertBlock('paragraph',index)">正文</button><button type="button" @click="insertBlock('heading',index)">小标题</button><button type="button" @click="openPhotos(index)">图片</button></div></div>
              <article class="archive-block" :class="{'is-dragging':dragging===block.id,'archive-heading-block':block.type==='heading'}" :data-block-id="block.id" :data-block-type="block.type" @dragover.prevent="dropAt=index" @drop.stop="dropBlock($event,index)">
                <div class="archive-block-main"><label class="archive-block-label" :for="`input-${block.id}`">{{blockLabel(block)}}<small v-if="block.type==='image'">原图比例 · 不裁切</small></label><textarea v-if="block.type!=='image'" :id="`input-${block.id}`" v-model="block.text" :class="block.type==='heading'?'archive-heading-input':'archive-paragraph-input'" :rows="block.type==='heading'?2:Math.min(12,Math.max(4,(block.text||'').split('\n').length+1))" :maxlength="block.type==='heading'?300:10000" :placeholder="block.type==='heading'?'填写小标题':'填写正文内容'" :aria-label="`第${index+1}段${blockLabel(block)}`"></textarea><template v-else><figure class="archive-edit-figure"><img v-if="photoFor(block)?.available" :src="photoFor(block)?.url" :alt="block.caption||'工作现场照片'" loading="lazy" @error="($event.target as HTMLImageElement).alt='照片读取失败，请检查原始附件'"><div v-else class="archive-missing-photo">照片无法使用：{{photoFor(block)?.unavailable_reason||'原始附件不存在'}}。请恢复来源资料，或返回范围重新生成新稿。</div></figure><div class="archive-caption-edit"><span>图{{imageNumbers[block.id]}}</span><input :id="`input-${block.id}`" v-model="block.caption" maxlength="500" :aria-label="`图${imageNumbers[block.id]}图注`" placeholder="填写图片说明"></div><p class="archive-photo-source">{{photoFor(block)?.event_date}} · {{photoFor(block)?.elevator_label}} · {{photoFor(block)?.event_title}}</p></template></div>
                <div class="archive-block-actions"><button type="button" class="archive-drag-handle" draggable="true" :disabled="busy" :aria-label="`拖动第${index+1}段排序，可使用下方上移下移按钮`" title="拖动此处排序" @dragstart="startDrag($event,block.id)" @dragend="finishDrag">⋮⋮</button><button type="button" :disabled="index===0" :aria-label="`上移第${index+1}段`" @click="moveBlock(index,-1)">↑<span>上移</span></button><button type="button" :disabled="index===draft.blocks.length-1" :aria-label="`下移第${index+1}段`" @click="moveBlock(index,1)">↓<span>下移</span></button><button type="button" class="archive-remove" :aria-label="`移除第${index+1}段`" @click="removeBlock(index)">×<span>移除</span></button></div>
              </article>
            </template>
            <div class="archive-insert-gap archive-final-gap" :class="{'is-drop-target':dropAt===draft.blocks.length}" @dragover.prevent="dropAt=draft.blocks.length" @drop="dropBlock($event,draft.blocks.length)"><button type="button" aria-label="在末尾插入" :aria-expanded="insertAt===draft.blocks.length" @click="insertAt=insertAt===draft.blocks.length?null:draft.blocks.length">＋<span v-if="!draft.blocks.length">添加第一段</span></button><div v-if="insertAt===draft.blocks.length" class="archive-insert-menu"><button type="button" @click="insertBlock('paragraph',draft.blocks.length)">正文</button><button type="button" @click="insertBlock('heading',draft.blocks.length)">小标题</button><button type="button" @click="openPhotos(draft.blocks.length)">图片</button></div></div>
          </fieldset>
          <div v-if="lastDeleted" class="archive-undo" role="status">已从编排稿移除一段。<el-button text :disabled="busy" @click="undoDelete">撤销本次移除</el-button></div>
        </div>
        <aside class="archive-editor-rail"><div class="archive-rail-note"><b>编排提示</b><p>标题、正文和小标题都可直接修改。点击段落间的加号，插入文字或工作照片。</p><p>照片只取自本次范围内的原始工作记录。移出编排稿后，仍可从图片库重新插入。</p></div><button type="button" class="archive-photo-library-link" :disabled="busy" @click="openPhotos(draft.blocks.length)"><span>▧ 图片库</span><b>{{draft.images.length}} 张</b><small>{{unusedPhotos}} 张可插入 · 点击添加至稿末</small></button><p class="hint">导出前会保存当前稿。多人修改发生冲突时，系统会保留当前编辑内容，不会覆盖另一份已保存稿。</p></aside>
      </div>

      <div v-else class="archive-preview-wrap"><p class="archive-preview-caption">内容顺序预览 · 无额外封面 · 非实际分页</p><article class="archive-paper archive-preview-paper"><h1>{{draft.title}}</h1><div class="archive-document-metadata"><p>编制单位：{{draft.metadata?.community}}</p><p>资料范围：{{draft.metadata?.scope_label}}</p><p>统计周期：{{draft.metadata?.period_label}}</p></div><template v-for="block in draft.blocks" :key="block.id"><h2 v-if="block.type==='heading'">{{block.text}}</h2><p v-else-if="block.type==='paragraph'" class="archive-preview-paragraph">{{block.text}}</p><figure v-else class="archive-preview-figure"><img v-if="photoFor(block)?.available" :src="photoFor(block)?.url" :alt="block.caption||'工作现场照片'"><div v-else class="archive-missing-photo">照片无法使用：{{photoFor(block)?.unavailable_reason||'原始附件不存在'}}</div><figcaption>图{{imageNumbers[block.id]}}<template v-if="block.caption">　{{block.caption}}</template></figcaption></figure></template><section v-if="directory&&previewDirectory.length" class="archive-preview-directory"><h2>附件目录</h2><div class="archive-directory-table"><table><thead><tr><th>编号</th><th>资料名称 / 类别</th><th>来源</th></tr></thead><tbody><tr v-for="item in previewDirectory" :key="item.id"><td>{{item.reference}}</td><td>{{item.display_name||item.original_name}}<br><small>{{item.category}}{{item.available?'':' · 原件不可用'}}</small></td><td>{{item.event_date}}<br>{{item.elevator_label}}<br>{{item.event_title}}</td></tr></tbody></table></div></section></article></div>
      <span class="archive-sr-only" role="status" aria-live="polite">{{announcement}}</span>
    </template>

    <el-dialog :model-value="pickerAt!==null" title="插入工作照片" width="min(900px, 94vw)" class="archive-photo-dialog" :close-on-click-modal="false" @update:model-value="value=>{if(!value)pickerAt=null}"><p class="hint">选择一张照片插入当前位置。每张照片在一份编排稿中只出现一次。</p><el-input v-model="pickerSearch" clearable placeholder="按楼栋、日期或工作事项查找" aria-label="查找工作照片"/><div v-if="!draft?.images.length" class="empty">本次范围没有工作照片。请先在工作记录中上传照片，再生成新稿。</div><div v-else-if="!photos.length" class="empty">没有匹配的工作照片，请调整查找内容。</div><div v-else class="archive-photo-grid"><button v-for="photo in photos" :key="photo.id" type="button" :disabled="!photo.available||photoUsed(photo.id)" :class="{'is-used':photoUsed(photo.id)}" :aria-label="`插入照片：${photo.event_title} ${photo.category}`" @click="insertPhoto(photo)"><div class="archive-library-image"><img v-if="photo.available" :src="photo.url" :alt="photo.category||photo.event_title" loading="lazy"><span v-else>{{photo.unavailable_reason||'原图不可用'}}</span><b v-if="photoUsed(photo.id)">已在正文</b></div><strong>{{photo.category}}</strong><span>{{photo.event_date}} · {{photo.elevator_label}}</span><small>{{photo.event_title}}</small></button></div><template #footer><el-button @click="pickerAt=null">关闭图片库</el-button></template></el-dialog>
  </section>
</template>

<style scoped>
.archive-selection-summary{display:grid;gap:8px;border-top:1px solid #e2e7ee;margin-top:25px;padding-top:20px;font-size:12px;color:#687482}.archive-selection-summary>b{color:#435674;font-weight:600}.archive-selection-summary>small{font-size:11px;line-height:1.9}.archive-document-metadata{font-size:12px;line-height:1.8;color:#687482;margin:20px 0 8px}.archive-document-metadata>p{margin:5px 0}.archive-preview-paper .archive-document-metadata{font-size:14px;color:#333;margin:0 0 25px}.archive-select-layout{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:38px;align-items:start}.archive-select-layout .export-settings{padding:4px 34px 28px}.archive-create-actions{padding-top:24px}.archive-create-actions>.el-button.is-text{margin:2px 6px 0 0;padding-left:0}.archive-create-actions>.hint{margin:12px 0}.archive-draft-rail{min-width:0;padding:12px 0}.archive-draft-rail h2{font-size:17px}.archive-draft-rail>.hint{margin:0 0 20px}.archive-draft-list{display:grid;gap:10px;max-height:650px;overflow:auto}.archive-draft-list>button{border:1px solid #e2e7ee;background:#fff;border-radius:7px;text-align:left;padding:17px 18px;display:grid;gap:8px;color:#28313b;width:100%}.archive-draft-list>button:hover{border-color:#a1aeef}.archive-draft-list b{font-weight:550;font-size:14px;line-height:1.6;overflow-wrap:anywhere}.archive-draft-list span,.archive-draft-list small{font-size:11px;color:#687482}.archive-no-drafts{padding:25px 0;color:#8794a2;font-size:13px}.archive-rail-note{border-top:1px solid #e2e7ee;padding:22px 0;margin-top:25px;font-size:12px;line-height:1.9;color:#687482}.archive-rail-note>b{font-size:13px;font-weight:600;color:#435674}.archive-rail-note p{margin:9px 0 0}.archive-error,.archive-list-error{border:1px solid #e8c5bc;background:#fff5f2;color:#8d4138;border-radius:7px;padding:13px 17px;font-size:13px;line-height:1.7;margin-bottom:20px}.archive-error{display:flex;align-items:center;justify-content:space-between;gap:15px}.archive-error .el-button{flex-shrink:0}.archive-toolbar{position:sticky;top:0;z-index:15;background:#f8f9fbf5;border-bottom:1px solid #e2e7ee;padding:15px 0;display:flex;align-items:center;justify-content:space-between;gap:14px}.archive-toolbar-start,.archive-toolbar-actions{display:flex;align-items:center;gap:10px}.archive-toolbar .el-button+.el-button{margin-left:0}.archive-save-state{font-size:11px;color:#687482;display:flex;align-items:center;gap:7px}.archive-save-state i{width:5px;height:5px;border-radius:100%;background:#3b806b;display:block;flex-shrink:0}.archive-save-state.unsaved i{background:#a77a35}.archive-save-state.unsaved{color:#956d30}.archive-document-options{display:flex;align-items:center;justify-content:space-between;gap:15px;color:#687482;font-size:12px;padding:14px 0 20px}.archive-document-options>div{display:flex;gap:20px}.archive-document-options .el-checkbox{margin-right:0}.archive-document-options :deep(.el-checkbox__label){font-size:12px}.archive-editor-layout{display:grid;grid-template-columns:minmax(0,780px) minmax(170px,1fr);gap:30px;align-items:start}.archive-paper-stack{min-width:0}.archive-edit-note{display:flex;justify-content:space-between;gap:12px;margin-bottom:12px;font-size:11px;color:#8794a2}.archive-edit-note>span:first-child{font-weight:600;color:#687482}.archive-paper{margin:0;background:white;border:1px solid #e2e7ee;box-shadow:0 9px 35px #28313b04;min-width:0}.archive-edit-paper{padding:32px 30px 20px}.archive-title-label{color:#687482;font-size:11px;display:block;margin-bottom:12px}.archive-title-input{display:block;width:100%;resize:vertical;min-height:110px;border:1px solid #dce2eb;border-radius:5px;padding:18px 22px;color:#202831;font-family:"方正小标宋简体","Songti SC","SimSun",serif;font-size:25px;line-height:1.6;text-align:center;background:#fcfcfd;font-weight:600}.archive-title-input:focus{outline:2px solid #a1aeef;outline-offset:2px;background:#fff}.archive-insert-gap{position:relative;min-height:43px;display:flex;align-items:center;justify-content:center;z-index:2}.archive-insert-gap:before,.archive-insert-gap:after{content:"";height:1px;flex:1;background:#edf0f5}.archive-insert-gap>button{border:1px solid #dce3ee;border-radius:50%;width:25px;height:25px;margin:0 10px;padding:0;background:#fff;color:#7485a3;font-size:18px;line-height:22px}.archive-insert-gap>button:hover,.archive-insert-gap>button[aria-expanded=true]{background:#eff2ff;border-color:#a1aeef;color:#435ddd}.archive-insert-gap.is-drop-target:before,.archive-insert-gap.is-drop-target:after{background:#435ddd;height:3px}.archive-insert-menu{display:flex;position:absolute;top:34px;left:50%;transform:translateX(-50%);background:white;border:1px solid #dce3ee;border-radius:6px;box-shadow:0 6px 25px #28313b1a;z-index:8;padding:5px;gap:3px}.archive-insert-menu>button{white-space:nowrap;border:0;background:#fff;color:#435674;border-radius:3px;padding:10px 15px;font-size:12px}.archive-insert-menu>button:hover{background:#eff2ff;color:#435ddd}.archive-final-gap{margin-bottom:2px}.archive-final-gap>button:has(span){width:auto;border-radius:16px;padding:0 12px;font-size:13px}.archive-final-gap>button>span{font-size:11px;margin-left:6px}.archive-block{display:grid;grid-template-columns:minmax(0,1fr) 48px;border:1px solid #e1e6ee;border-radius:5px;background:#fff;position:relative;transition:border-color .15s}.archive-block:focus-within{border-color:#a1aeef}.archive-block.is-dragging{opacity:.45}.archive-block-main{padding:17px 20px 19px;min-width:0}.archive-block-label{font-size:11px;color:#8794a2;display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}.archive-block-label>small{font-size:10px}.archive-block textarea{display:block;width:100%;resize:vertical;border:0;border-radius:3px;color:#28313b;background:white;padding:3px 1px;font-family:"FangSong","仿宋","Songti SC",serif;line-height:1.9;outline-offset:5px}.archive-block textarea:focus{outline:1px solid #b8c2ed}.archive-paragraph-input{font-size:17px;min-height:130px}.archive-heading-input{font-family:"SimHei","黑体","Microsoft YaHei",sans-serif!important;font-size:18px;font-weight:600;min-height:65px}.archive-block-actions{border-left:1px solid #edf0f5;display:flex;flex-direction:column;align-items:stretch;background:#fcfcfe;border-radius:0 5px 5px 0}.archive-block-actions>button{border:0;background:none;min-height:41px;padding:6px 1px;color:#687b92;font-size:16px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px}.archive-block-actions>button>span{font-size:10px}.archive-block-actions>button:hover:not(:disabled){color:#435ddd;background:#eff2ff}.archive-block-actions>button:disabled{color:#c9d0db;cursor:default}.archive-block-actions>button.archive-drag-handle{font-size:19px;letter-spacing:-4px;padding-right:4px;cursor:grab;min-height:38px}.archive-block-actions>button.archive-remove{color:#b35c52;margin-top:auto}.archive-block-actions>button.archive-remove:hover{background:#fff2ef;color:#9e4136}.archive-edit-figure{margin:0;background:#f8f9fb;text-align:center;min-height:100px}.archive-edit-figure>img{display:block;width:100%;max-height:410px;object-fit:contain}.archive-caption-edit{display:flex;align-items:baseline;gap:10px;margin-top:15px;font-family:"FangSong","仿宋","Songti SC",serif;font-size:15px}.archive-caption-edit>span{white-space:nowrap}.archive-caption-edit>input{border:0;border-bottom:1px solid #e2e7ee;padding:5px 0;min-width:0;flex:1;background:transparent;color:#28313b;font:inherit}.archive-caption-edit>input:focus{outline:1px solid #b8c2ed;outline-offset:3px}.archive-photo-source{font-size:10px;color:#8794a2;line-height:1.8;margin:12px 0 0}.archive-missing-photo{padding:22px;font:13px/1.8 "Microsoft YaHei",sans-serif;color:#a15345;background:#fff5f2}.archive-editor-rail{position:sticky;top:90px;min-width:0}.archive-editor-rail>.archive-rail-note{margin:0;padding-top:4px;border:0}.archive-editor-rail>.hint{line-height:1.9;font-size:11px;margin-top:20px}.archive-photo-library-link{display:grid;grid-template-columns:1fr auto;text-align:left;gap:8px;border:1px solid #dce3ee;background:#f1f4fc;border-radius:6px;padding:17px;color:#435674;width:100%;font-size:13px}.archive-photo-library-link>small{grid-column:1/-1;font-size:10px;color:#73839a}.archive-photo-library-link>b{font-weight:500}.archive-undo{font-size:12px;color:#687482;display:flex;align-items:center;justify-content:center;margin:12px 0}.archive-preview-wrap{max-width:780px;margin:0 auto}.archive-preview-caption{text-align:center;color:#8794a2;font-size:11px;margin:0 0 14px}.archive-preview-paper{padding:68px 62px 65px;font-family:"FangSong","仿宋","Songti SC",serif;color:#111;overflow-wrap:anywhere;line-height:1.9}.archive-preview-paper>h1{font-family:"方正小标宋简体","Songti SC","SimSun",serif;font-size:27px;line-height:1.65;font-weight:600;text-align:center;margin:0 0 35px;white-space:pre-wrap}.archive-preview-paper h2{font-family:"SimHei","黑体","Microsoft YaHei",sans-serif;font-size:19px;font-weight:600;line-height:1.8;margin:25px 0 14px;white-space:pre-wrap}.archive-preview-paragraph{font-size:20px;margin:14px 0;white-space:pre-wrap;text-indent:2em;line-height:1.9}.archive-preview-figure{margin:25px auto;text-align:center;break-inside:avoid}.archive-preview-figure>img{display:block;max-width:100%;max-height:410px;width:auto;height:auto;margin:0 auto}.archive-preview-figure figcaption{font-size:17px;margin-top:10px;line-height:1.7;white-space:pre-wrap}.archive-directory-table{overflow-x:auto}.archive-preview-directory table{width:100%;border-collapse:collapse;font-size:13px;line-height:1.8}.archive-preview-directory th,.archive-preview-directory td{border:1px solid #b5b5b5;padding:9px 10px;text-align:left;font-weight:400;vertical-align:top}.archive-preview-directory th{font-family:"SimHei","黑体",sans-serif}.archive-preview-directory td:first-child{min-width:65px}.archive-preview-directory td:nth-child(2){word-break:break-all}.archive-preview-directory small{font-size:12px}.archive-photo-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px;margin-top:22px;max-height:58vh;overflow:auto;padding:2px}.archive-photo-grid>button{text-align:left;display:grid;gap:7px;padding:0 0 12px;border:1px solid #e2e7ee;border-radius:5px;background:white;overflow:hidden;color:#28313b;min-width:0}.archive-photo-grid>button:hover:not(:disabled){border-color:#435ddd}.archive-photo-grid>button:disabled{cursor:default}.archive-photo-grid>button.is-used{background:#f8f9fb;color:#8794a2}.archive-library-image{height:155px;background:#f1f4f8;position:relative;display:grid;place-items:center}.archive-library-image img{width:100%;height:155px;object-fit:contain}.archive-library-image>span{font-size:11px;padding:15px;color:#a15345}.archive-library-image>b{position:absolute;right:7px;top:7px;border-radius:3px;background:#28313bcc;color:white;padding:4px 7px;font-size:10px;font-weight:400}.archive-photo-grid strong,.archive-photo-grid>button>span,.archive-photo-grid small{padding:0 12px;overflow-wrap:anywhere}.archive-photo-grid strong{font-size:12px;font-weight:550;margin-top:4px}.archive-photo-grid>button>span,.archive-photo-grid small{font-size:10px;line-height:1.7;color:#687482}.archive-sr-only{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap}.archive-workspace button:focus-visible{outline:2px solid #435ddd;outline-offset:3px}
@media(max-width:1100px){.archive-editor-layout{grid-template-columns:minmax(0,780px);justify-content:center}.archive-editor-rail{position:static;display:flex;gap:25px;align-items:start}.archive-editor-rail>.archive-rail-note{flex:1}.archive-editor-rail>.archive-photo-library-link{width:240px;flex-shrink:0}.archive-editor-rail>.hint{display:none}.archive-select-layout{grid-template-columns:minmax(0,1fr) 250px;gap:24px}.archive-toolbar{flex-wrap:wrap}.archive-toolbar-start{flex:1}.archive-save-state{line-height:1.7}}
@media(max-width:760px){.archive-select-layout{grid-template-columns:1fr;gap:18px}.archive-select-layout .export-settings{padding:0 20px 22px}.archive-draft-rail{padding:0}.archive-draft-list{max-height:380px}.archive-draft-rail>.archive-rail-note{display:none}.archive-toolbar{padding:11px 0;gap:10px;top:0}.archive-toolbar-start{flex-basis:100%;justify-content:space-between}.archive-toolbar-start>.el-button{padding:8px 10px;font-size:12px}.archive-toolbar-actions{width:100%;gap:7px}.archive-toolbar-actions>.el-button{flex:1;font-size:12px;padding:9px 8px}.archive-save-state{font-size:10px;max-width:58%;text-align:right}.archive-document-options{align-items:start;flex-direction:column;gap:6px;padding:12px 0 16px;font-size:11px}.archive-document-options>div{gap:14px;flex-wrap:wrap}.archive-document-options :deep(.el-checkbox__label){font-size:11px}.archive-editor-layout{gap:20px}.archive-edit-note{font-size:10px;line-height:1.6;align-items:center}.archive-edit-note>span:last-child{max-width:72%;text-align:right}.archive-edit-paper{padding:20px 12px 14px}.archive-title-input{padding:13px 11px;font-size:22px;min-height:120px}.archive-title-label{font-size:10px}.archive-block{grid-template-columns:minmax(0,1fr) 38px}.archive-block-main{padding:13px 12px 14px}.archive-block-label{font-size:10px;margin-bottom:9px;gap:5px}.archive-block-label>small{font-size:9px}.archive-block-actions>button{min-height:44px;font-size:15px}.archive-block-actions>button>span{font-size:9px}.archive-paragraph-input{font-size:16px;line-height:1.9!important;min-height:150px}.archive-heading-input{font-size:17px;min-height:70px}.archive-edit-figure>img{max-height:300px}.archive-caption-edit{font-size:14px;gap:6px;margin-top:10px}.archive-photo-source{font-size:9px}.archive-insert-gap{min-height:39px}.archive-insert-menu>button{min-height:42px;padding:9px 15px}.archive-insert-menu{top:31px}.archive-editor-rail{display:block}.archive-editor-rail>.archive-rail-note{display:none}.archive-editor-rail>.archive-photo-library-link{width:100%}.archive-preview-paper{padding:32px 21px 40px}.archive-preview-paper>h1{font-size:23px;margin-bottom:26px}.archive-preview-paper h2{font-size:17px}.archive-preview-paragraph{font-size:17px;line-height:1.95}.archive-preview-figure figcaption{font-size:15px}.archive-preview-figure>img{max-height:330px}.archive-preview-caption{font-size:10px}.archive-preview-directory td,.archive-preview-directory th{padding:6px}.archive-preview-directory table{font-size:11px}.archive-preview-directory small{font-size:10px}.archive-error{align-items:start;flex-direction:column;gap:3px}.archive-undo{font-size:11px;flex-wrap:wrap}.archive-photo-grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:11px;max-height:55vh}.archive-library-image,.archive-library-image img{height:130px}}
@media(prefers-reduced-motion:reduce){.archive-block{transition:none}}
</style>
