<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import type { SelectInstance } from 'element-plus'
import { calendarDay, isoDay, periodRange, presets, today, type Period } from '../calendar'
import { matchingElevatorOptions } from '../location'

type Entry = {
  id: number; timestamp: string; kind: string; title: string; summary: string; tags: string[]
  tone: string; elevator_id: number | null; event_id: number | null
}
type Result = { items: Entry[]; dates: string[]; total: number }
const props = defineProps<{
  api: (path: string) => Promise<Result>
  options: Parameters<typeof matchingElevatorOptions>[0]
  elevatorLabels: Map<number, string>
}>()
const router = useRouter()
const period = ref<Period | '单日'>('全部')
const current = ref(today())
const range = ref(periodRange('全部', current.value))
const month = ref(current.value.slice(0, 7) + '-01')
const elevator = ref<number>(), category = ref(''), search = ref('')
const select = ref<SelectInstance>()
const options = computed(() => matchingElevatorOptions(props.options, search.value))
const weekdays = '日一二三四五六'
const workTypes = ['日常维保','故障','维修','配件更换','检验/检查','资料补充','其他']
const systemTypes = ['系统操作','电梯档案','楼栋与单元','附件','导入','导出','备份','系统设置','恢复','工作文稿']
const result = ref<Result>({ items: [], dates: [], total: 0 })
const pins = computed(() => new Set(result.value.dates))
const error = ref(''), pending = ref(false), retry = ref(0), visible = ref(60)
const scroller = ref<HTMLElement>()
const cells = computed(() => {
  const offset = calendarDay(month.value).getUTCDay()
  const last = calendarDay(month.value, 1, -1).getUTCDate()
  return Array.from({ length: Math.ceil((last + offset) / 7) * 7 }, (_, i) =>
    isoDay(calendarDay(month.value, 0, i - offset)))
})
function shiftMonth(by: number) { month.value = isoDay(calendarDay(month.value, by)) }
function choosePeriod(value: Period) {
  current.value = today()
  period.value = value
  range.value = periodRange(value, current.value)
  month.value = current.value.slice(0, 7) + '-01'
}
function chooseDay(day: string) {
  period.value = '单日'
  range.value = [day, day]
  month.value = day.slice(0, 7) + '-01'
}
function dateLabel(day: string, year = false) {
  return (year ? day.slice(0, 4) + '年' : '') + Number(day.slice(5, 7)) + '月' + Number(day.slice(8)) + '日'
}
const groups = computed(() => {
  const days = new Map<string, Entry[]>()
  for (const item of result.value.items.slice(0, visible.value)) {
    const day = item.timestamp.slice(0, 10)
    if (!days.has(day)) days.set(day, [])
    days.get(day)!.push(item)
  }
  return days
})
watch([range, month, elevator, category, retry], async (_, __, onCleanup) => {
  let active = true
  onCleanup(() => { active = false })
  const [start, end] = range.value
  const params = new URLSearchParams({ start, end, month: month.value })
  if (elevator.value) params.set('elevator_id', String(elevator.value))
  if (category.value) params.set('type', category.value)
  pending.value = true
  error.value = ''
  try {
    const data = await props.api('/timeline?' + params)
    if (active) {
      result.value = data
      visible.value = 60
      scroller.value?.scrollTo(0, 0)
    }
  } catch (e) {
    if (active) {
      error.value = e instanceof Error ? e.message : '无法读取工作记录'
      result.value = { items: [], dates: [], total: 0 }
    }
  } finally {
    if (active) pending.value = false
  }
}, { immediate: true })
</script>

