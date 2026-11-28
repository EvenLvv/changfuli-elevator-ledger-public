const shanghaiDate = new Intl.DateTimeFormat('en-CA', {
  timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit'
})
export function today() {
  const parts = shanghaiDate.formatToParts(new Date())
  const get = (type: Intl.DateTimeFormatPartTypes) => parts.find(part => part.type === type)!.value
  return [get('year'), get('month'), get('day')].join('-')
}
const shanghaiTime = new Intl.DateTimeFormat('zh-CN', {
  timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23'
})
export function displayTimestamp(stamp?: string) {
  if (!stamp) return ''
  const zoned = /(?:Z|[+-]\d{2}:\d{2})$/.test(stamp) ? stamp : stamp + '+08:00'
  return shanghaiTime.format(new Date(zoned))
}
export const isoDay = (date: Date) => date.toISOString().slice(0, 10)

// Calendar arithmetic on date-only values must be independent of the device timezone.
export function calendarDay(day: string, months = 0, days = 0) {
  const result = new Date(day + 'T00:00:00Z')
  result.setUTCMonth(result.getUTCMonth() + months)
  result.setUTCDate(result.getUTCDate() + days)
  return result
}

export const presets = ['全部', '今天', '近7天', '本月', '本季度'] as const
export type Period = typeof presets[number]

export function periodRange(period: Period, current: string) {
  if (period === '全部') return ['1900-01-01', '9999-12-31']
  const first = current.slice(0, 7) + '-01'
  if (period === '今天') return [current, current]
  if (period === '近7天') return [isoDay(calendarDay(current, 0, -6)), current]
  const quarterOffset = (Number(current.slice(5, 7)) - 1) % 3
  const start = period === '本月' ? first : isoDay(calendarDay(first, -quarterOffset))
  return [start, isoDay(calendarDay(start, period === '本月' ? 1 : 3, -1))]
}
