import type { defineCapability } from './capabilityRegistry'
import i18n from '../../i18n'
import { failure, reloadSeries } from './seriesShotEditCapabilities'

/**
 * "Calibra la perspectiva de la lámina de la oficina": a location plate's stage (horizon, one reference object of known height, optional far
 * floor; services/series_stage.py) is stored with POST /api/v1/series/{series}/locations/{location}/stage, and read with `.../stage/check`:
 * the routes behind the `series.location.stage.set` and `.check` MCP tools and Series Lab's location panel (SeriesLocationStage). 2D wide and
 * two-shots there are then sized by it. The Wizard cannot see the grid image `check` draws: it gives the person its address and the horizon
 * guess, and the numbers must come from someone who looked (the person, or an agent with image sight through MCP), never from a guess.
 */
export interface StageRefInput { baseY: number; heightPct: number; heightM?: number }
export interface AgentSetSeriesLocationStageAction {
  type: 'set_series_location_stage'
  seriesId: string
  locationId: string
  horizon?: number
  ref?: StageRefInput
  floorTop?: number
  clear: boolean
}
export interface AgentCheckSeriesLocationStageAction {
  type: 'check_series_location_stage'
  seriesId: string
  locationId: string
  horizon?: number
  ref?: StageRefInput
  floorTop?: number
  step?: number
}

type StageReply = {
  locationId?: string, stage?: { horizon: number } | null, affectedShots?: string[], eyeHeightM?: number, warning?: string
  grid?: { url?: string, file?: string, step?: number }, plate?: { file?: string }
  suggestion?: { suggestion?: { horizon: number, confidence: string } | null }
  detail?: { message?: string } | string
}

/** The model fills the fields it does not use with 0 and "": those name nothing. */
const positive = (value: unknown, max: number): number | undefined => (
  typeof value === 'number' && Number.isFinite(value) && value > 0 && value <= max ? value : undefined)
const id = (value: unknown): string => typeof value === 'string' ? value.trim().slice(0, 160) : ''

function stageFields(raw: Record<string, unknown>): { horizon?: number, ref?: StageRefInput, floorTop?: number } {
  const [horizon, baseY, heightPct] = [positive(raw.horizon, 0.95), positive(raw.ref_base_y, 1), positive(raw.ref_height_pct, 1.5)]
  const heightM = positive(raw.ref_height_m, 30), floorTop = positive(raw.floor_top, 1)
  return { ...(horizon !== undefined ? { horizon } : {}),
           ...(baseY !== undefined && heightPct !== undefined ? { ref: { baseY, heightPct, ...(heightM !== undefined ? { heightM } : {}) } } : {}),
           ...(floorTop !== undefined ? { floorTop } : {}) }
}

/** The request body of `set`: the same fields as the MCP tool, left out when empty. */
export function stageSetBody(action: AgentSetSeriesLocationStageAction, workspace: string): Record<string, unknown> {
  return action.clear ? { workspace, clear: true }
    : { workspace, horizon: action.horizon, ref: action.ref, ...(action.floorTop !== undefined ? { floorTop: action.floorTop } : {}) }
}

/** The request body of `check`: the proposal (when there is one) and the grid step. */
export function stageCheckBody(action: AgentCheckSeriesLocationStageAction, workspace: string): Record<string, unknown> {
  return { workspace, ...(action.step !== undefined ? { step: action.step } : {}), ...(action.horizon !== undefined ? { horizon: action.horizon } : {}),
           ...(action.ref ? { ref: action.ref } : {}), ...(action.floorTop !== undefined ? { floorTop: action.floorTop } : {}) }
}

export function stageSetMessage(reply: StageReply, location: string): string {
  const said = reply.stage
    ? i18n.t('wizard:replies.stageSet', { location, count: reply.affectedShots?.length ?? 0, eye: reply.eyeHeightM ?? '' })
    : i18n.t('wizard:replies.stageCleared', { location })
  return [said, reply.warning].filter(Boolean).join(' ')
}

