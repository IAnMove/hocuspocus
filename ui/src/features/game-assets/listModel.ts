import type { GameAsset, GameEstimate, ProduceStep } from './types'

export const OPEN_STATUSES = ['pending', 'rejected', 'failed'] as const

export const EXAMPLE_LIST = `personaje heroe: caballero bajito con armadura de bronce y capa roja | jugador
anim heroe: idle, andar, saltar, atacar, herido, morir
personaje slime: babosa verde gelatinosa | enemigo
objeto moneda: moneda de oro | anim girar | 8 frames
tileset hierba: suelo de hierba sobre tierra
fondo bosque: bosque al atardecer | capas 3
ui boton: botón de madera | 9-slice
efecto explosion: explosión pequeña con chispas | 12 frames
sfx salto: salto corto y ligero | variantes 3
musica nivel1: tema alegre de bosque | bucle 60 s`

export const SPEC_FIELDS: Record<string, { key: string; input: 'text' | 'number' }[]> = {
  character: [{ key: 'role', input: 'text' }, { key: 'heightPx', input: 'number' }],
  sprite: [{ key: 'pose', input: 'text' }, { key: 'heightPx', input: 'number' }],
  animation: [{ key: 'action', input: 'text' }, { key: 'method', input: 'text' }, { key: 'frames', input: 'number' }, { key: 'fps', input: 'number' }],
  item: [{ key: 'sizePx', input: 'number' }],
  icon: [{ key: 'sizePx', input: 'number' }, { key: 'frame', input: 'text' }],
  ui: [{ key: 'element', input: 'text' }, { key: 'widthPx', input: 'number' }, { key: 'heightPx', input: 'number' }],
  tile: [{ key: 'sizePx', input: 'number' }, { key: 'variants', input: 'number' }],
  tileset: [{ key: 'sizePx', input: 'number' }],
  background: [{ key: 'layers', input: 'number' }, { key: 'method', input: 'text' }],
  vfx: [{ key: 'effect', input: 'text' }, { key: 'frames', input: 'number' }],
  sfx: [{ key: 'trigger', input: 'text' }, { key: 'seconds', input: 'number' }, { key: 'engine', input: 'text' }],
  music: [{ key: 'loopSeconds', input: 'number' }, { key: 'mood', input: 'text' }],
  jingle: [{ key: 'seconds', input: 'number' }, { key: 'mood', input: 'text' }],
  voice: [{ key: 'character', input: 'text' }],
  model3d: [{ key: 'maxTriangles', input: 'number' }],
  character3d: [{ key: 'profile', input: 'text' }],
}

export function visibleAssets(assets: GameAsset[], filter: { kind: string; status: string; query: string }): GameAsset[] {
  const query = filter.query.trim().toLowerCase()
  return assets.filter(asset => {
    if (filter.kind && asset.kind !== filter.kind) return false
    if (filter.status && asset.status !== filter.status) return false
    if (!query) return true
    return `${asset.id} ${asset.name} ${asset.description}`.toLowerCase().includes(query)
  })
}

export function produceTargets(assets: GameAsset[], mode: 'pending' | 'rerender' | 'selected', selected: string[]): GameAsset[] {
  if (mode === 'rerender') return assets.filter(asset => asset.status === 'stale' && !asset.locked)
  if (mode === 'selected') {
    const ids = new Set(selected)
    return assets.filter(asset => ids.has(asset.id) && (OPEN_STATUSES.includes(asset.status as typeof OPEN_STATUSES[number]) || (asset.status === 'stale' && !asset.locked)))
  }
  return assets.filter(asset => OPEN_STATUSES.includes(asset.status as typeof OPEN_STATUSES[number]))
}

export function estimateSource(source: string): 'history' | 'trial' | 'defaults' {
  if (source.startsWith('history')) return 'history'
  if (source === 'trial') return 'trial'
  return 'defaults'
}

export function readEstimate(value: unknown): GameEstimate {
  const raw = value && typeof value === 'object' ? value as Record<string, unknown> : {}
  const byKind = raw.byKind && typeof raw.byKind === 'object' ? raw.byKind as Record<string, number> : {}
  return {
    minutes: typeof raw.minutes === 'number' ? raw.minutes : 0,
    source: typeof raw.source === 'string' ? raw.source : 'defaults',
    byKind,
  }
}

export interface KindBar { kind: string; done: number; total: number }

export function kindProgress(steps: ProduceStep[] | undefined): KindBar[] {
  const bars = new Map<string, KindBar>()
  for (const step of steps || []) {
    const kind = step.kind || 'other'
    const bar = bars.get(kind) || { kind, done: 0, total: 0 }
    bar.total += 1
    if (step.status === 'done' || step.status === 'failed' || step.status === 'skipped') bar.done += 1
    bars.set(kind, bar)
  }
  return [...bars.values()]
}

export function waitingSteps(steps: ProduceStep[] | undefined): ProduceStep[] {
  return (steps || []).filter(step => step.reason === 'waiting_dependency')
}

export function specPatch(asset: GameAsset, draft: Record<string, string>): Record<string, unknown> {
  const spec: Record<string, unknown> = { ...asset.spec }
  for (const field of SPEC_FIELDS[asset.kind] || []) {
    const raw = (draft[field.key] || '').trim()
    if (!raw) continue
    if (field.input === 'number') {
      const parsed = Number(raw)
      if (Number.isFinite(parsed)) spec[field.key] = parsed
    } else spec[field.key] = raw
  }
  return { name: draft.name ?? asset.name, description: draft.description ?? asset.description, spec }
}

export function listBody(text: string, format: 'lines' | 'csv' | 'json'): { text?: string; csv?: string; items?: unknown[]; format: string } {
  if (format === 'csv') return { csv: text, format: 'csv' }
  if (format === 'json') {
    const parsed = JSON.parse(text) as unknown
    if (!Array.isArray(parsed)) throw new Error('JSON items must be a list')
    return { items: parsed, format: 'json' }
  }
  return { text, format: 'lines' }
}
