import type { defineCapability } from './capabilityRegistry'

/**
 * "Edita el quinto plano y ponle X": one Series shot, named by its number in the
 * episode (the #N Series Lab shows) or its id, edited through
 * POST /api/v1/series/{series}/episodes/{episode}/shots/edit, the route behind
 * the series.shot.update MCP tool. The Wizard passes the user's words as
 * `instruction` and the server's LLM writes the edit against the real shot,
 * cast, poses, files and effects; explicit `changes`/`append` (script keys of
 * series.episode.from_script) are applied as they are. Rendering again is a
 * separate, confirmed action.
 */
export interface AgentEditSeriesShotAction {
  type: 'edit_series_shot'
  seriesId: string
  episodeId: string
  shot: string | number
  instruction: string
  changes?: Record<string, unknown>
  append?: Record<string, unknown>
}

export interface AgentRerenderSeriesShotAction {
  type: 'rerender_series_shot'
  seriesId: string
  episodeId: string
  shot: string | number
  produce: boolean
  confirm: true
}

type ShotTarget = { workspace: string, seriesId: string, episodeId: string }
type ShotReply = {
  shotId?: string, number?: number, changed?: string[], approvalReset?: boolean, note?: string
  missingLines?: Record<string, string[]>, instruction?: { summary?: string }
  render?: { jobId?: string }, produce?: { jobId?: string }
  detail?: { message?: string, problems?: string[] } | string
}

const text = (value: unknown, limit: number): string => typeof value === 'string' ? value.trim().slice(0, limit) : ''
const record = (value: unknown): Record<string, unknown> | undefined => (
  value && typeof value === 'object' && !Array.isArray(value) && Object.keys(value).length ? value as Record<string, unknown> : undefined)

/** The shot the user named: a positive number (its #N in the episode) or a shot id; 0 and "" mean none. */
export function shotRef(raw: Record<string, unknown>): string | number | null {
  const number = typeof raw.shot_number === 'number' && Number.isFinite(raw.shot_number) ? Math.round(raw.shot_number) : 0
  if (number >= 1 && number <= 999) return number
  const id = text(raw.shot_id, 160)
  return id || null
}

function failure(body: ShotReply, fallback: string): Error {
  const detail = body.detail
  if (typeof detail === 'string') return new Error(detail)
  const problems = detail?.problems?.length ? `: ${detail.problems.slice(0, 4).join('; ')}` : ''
  return new Error(`${detail?.message || fallback}${problems}`)
}

export async function postShotEdit(target: ShotTarget, body: Record<string, unknown>): Promise<ShotReply> {
  const url = `/api/v1/series/${encodeURIComponent(target.seriesId)}/episodes/${encodeURIComponent(target.episodeId)}/shots/edit`
  const response = await fetch(url, {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ workspace: target.workspace, ...body }),
  })
  const reply = await response.json() as ShotReply
  if (!response.ok) throw failure(reply, 'The shot could not be edited')
  return reply
}

export function shotEditMessage(reply: ShotReply): string {
  const shot = `Plano ${reply.number ?? ''} (${reply.shotId || ''})`.replace('  ', ' ')
  if (reply.render?.jobId) return `${shot}: renderizando de nuevo en el servidor (${reply.render.jobId}).`
  if (reply.produce?.jobId) return `${shot}: produciendo el episodio (${reply.produce.jobId}); se renderiza lo cambiado y se vuelve a montar.`
  if (reply.note) return `${shot}: ${reply.note}`
  const changed = reply.changed?.length ? reply.changed.join(', ') : 'nada'
  const summary = reply.instruction?.summary ? ` ${reply.instruction.summary}.` : ''
  const approval = reply.approvalReset ? ' Su toma ya no muestra el plano: la aprobación se quitó; vuelve a renderizarlo para verlo.' : ''
  const missing = Object.entries(reply.missingLines || {}).filter(([, lines]) => lines.length)
    .map(([language, lines]) => ` A la versión ${language} le faltan ${lines.length} líneas.`).join('')
  return `${shot} editado: ${changed}.${summary}${approval}${missing}`.replace('..', '.')
}

export async function activeShotTarget(seriesId: string, episodeId: string, workspace?: string): Promise<ShotTarget> {
  const { useSeriesStore } = await import('../series/store')
  const state = useSeriesStore.getState()
  // Unsaved edits in Series Lab go first, so the server edit starts from what the user sees.
  await state.saveNow().catch(() => null)
  const target = { workspace: workspace || state.workspace, seriesId: seriesId || state.activeSeriesId, episodeId: episodeId || state.activeEpisodeId }
  if (!target.seriesId || !target.episodeId) throw new Error('Open the episode in Series Lab, or name its series and episode.')
  return target
}

async function reloadSeries(): Promise<void> {
  const { useSeriesStore } = await import('../series/store')
  await useSeriesStore.getState().reload().catch(() => undefined)
}