export function stageCheckMessage(reply: StageReply, location: string): string {
  const guess = reply.suggestion?.suggestion
  const where = i18n.t('wizard:replies.stageGrid', { location, file: reply.grid?.file ?? '', url: reply.grid?.url ?? '' })
  const horizon = guess ? i18n.t('wizard:replies.stageGuess', { horizon: guess.horizon, confidence: guess.confidence }) : i18n.t('wizard:replies.stageNoGuess')
  return [where, horizon, reply.eyeHeightM !== undefined ? i18n.t('wizard:replies.stageEye', { eye: reply.eyeHeightM }) : '', reply.warning,
          i18n.t('wizard:replies.stageLook')].filter(Boolean).join(' ')
}

type Target = { workspace: string, seriesId: string, locationId: string, location: string }

/** The location to calibrate: the one named, else the only one of the open series. Unsaved edits in Series Lab go first. */
export async function stageTarget(seriesId: string, locationId: string, workspace?: string, save = true): Promise<Target> {
  const { useSeriesStore } = await import('../series/store')
  const state = useSeriesStore.getState()
  if (save) await state.saveNow().catch(() => null)
  const series = seriesId || state.activeSeriesId
  const locations = state.library.seriesById[series]?.locations ?? []
  const found = locationId ? locations.find(item => item.id === locationId) : locations.length === 1 ? locations[0] : undefined
  if (!series) throw new Error('Open the series in Series Lab, or name it.')
  if (!locationId && !found) throw new Error('Name the location whose plate to calibrate (location_id).')
  return { workspace: workspace || state.workspace, seriesId: series, locationId: locationId || found!.id, location: found?.name || locationId }
}

async function postStage(url: string, body: Record<string, unknown>, fallback: string): Promise<StageReply> {
  // The Wizard declares itself, so a change it makes records ``createdBy: wizard``.
  const response = await fetch(url, { method: 'POST', headers: { 'content-type': 'application/json', 'X-Hocus-UI-Surface': 'wizard' }, body: JSON.stringify(body) })
  const reply = await response.json() as StageReply
  if (!response.ok) throw failure(reply, fallback)
  return reply
}

const stageUrl = (target: Target, tail = '') =>
  `/api/v1/series/${encodeURIComponent(target.seriesId)}/locations/${encodeURIComponent(target.locationId)}/stage${tail}`

export async function executeSetSeriesLocationStage(action: AgentSetSeriesLocationStageAction, workspace?: string) {
  const target = await stageTarget(action.seriesId, action.locationId, workspace)
  const reply = await postStage(stageUrl(target), stageSetBody(action, target.workspace), 'The stage could not be saved')
  await reloadSeries()
  return { message: stageSetMessage(reply, target.location), metadata: reply as Record<string, unknown>,
           target: { kind: 'series', id: target.seriesId, title: target.location } }
}

export async function executeCheckSeriesLocationStage(action: AgentCheckSeriesLocationStageAction, workspace?: string) {
  const target = await stageTarget(action.seriesId, action.locationId, workspace, false)
  const reply = await postStage(stageUrl(target, '/check'), stageCheckBody(action, target.workspace), 'The plate could not be read')
  return { message: stageCheckMessage(reply, target.location), metadata: reply as Record<string, unknown>,
           target: { kind: 'series', id: target.seriesId, title: target.location } }
}

const NUMBER = (maximum: number) => ({ type: 'number', minimum: 0, maximum })
const SHARED = {
  series_id: { type: 'string', maxLength: 160 }, location_id: { type: 'string', maxLength: 160 }, horizon: NUMBER(0.95),
  ref_base_y: NUMBER(1), ref_height_pct: NUMBER(1.5), ref_height_m: NUMBER(30), floor_top: NUMBER(1),
} as const

