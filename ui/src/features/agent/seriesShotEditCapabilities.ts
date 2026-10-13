import type { defineCapability } from './capabilityRegistry'
import i18n from '../../i18n'

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

/** "Vuelve a grabar la segunda línea del plano 12": one line's voice recorded now (series.shot.voice). */
export interface AgentRecordSeriesLineAction {
  type: 'regenerate_series_line_voice'
  seriesId: string
  episodeId: string
  shot: string | number
  line: number
  retake: boolean
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
  const shot = i18n.t('wizard:replies.shotLabel', { number: reply.number ?? '', id: reply.shotId || '' }).replace('  ', ' ')
  if (reply.render?.jobId) return i18n.t('wizard:replies.shotRerendering', { shot, jobId: reply.render.jobId })
  if (reply.produce?.jobId) return i18n.t('wizard:replies.shotProducing', { shot, jobId: reply.produce.jobId })
  if (reply.note) return i18n.t('wizard:replies.shotNote', { shot, note: reply.note })
  const changed = reply.changed?.length ? reply.changed.join(', ') : i18n.t('wizard:replies.shotNothing')
  const summary = reply.instruction?.summary ? ` ${reply.instruction.summary}.` : ''
  const approval = reply.approvalReset ? i18n.t('wizard:replies.shotApprovalReset') : ''
  const missing = Object.entries(reply.missingLines || {}).filter(([, lines]) => lines.length)
    .map(([language, lines]) => i18n.t('wizard:replies.shotMissingLines', { language, lines: lines.length })).join('')
  return i18n.t('wizard:replies.shotEdited', { shot, changed, summary, approval, missing }).replace('..', '.')
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

type VoiceJob = { jobId?: string, status?: string, beatId?: string, error?: string, result?: { filename?: string } }
const VOICE_WAIT_MS = 90_000
const VOICE_POLL_MS = 1500

function lineVoiceMessage(action: AgentRecordSeriesLineAction, job: VoiceJob): string {
  const line = i18n.t('wizard:replies.shotLineLabel', { line: action.line, shot: action.shot })
  const recorded = action.retake ? i18n.t('wizard:replies.shotLineRetake') : i18n.t('wizard:replies.shotLineVoice')
  if (job.status === 'completed') return i18n.t('wizard:replies.shotLineCompleted', { line, recorded, file: job.result?.filename || '' })
  if (job.status === 'failed' || job.status === 'interrupted') return i18n.t('wizard:replies.shotLineFailed', { line, error: job.error || job.status })
  return i18n.t('wizard:replies.shotLineRecording', { line, jobId: job.jobId })
}

const recording = (job: VoiceJob) => Boolean(job.jobId) && (job.status === 'queued' || job.status === 'running')

/** Record one line now and wait for it (a minute and a half at most: a busy GPU keeps it recording in the background). */
export async function executeSeriesLineVoice(action: AgentRecordSeriesLineAction, workspace?: string, sleep = (ms: number) => new Promise(done => setTimeout(done, ms))) {
  const target = await activeShotTarget(action.seriesId, action.episodeId, workspace)
  const base = `/api/v1/series/${encodeURIComponent(target.seriesId)}/episodes/${encodeURIComponent(target.episodeId)}/shots/${encodeURIComponent(String(action.shot))}/voices`
  const response = await fetch(base, { method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ workspace: target.workspace, line: action.line, retake: action.retake }) })
  let job = await response.json() as VoiceJob & ShotReply
  if (!response.ok) throw failure(job, 'The line could not be recorded')
  const started = Date.now()
  while (recording(job) && Date.now() - started < VOICE_WAIT_MS) {
    await sleep(VOICE_POLL_MS)
    const polled = await fetch(`/api/v1/series/voice-jobs/${encodeURIComponent(job.jobId!)}?workspace=${encodeURIComponent(target.workspace)}`)
    if (polled.ok) job = await polled.json() as VoiceJob
  }
  return { message: lineVoiceMessage(action, job), metadata: job as Record<string, unknown>, jobId: job.jobId,
    target: { kind: 'series_episode', id: target.episodeId, title: `${action.shot} · ${action.line}` } }
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
    description: 'Edit one shot of the open (or named) Series episode: shot_number is the #N the episode shows (5 = the fifth shot), or shot_id. Put the user\'s request in instruction (their words: "ponle un sombrero a Kevin", "acerca la cámara en el remate", "añade una explosión cuando grita") and the server writes the edit from the real shot, cast, poses, files and effects. Only for an exact, known edit fill changes (script keys: framing, camera push|static, cast, lines, fx, sfx, props, layers, music, timing, foley, resolution 480p|540p|720p|768p for the H3 clip of a video shot…) or append (adds to fx, sfx, props, layers, cast, lines). Takes are kept; a shot that no longer matches its take loses its approval. It does not render.',
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
    risk: 'edit', confirmation: 'none', progress: 'wizard:progress.editingShot',
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
  register<AgentRecordSeriesLineAction>({
    name: 'regenerate_series_line_voice',
    title: 'Record one line of a Series Lab shot again',
    description: 'Record the voice of one line of a shot of the open (or named) Series episode now, with the render\'s own voice path (the character\'s voice, trimmed, checked, lip-sync cues): shot_number (#N in the episode) or shot_id, and line_number (1 = the shot\'s first line). retake=true records another take of an unchanged line with another seed and keeps the old one if it fails; otherwise a line already recorded for its text is kept. The shot\'s take is not touched: add rerender_series_shot to hear it in the take.',
    useWhen: 'The user asks to redo, regenerate or record again the voice of one specific line of a shot ("vuelve a grabar la segunda línea del plano 12", "otra toma de voz de Inés en el plano 3").',
    parameters: ['series_id', 'episode_id', 'shot_number', 'shot_id', 'line_number', 'retake', 'confirm'],
    inputSchema: {
      type: 'object', additionalProperties: false,
      properties: { type: { const: 'regenerate_series_line_voice' }, ...SHOT_FIELDS, line_number: { type: 'integer', minimum: 0, maximum: 99 },
        retake: { type: 'boolean' }, confirm: { const: true } },
      required: ['type', 'confirm'],
    },
    risk: 'compute', confirmation: 'required', progress: 'wizard:progress.recordingLineOnServer',
    resolve(raw) {
      const shot = shotRef(raw)
      const line = typeof raw.line_number === 'number' && Number.isInteger(raw.line_number) ? raw.line_number : 0
      if (raw.confirm !== true || shot === null || line < 1) return null
      return { type: 'regenerate_series_line_voice', seriesId: text(raw.series_id, 160), episodeId: text(raw.episode_id, 160), shot, line,
               retake: raw.retake === true, confirm: true }
    },
    validate(action) { return action.confirm === true && action.line >= 1 ? [] : ['Say which line (line_number, 1 = the first) and confirm.'] },
    async prepare(action) { return action },
    async execute(action, context) { return context.adapters.seriesShots.voice(action, context.workspace) },
    correlate(_action, outcome) { return outcome.target },
    async track(_action, outcome) { return outcome },
    report: { targetKind: 'series_episode', successState: 'completed' },
    summarize(_action, outcome) { return outcome.message },
    presentation: { destination: 'series_lab', anchors: ['review', 'lines'], replay: 'atomic' },
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
    risk: 'compute', confirmation: 'required', progress: 'wizard:progress.renderingShotOnServer',
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
