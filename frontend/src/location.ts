const numberPatterns = {
  building: /^([0-9]+)\s*(?:栋|号楼|楼)?$/,
  unit: /^([0-9]+)\s*(?:单元口|单元|口)?$/,
  elevator: /^([0-9]+)\s*(?:号电梯|号梯|号|梯)?$/,
}

export function locationNumber(kind: keyof typeof numberPatterns, name = '') {
  const number = name.trim().match(numberPatterns[kind])?.[1]
  return number?.replace(/^0+(?=\d)/, '') ?? ''
}

type ElevatorPlace = { building_name: string; unit_name: string; elevator_name?: string; name: string }

export function placeParts(item: ElevatorPlace) {
  const name = item.elevator_name || item.name
  const building = locationNumber('building', item.building_name)
  const unit = locationNumber('unit', item.unit_name)
  const elevator = locationNumber('elevator', name)
  return [building ? `${building}栋` : item.building_name, unit ? `${unit}口` : item.unit_name, elevator ? `${elevator}号电梯` : name]
}

export function place(item: ElevatorPlace) {
  return placeParts(item).join('')
}

export function matchingElevatorOptions(options: Array<{ item: ElevatorPlace & { id: number }; label: string }>, query: string) {
  const normalized = query.normalize('NFKC').trim().toLowerCase()
  const archiveId = normalized.match(/^档案\s*([0-9]+)(?:\s*·[\s\S]*)?$/)?.[1].replace(/^0+(?=\d)/, '')
  if (archiveId) return options.filter(({ item }) => String(item.id) === archiveId)
  const terms = normalized.split(/\s+/)
  return options.filter(({ item, label }) => {
    const text = `${label} ${item.building_name}${item.unit_name}${item.name}`.normalize('NFKC').toLowerCase()
    return terms.every(term => text.includes(term))
  })
}

export function conflictingPlaceLabels(elevators: Array<ElevatorPlace & { id: number }>) {
  const counts = new Map<string, number>()
  const places = elevators.map(item => {
    const label = place(item)
    counts.set(label, (counts.get(label) ?? 0) + 1)
    return { item, label }
  })
  const labels = new Map<number, string>()
  for (const { item, label } of places) {
    if (counts.get(label) === 1) continue
    labels.set(item.id, `${label}（档案 ${item.id} · ${item.building_name} / ${item.unit_name} / ${item.name}）`)
  }
  return labels
}