export function registerSeriesStageCapabilities(register: typeof defineCapability) {
  register<AgentSetSeriesLocationStageAction>({
    name: 'set_series_location_stage',
    title: 'Calibrate the perspective of a Series Lab location plate',
    description: 'Save the perspective (stage) of a location plate, so 2D wide and two-shots there size each person by where they stand and how tall they are instead of by the framing alone: horizon = y of the eye line, ref_base_y = y of the foot of one reference object of known height (a door), ref_height_pct = how tall it is on the plate, ref_height_m = its metres (default 2), floor_top = the farthest floor (optional); all fractions of the plate height from the top. NEVER guess them: they must come from someone who looked at the plate\'s grid (check_series_location_stage, then the numbers the user reads off it). clear=true removes the stage. The reply says how many shots render again and the camera height the numbers imply (about 1.6 m is right; far from it the numbers were probably misread). Series Lab\'s location panel edits the same stage.',
    useWhen: 'The user gives the numbers of a plate\'s perspective (horizon, door base and height) or asks to remove a location\'s calibration ("fija el horizonte de la oficina en 0,22 con la puerta entre 0,10 y 0,72", "quita la calibración del hangar").',
    parameters: ['series_id', 'location_id', 'horizon', 'ref_base_y', 'ref_height_pct', 'ref_height_m', 'floor_top', 'clear'],
    inputSchema: {
      type: 'object', additionalProperties: false,
      properties: { type: { const: 'set_series_location_stage' }, ...SHARED, clear: { type: 'boolean' } },
      required: ['type'],
    },
    risk: 'edit', confirmation: 'none', progress: 'wizard:progress.settingLocationStage',
    resolve(raw) {
      const fields = stageFields(raw)
      const clear = raw.clear === true
      if (!clear && (fields.horizon === undefined || !fields.ref)) return null
      return { type: 'set_series_location_stage', seriesId: id(raw.series_id), locationId: id(raw.location_id), ...(clear ? {} : fields), clear }
    },
    validate(action) {
      if (action.clear) return []
      return action.horizon !== undefined && action.ref && action.ref.baseY - action.horizon >= 0.01
        ? [] : ['The reference foot (ref_base_y) must be below the horizon; give horizon, ref_base_y and ref_height_pct.']
    },
    async prepare(action) { return action },
    async execute(action, context) { return context.adapters.seriesShots.setStage(action, context.workspace) },
    correlate(_action, outcome) { return outcome.target },
    async track(_action, outcome) { return outcome },
    report: { targetKind: 'series', successState: 'completed' },
    summarize(_action, outcome) { return outcome.message },
    presentation: { destination: 'series_lab', anchors: ['canon', 'locations'], replay: 'atomic' },
  })
  register<AgentCheckSeriesLocationStageAction>({
    name: 'check_series_location_stage',
    title: 'Draw a grid over a Series Lab location plate to read its perspective',
    description: 'Draw a grid (a line every 10 % of the plate, labelled) over the location\'s still plate, save it as a workspace image and answer with its file and address, the saved stage, a cheap horizon guess with its confidence and the camera height a proposal implies. It changes nothing in the series. You cannot see the image: give the user the address so they (or a capable agent) can read baseY, heightPct and the horizon off it; never invent numbers. With horizon, ref_base_y and ref_height_pct it also draws that proposal (three 1.75 m bars) so it can be checked before set_series_location_stage.',
    useWhen: 'The user wants to calibrate a location plate\'s perspective or asks for the grid of a location ("enséñame la rejilla de la oficina", "quiero calibrar la escala del hangar").',
    parameters: ['series_id', 'location_id', 'horizon', 'ref_base_y', 'ref_height_pct', 'ref_height_m', 'floor_top', 'grid_step'],
    inputSchema: {
      type: 'object', additionalProperties: false,
      properties: { type: { const: 'check_series_location_stage' }, ...SHARED, grid_step: { type: 'number', minimum: 0, maximum: 0.25 } },
      required: ['type'],
    },
    risk: 'read', confirmation: 'none', progress: 'wizard:progress.checkingLocationStage',
    resolve(raw) {
      const step = typeof raw.grid_step === 'number' && raw.grid_step >= 0.05 && raw.grid_step <= 0.25 ? raw.grid_step : undefined
      return { type: 'check_series_location_stage', seriesId: id(raw.series_id), locationId: id(raw.location_id), ...stageFields(raw), ...(step !== undefined ? { step } : {}) }
    },
    validate() { return [] },
    async prepare(action) { return action },
    async execute(action, context) { return context.adapters.seriesShots.checkStage(action, context.workspace) },
    correlate(_action, outcome) { return outcome.target },
    async track(_action, outcome) { return outcome },
    report: { targetKind: 'series', successState: 'completed' },
    summarize(_action, outcome) { return outcome.message },
    presentation: { destination: 'series_lab', anchors: ['canon', 'locations'] },
  })
}
