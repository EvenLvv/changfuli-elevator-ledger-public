<script setup lang="ts">
import { computed, ref, watch } from 'vue'

type Photo = {id:string; original_name:string; category:string}
type RecordOption = {id:number; elevator_id:number; title:string; type:string; occurred_on:string}
type PhotoRecord = RecordOption & {location_label:string; photos:Photo[]}
const props = defineProps<{
  elevators: {item:{id:number}; label:string}[]
  api:(path:string, options?:any)=>Promise<any>
}>()

const elevatorId = ref<number>()
const recordId = ref<number>()
const options = ref<RecordOption[]>([])
const records = ref<PhotoRecord[]>([])
const loading = ref(false), loadingOptions = ref(false), hasMore = ref(false)
const error = ref(''), optionsError = ref('')
const failedImages = ref(new Set<string>())
const selected = ref<{photo:Photo; record:PhotoRecord}>()
const elevatorLabels = computed(() => new Map(props.elevators.map(({item,label})=>[item.id,label])))
let recordsRequest=0, optionsRequest=0

const imageUrl = (photo:Photo) => `/api/attachments/${photo.id}`
const baseParams = () => new URLSearchParams(elevatorId.value?{elevator_id:String(elevatorId.value)}:{})
const recordLabel = (record:RecordOption) => `${record.occurred_on} · ${record.title} · ${elevatorLabels.value.get(record.elevator_id)||''} · 记录 ${record.id}`

async function loadOptions() {
  const request=++optionsRequest
  options.value=[]; optionsError.value=''; loadingOptions.value=true
  try {
    const result=await props.api(`/photo-library/records?${baseParams()}`)
    if(request===optionsRequest) options.value=result
  } catch(e:any) {
    if(request===optionsRequest) optionsError.value=e.message||'无法读取工作记录选项'
  } finally {
    if(request===optionsRequest) loadingOptions.value=false
  }
}

async function loadRecords(append=false) {
  const request=++recordsRequest
  if(!append) {
    records.value=[]; failedImages.value.clear(); hasMore.value=false
  }
  const params=baseParams()
  if(recordId.value) params.set('event_id',String(recordId.value))
  params.set('offset',String(records.value.length))
  loading.value=true; error.value=''
  try {
    const result=await props.api(`/photo-library?${params}`)
    if(request===recordsRequest) {
      records.value.push(...result.records)
      hasMore.value=result.has_more
    }
  } catch(e:any) {
    if(request===recordsRequest) error.value=e.message||'无法读取照片'
  } finally {
    if(request===recordsRequest) loading.value=false
  }
}

watch(elevatorId, ()=>{recordId.value=undefined;void loadOptions()},{immediate:true})
watch([elevatorId,recordId], ()=>loadRecords(),{immediate:true})
</script>

