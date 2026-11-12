/** Compose location props with per-shot overrides without freezing unchanged set entries. */
export type RoomItem = Record<string, unknown> & { objectId: string }

export function visibleRoomItems(inherited: RoomItem[], own: RoomItem[], removed: string[] = []): RoomItem[] {
  const rows = new Map(inherited.filter(row => !removed.includes(row.objectId)).map(row => [row.objectId, row]))
  for (const row of own) rows.set(row.objectId, row)
  return [...rows.values()]
}

export function roomItemOverrides(inherited: RoomItem[], rows: RoomItem[]) {
  const base = new Map(inherited.map(row => [row.objectId, row]))
  const ids = new Set(rows.map(row => row.objectId))
  return { objects: rows.filter(row => JSON.stringify(row) !== JSON.stringify(base.get(row.objectId))),
    removedSetObjects: inherited.filter(row => !ids.has(row.objectId)).map(row => row.objectId) }
}