<template>
  <section class="operations">
    <div class="page-heading">
      <div><div class="eyebrow">操作留痕 · 按日分隔</div><h1>工作记录</h1>
        <p>每一次操作都会记入时间轴，默认展示全部历史记录，最新的记录在最上方。可用日历查看某一天，或切换全部、今天、近7天、本月、本季度。</p>
      </div>
      <el-button type="primary" size="large" @click="router.push('/events/new')">＋ 新增工作记录</el-button>
    </div>
    <div class="operation-workspace">
      <section class="panel feed">
        <header><h2>操作时间轴</h2><small>{{period}} · {{pending ? '读取中…' : result.total+' 条 · 倒序'}}</small></header>
        <div ref="scroller" class="entries" :aria-busy="pending">
          <p v-if="error" class="empty">{{error}} <button @click="retry++">重试</button></p>
          <p v-else-if="!pending && !result.total" class="empty">所选日期和筛选条件下暂无操作。</p>
          <template v-for="[day, items] in groups" :key="day">
            <div class="date-rule"><strong>{{dateLabel(day, true)}}</strong> 星期{{weekdays[calendarDay(day).getUTCDay()]}}</div>
            <div v-for="item in items" :key="item.id" class="operation" :class="item.tone">
              <time :datetime="item.timestamp">{{item.timestamp.slice(11,16)}}</time><div class="axis"><i/></div>
              <component :is="item.event_id ? 'button' : 'article'" class="operation-card"
                @click="item.event_id && router.push('/elevators/'+item.elevator_id+'?event_id='+item.event_id)">
                <span class="kind">{{item.kind}}</span><h3>{{item.title}}</h3><p v-if="item.summary">{{item.summary}}</p>
                <div class="tags"><span v-for="tag in item.tags" :key="tag" :class="{done:tag==='已完成'}">{{tag}}</span></div>
              </component>
            </div>
          </template>
          <el-button v-if="visible < result.total" class="full" @click="visible+=60">加载更多操作</el-button>
        </div>
      </section>
      <aside class="panel calendar">
        <header><h2>{{month.slice(0,4)}}年{{Number(month.slice(5,7))}}月</h2><div>
          <button aria-label="上个月" @click="shiftMonth(-1)">‹</button><button aria-label="下个月" @click="shiftMonth(1)">›</button>
        </div></header>
        <div class="periods"><button v-for="p in presets" :key="p" :aria-pressed="period===p" @click="choosePeriod(p)">{{p}}</button></div>
        <p class="range-note" aria-live="polite">已选 <template v-if="period==='全部'">全部日期</template><template v-else>{{dateLabel(range[0])}}<template v-if="range[0]!==range[1]"> — {{dateLabel(range[1])}}</template></template>，{{pending?'读取中…':'共 '+result.total+' 条操作'}}</p>
        <div class="week"><span v-for="day in weekdays" :key="day">{{day}}</span></div>
        <div class="days"><button v-for="day in cells" :key="day" :aria-label="dateLabel(day,true)+(pins.has(day)?'，有操作记录':'')"
          :class="{muted:day.slice(0,7)!==month.slice(0,7), selected:period!=='全部' && day>=range[0] && day<=range[1], end:period!=='全部' && day===range[1], today:day===current}"
          @click="chooseDay(day)">{{Number(day.slice(8))}}<i v-if="pins.has(day)" class="pin"/></button></div>
        <small class="legend">当天有操作记录</small>
        <el-form label-position="top" class="timeline-filters">
          <el-form-item label="电梯"><el-select ref="select" v-model="elevator" clearable filterable placeholder="全部电梯"
            :class="{'elevator-select-conflict':elevatorLabels.has(elevator!)}" :filter-method="q=>search=q"
            @visible-change="open=>{if (!open) search=''}" @keydown.esc.capture.stop.prevent="select?.blur()">
            <el-option v-for="{item,label} in options" :key="item.id" :value="item.id" :label="label"
              :class="{'elevator-option-conflict':elevatorLabels.has(item.id)}"/>
          </el-select></el-form-item>
          <label>类型<select v-model="category"><option value="">全部类型</option>
            <optgroup label="工作类型"><option v-for="t in workTypes" :key="t">{{t}}</option></optgroup>
            <optgroup label="系统操作"><option v-for="t in systemTypes" :key="t">{{t}}</option></optgroup></select></label>
        </el-form>
      </aside>
    </div>
  </section>
</template>