<template>
  <section class="photo-library">
    <div class="page-heading"><div><h1>图片库</h1><p>按电梯或工作记录查看现场照片及其他图片附件。</p></div></div>
    <div class="panel library-filters" aria-label="筛选照片">
      <div>
        <label for="photo-library-elevator">电梯</label>
        <el-select id="photo-library-elevator" v-model="elevatorId" clearable filterable placeholder="全部电梯" aria-label="按电梯筛选照片">
          <el-option v-for="{item,label} in elevators" :key="item.id" :value="item.id" :label="label"/>
        </el-select>
      </div>
      <div>
        <label for="photo-library-record">工作记录</label>
        <el-select id="photo-library-record" v-model="recordId" clearable filterable :loading="loadingOptions" placeholder="全部工作记录" aria-label="按工作记录筛选照片">
          <el-option v-for="item in options" :key="item.id" :value="item.id" :label="recordLabel(item)"/>
        </el-select>
      </div>
      <div v-if="optionsError" class="library-filter-error" role="alert">{{optionsError}} <el-button text @click="loadOptions">重试读取筛选项</el-button></div>
    </div>
    <div v-if="loading&&!records.length" class="panel empty" role="status">正在读取照片…</div>
    <div v-else-if="!records.length&&!error" class="panel empty">所选范围内没有可浏览的照片。</div>
    <section v-for="record in records" :key="record.id" class="library-record panel" :aria-label="record.title">
      <div class="library-record-heading">
        <div><p><time>{{record.occurred_on}}</time><span>{{record.type}}</span></p><h2>{{record.title}}</h2></div>
        <router-link :to="{path:`/elevators/${record.elevator_id}`,query:{event_id:record.id}}" class="library-record-link">{{record.location_label}} · 查看记录</router-link>
      </div>
      <ul class="library-grid">
        <li v-for="photo in record.photos" :key="photo.id">
          <button type="button" class="library-photo" :disabled="failedImages.has(photo.id)" :aria-label="`查看原图 ${photo.original_name}`" @click="selected={photo,record}">
            <span class="library-image"><img v-if="!failedImages.has(photo.id)" :src="imageUrl(photo)" :alt="photo.original_name" loading="lazy" @error="failedImages.add(photo.id)"><span v-else>原图暂时无法读取</span></span>
            <span class="library-caption"><b>{{photo.category}}</b><small>{{photo.original_name}}</small></span>
          </button>
        </li>
      </ul>
    </section>
    <div v-if="error" class="panel empty" role="alert">{{error}}<br><el-button @click="loadRecords(!!records.length)">重试读取照片</el-button></div>
    <div v-else-if="hasMore" class="library-more"><el-button :loading="loading" @click="loadRecords(true)">加载更早的工作记录</el-button></div>

    <el-dialog :model-value="!!selected" :title="selected?.photo.category||'查看原图'" width="min(900px, 94vw)" @update:model-value="value=>{if(!value) selected=undefined}">
      <figure v-if="selected" class="library-original">
        <img :src="imageUrl(selected.photo)" :alt="selected.photo.original_name">
        <figcaption><span>{{selected.photo.original_name}} · {{selected.record.title}}</span><a :href="`${imageUrl(selected.photo)}?download=true`">下载原图</a></figcaption>
      </figure>
    </el-dialog>
  </section>
</template>

<style scoped>
.photo-library{min-width:0}
.library-filters{display:grid;grid-template-columns:minmax(140px,1fr) minmax(200px,2fr);gap:14px 20px;padding:16px 20px;margin-bottom:20px}
.library-filters label{display:block;font-size:13px;font-weight:600;margin-bottom:7px}
.library-filters :deep(.el-select){width:100%}
.library-filter-error{grid-column:1/-1;color:var(--muted);font-size:13px}
.library-record{padding:18px 20px;margin-bottom:16px}
.library-record-heading{display:flex;gap:10px 20px;justify-content:space-between;align-items:end;margin-bottom:14px}
.library-record-heading p{color:var(--muted);font-size:12px;display:flex;gap:10px;margin:0}
.library-record-heading h2{font-size:17px;margin:6px 0 0;overflow-wrap:anywhere}
.library-record-link,.library-original a{color:var(--blue);font-size:13px;text-decoration:underline;text-underline-offset:3px}
.library-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,170px),1fr));gap:12px;list-style:none;margin:0;padding:0}
.library-grid li{min-width:0;max-width:270px}
.library-photo{display:block;width:100%;padding:0;overflow:hidden;border:1px solid var(--line);border-radius:6px;background:white;text-align:left;color:var(--ink)}
.library-photo:not(:disabled):hover,.library-photo:focus-visible{border-color:var(--blue)}
.library-image{display:grid;place-content:center;width:100%;aspect-ratio:4/3;background:#f2f5f8;position:relative;color:var(--muted);text-align:center;font-size:12px}
.library-image img{position:absolute;inset:0;width:100%;height:100%;object-fit:contain}
.library-caption{display:grid;gap:3px;padding:9px 10px;overflow-wrap:anywhere}
.library-caption b{font-size:12px}
.library-caption small{font-size:11px;color:var(--muted)}
.library-more{text-align:center;margin:20px 0}
.library-original{margin:0}
.library-original img{display:block;max-width:100%;max-height:65vh;margin:0 auto;object-fit:contain}
.library-original figcaption{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-top:10px;overflow-wrap:anywhere}
.library-original a{flex-shrink:0;padding:10px 0}
@media(max-width:630px){
  .library-filters{grid-template-columns:minmax(0,1fr);padding:14px}
  .library-filters :deep(.el-select__wrapper){min-height:42px}
  .library-record{padding:14px}
  .library-record-heading{flex-direction:column;align-items:start;gap:5px}
  .library-record-link{display:inline-flex;align-items:center;min-height:32px}
  .library-grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
}
</style>