export async function executeSeriesShotEdit(action: AgentEditSeriesShotAction | AgentRerenderSeriesShotAction, workspace?: string) {
  const target = await activeShotTarget(action.seriesId, action.episodeId, workspace)
  const body: Record<string, unknown> = action.type === 'edit_series_shot'
    ? { shot: action.shot, ...(action.changes ? { changes: action.changes } : {}), ...(action.append ? { append: action.append } : {}),
        ...(!action.changes && !action.append ? { instruction: action.instruction } : {}) }
    : { shot: action.shot, ...(action.produce ? { produce: true } : { render: true, approve: true }) }
  const reply = await postShotEdit(target, body)
  await reloadSeries()
  return {
    message: shotEditMessage(reply),
    metadata: reply as Record<string, unknown>,
    jobId: reply.render?.jobId || reply.produce?.jobId,
    target: { kind: 'series_episode', id: target.episodeId, title: reply.shotId || String(action.shot) },
  }
}

const SHOT_FIELDS = {
  series_id: { type: 'string', maxLength: 160 },
  episode_id: { type: 'string', maxLength: 160 },
  shot_number: { type: 'integer', minimum: 0, maximum: 999 },
  shot_id: { type: 'string', maxLength: 160 },
}

export function registerSeriesShotEditCapabilities(register: typeof defineCapability) {
  register<AgentEditSeriesShotAction>({
    name: 'edit_series_shot',
    title: 'Edit one Series Lab shot by instruction',
    description: 'Edit one shot of the open (or named) Series episode: shot_number is the #N the episode shows (5 = the fifth shot), or shot_id. Put the user\'s request in instruction (their words: "ponle un sombrero a Kevin", "acerca la cámara en el remate", "añade una explosión cuando grita") and the server writes the edit from the real shot, cast, poses, files and effects. Only for an exact, known edit fill changes (script keys: framing, camera push|static, cast, lines, fx, sfx, props, layers, music, timing, foley…) or append (adds to fx, sfx, props, layers, cast, lines). Takes are kept; a shot that no longer matches its take loses its approval. It does not render.',
    useWhen: 'The user asks to change, fix or add something to a specific shot ("el quinto plano", "plano 3", "this shot") of a Series Lab episode.',
    parameters: ['series_id', 'episode_id', 'shot_number', 'shot_id', 'instruction', 'changes', 'append'],
    inputSchema: {
      type: 'object', additionalProperties: false,
      properties: {
        type: { const: 'edit_series_shot' }, ...SHOT_FIELDS,
        instruction: { type: 'string', maxLength: 2000 }, changes: { type: 'object' }, append: { type: 'object' },
      },
      required: ['type'],
    },
    risk: 'edit', confirmation: 'none', progress: 'Editando el plano…',
    resolve(raw) {
      const shot = shotRef(raw)
      const instruction = text(raw.instruction, 2000)
      const changes = record(raw.changes)
      const append = record(raw.append)
      if (shot === null || (!instruction && !changes && !append)) return null
      return { type: 'edit_series_shot', seriesId: text(raw.series_id, 160), episodeId: text(raw.episode_id, 160), shot, instruction,
               ...(changes ? { changes } : {}), ...(append ? { append } : {}) }
    },
    validate(action) { return action.instruction || action.changes || action.append ? [] : ['Say what to change in the shot.'] },
    async prepare(action) { return action },
    async execute(action, context) { return context.adapters.seriesShots.edit(action, context.workspace) },
    correlate(_action, outcome) { return outcome.target },
    async track(_action, outcome) { return outcome },
    report: { targetKind: 'series_episode', successState: 'completed' },
    summarize(_action, outcome) { return outcome.message },
    presentation: { destination: 'series_lab', anchors: ['episode', 'shots'], replay: 'atomic' },
  })
  register<AgentRerenderSeriesShotAction>({
    name: 'rerender_series_shot',
    title: 'Render one Series Lab shot again',
    description: 'Render just one shot of the open (or named) Series episode again on the server (its voices, scene and take, approved), by shot_number (#N in the episode) or shot_id; produce=true instead renders what changed in every language and recuts the episode. A generated or imported video take is not rendered: its sound is laid at the cut.',
    useWhen: 'The user explicitly asks to render, redo or regenerate a specific shot after an edit, or to see the change in the episode.',
    parameters: ['series_id', 'episode_id', 'shot_number', 'shot_id', 'produce', 'confirm'],
    inputSchema: {
      type: 'object', additionalProperties: false,
      properties: { type: { const: 'rerender_series_shot' }, ...SHOT_FIELDS, produce: { type: 'boolean' }, confirm: { const: true } },
      required: ['type', 'confirm'],
    },
    risk: 'compute', confirmation: 'required', progress: 'Renderizando el plano en el servidor…',
    resolve(raw) {
      const shot = shotRef(raw)
      if (raw.confirm !== true || shot === null) return null
      return { type: 'rerender_series_shot', seriesId: text(raw.series_id, 160), episodeId: text(raw.episode_id, 160), shot,
               produce: raw.produce === true, confirm: true }
    },
    validate(action) { return action.confirm === true ? [] : ['confirmation is required'] },
    async prepare(action) { return action },
    async execute(action, context) { return context.adapters.seriesShots.rerender(action, context.workspace) },
    correlate(_action, outcome) { return outcome.target },
    async track(_action, outcome) { return outcome },
    report: { targetKind: 'series_episode', successState: 'completed' },
    summarize(_action, outcome) { return outcome.message },
    presentation: { destination: 'series_lab', anchors: ['review', 'render'], replay: 'atomic' },
  })
}