<style scoped>
.operations,.feed,.operation-workspace{min-height:0;min-width:0}
.operations,.feed{display:flex;flex-direction:column}
.operations{flex:1}
.operations .page-heading{align-items:flex-start;margin-bottom:14px}
.operations h1{font-size:32px;margin:0 0 5px}
.operations .eyebrow{margin-bottom:8px}
.operation-workspace{flex:1;display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:22px}
.operation-workspace>.panel{margin:0}
.feed{padding:20px 8px 8px 32px}
header{display:flex;align-items:center;justify-content:space-between}
.feed header{padding-right:20px}
header h2{margin:0}
.entries{overflow:auto;padding-right:20px}
small,.range-note,.operation time,.timeline-filters label{color:var(--muted);font-size:12px}
.date-rule{display:flex;align-items:center;gap:14px;font-size:12px;color:#8190a3;margin:20px 0 10px}
.date-rule strong{font-size:13px;color:var(--ink)}
.date-rule::before,.date-rule::after{content:'';height:1px;background:var(--line);flex:1}
.date-rule::before{flex:0 0 8px}
.operation{display:grid;grid-template-columns:54px 20px minmax(0,1fr);gap:8px;padding-bottom:12px;--tone:var(--blue)}
.operation.fault{--tone:#b35c52}.operation.sys{--tone:#687b91}.operation.ok{--tone:#39836c}
.operation time{text-align:right;margin-top:14px;font-variant-numeric:tabular-nums}
.axis{position:relative}
.axis::before{content:'';position:absolute;left:9px;top:0;bottom:-12px;border-left:1px solid var(--line)}
.operation:has(+.date-rule) .axis::before,.operation:last-child .axis::before{bottom:calc(100% - 22px)}
.date-rule+.operation .axis::before{top:22px}
.axis i{position:absolute;left:3px;top:16px;border:2px solid var(--tone);background:white;border-radius:50%;width:13px;height:13px}
.operation-card{border:1px solid var(--line);padding:12px 16px;text-align:left;background:white;border-radius:10px;color:var(--ink);overflow-wrap:anywhere;min-width:0}
button.operation-card:hover{border-color:#a1aeef}
.kind{font-size:11px;color:var(--tone);font-weight:650;letter-spacing:.06em}
.operation-card h3{font-size:15px;margin:4px 0 6px}.operation-card p{font-size:12px;color:#66798b;margin:0}
.tags{display:flex;gap:8px;margin-top:8px}.tags span{font-size:11px;border-radius:20px;padding:3px 8px;background:#f4f6f9;color:#5c6d81}.tags .done{color:#39836c;background:#eef6f3}
.calendar{overflow:auto;padding:22px}
.calendar header h2{font-size:16px}.calendar button,.timeline-filters select{border:1px solid var(--line);background:white;color:#52606f;border-radius:6px}
.calendar header button{width:28px;height:28px;margin-left:6px}
.periods{display:flex;gap:6px;flex-wrap:wrap;margin:16px 0}
.periods button{font-size:12px;font-weight:600;border-radius:20px;padding:6px 10px}
.periods button[aria-pressed=true],.days .end{color:white;background:var(--blue)}
.week,.days{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:4px;text-align:center}
.week{font-size:11px;color:#8190a3;margin:15px 0 6px}
.days button{position:relative;border:0;height:38px;font-size:13px}.days .muted{color:#aeb9c7}.days .selected{background:#eef1fb;color:var(--blue)}.days .selected.end{background:var(--blue);color:white}
.days .today{box-shadow:inset 0 0 0 1px var(--blue)}.days button:hover{outline:1px solid var(--blue)}
.pin{position:absolute;bottom:4px;left:calc(50% - 2px);width:4px;height:4px;border-radius:50%;background:var(--blue)}.end .pin{background:white}
.legend{display:block;margin:15px 0;font-size:11px}.legend::before{content:'';display:inline-block;width:6px;height:6px;margin-right:6px;border-radius:50%;background:var(--blue)}
.timeline-filters{border-top:1px solid var(--line);padding-top:14px}
.timeline-filters :deep(.el-form-item){margin-bottom:10px}.timeline-filters :deep(.el-form-item__label){font-size:12px;margin-bottom:6px}
.timeline-filters select{display:block;margin-top:6px;width:100%;height:36px;padding:0 9px;font-size:13px}
@media(max-width:850px){.operation-workspace{display:flex;flex-direction:column}.calendar{order:-1}.feed{padding:18px 12px}.entries{padding:0}.operation{grid-template-columns:33px 13px minmax(0,1fr);gap:4px}.axis::before{left:6px}.axis i{left:0}.calendar,.entries{overflow:visible}}
</style>
