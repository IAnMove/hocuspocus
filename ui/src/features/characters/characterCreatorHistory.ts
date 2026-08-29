export const CHARACTER_CREATOR_HISTORY_LIMIT = 24

export type CharacterCreatorHistoryView = {
  id: string
  hunyuan: 'front' | 'left' | 'back' | 'right'
  label: string
  filename: string
  url: string
  time: number
}

export type CharacterCreatorHistoryEntry = {
  id: string
  name: string
  kind: 'character' | 'object'
  videoName: string
  views: CharacterCreatorHistoryView[]
  hunyuanGlb?: string | null
  workspace: string
  createdAt: string
}

const keyFor = (workspace: string) => `maestro-character-creator-history-v1:${workspace.trim() || 'default'}`

export function characterCreatorHistoryKey(workspace: string): string {
  return keyFor(workspace)
}

export function parseCharacterCreatorHistory(raw: string | null): CharacterCreatorHistoryEntry[] {
  if (!raw) return []
  try {
    const parsed = JSON.parse(raw) as unknown
    if (!Array.isArray(parsed)) return []
    return parsed.flatMap(item => {
      if (!item || typeof item !== 'object') return []
      const entry = item as Partial<CharacterCreatorHistoryEntry>
      if (typeof entry.videoName !== 'string' || !entry.videoName.trim()) return []
      const views = Array.isArray(entry.views) ? entry.views.filter(view => (
        view && typeof view.filename === 'string' && typeof view.id === 'string'
      )) as CharacterCreatorHistoryView[] : []
      return [{
        id: typeof entry.id === 'string' && entry.id.trim() ? entry.id : `sheet-${entry.videoName}`,
        name: typeof entry.name === 'string' && entry.name.trim() ? entry.name.trim() : entry.videoName,
        kind: entry.kind === 'object' ? 'object' : 'character',
        videoName: entry.videoName,
        views,
        hunyuanGlb: typeof entry.hunyuanGlb === 'string' ? entry.hunyuanGlb : null,
        workspace: typeof entry.workspace === 'string' && entry.workspace.trim() ? entry.workspace : 'default',
        createdAt: typeof entry.createdAt === 'string' ? entry.createdAt : new Date().toISOString(),
      }]
    })
  } catch {
    return []
  }
}

export function rememberCharacterCreatorSheet(
  history: CharacterCreatorHistoryEntry[],
  entry: CharacterCreatorHistoryEntry,
  limit = CHARACTER_CREATOR_HISTORY_LIMIT,
): CharacterCreatorHistoryEntry[] {
  const next = {
    ...entry,
    id: entry.id.trim() || `sheet-${entry.videoName}`,
    name: entry.name.trim() || entry.videoName,
    videoName: entry.videoName.trim(),
  }
  const without = history.filter(item => item.videoName !== next.videoName && item.id !== next.id)
  return [next, ...without].slice(0, Math.max(1, limit))
}

export function attachCharacterCreatorMesh(
  history: CharacterCreatorHistoryEntry[],
  videoName: string,
  hunyuanGlb: string,
): CharacterCreatorHistoryEntry[] {
  return history.map(item => item.videoName === videoName ? { ...item, hunyuanGlb } : item)
}
