import type { defineCapability } from './capabilityRegistry'
import i18n from '../../i18n'
import { activeShotTarget, failure, reloadSeries, shotRef } from './seriesShotEditCapabilities'

/**
 * "Pon la tarjeta de andar en el plano 3": a whole Video 2D card (`walk-cycle-sheet`, `walk-toward-camera`, `character-reaction`…) becomes
 * a new take of one Series shot, through POST /api/v1/series/{series}/episodes/{episode}/shots/{shot}/card, the route behind the
 * `series.shot.card.apply` MCP tool (services/series_shot_card.py): the server binds the card to the shot's characters (their pose
 * pictures, or for the sheet cards the approved animation sheet), compiles it, saves the scene so it opens in Video 2D, exports it and
 * attaches the take as a candidate. The Wizard asks it to approve the take only in «Modo un solo disparo» (Settings › Services); in the
 * default review mode the server refuses `approve` and the person approves in Series Lab. A scene that is still being exported answers
 * `exporting`: the same request finishes it, so the Wizard sends it again for a few minutes at most.
 */
export interface SeriesShotCardCast {
  slot?: string
  characterId: string
  animation?: string
  poseId?: string
}

export interface AgentApplySeriesShotCardAction {
  type: 'apply_series_shot_card'
  seriesId: string
  episodeId: string
  shot: string | number
  card: string
  cast?: SeriesShotCardCast[]
  controls?: Record<string, unknown>
  assets?: Record<string, string>
  language?: string
  approve: boolean
}

type CardReply = {
  status?: 'completed' | 'exporting'
  shotId?: string, number?: number, card?: string, scene?: string, warnings?: string[], approvalNote?: string
  take?: { attemptId?: string, approved?: boolean, reused?: boolean, superseded?: string[] }
  detail?: { message?: string } | string
}

const CARD = /^[a-z0-9][a-z0-9-]{0,119}$/
const text = (value: unknown, limit: number): string => typeof value === 'string' ? value.trim().slice(0, limit) : ''
const record = (value: unknown): Record<string, unknown> | undefined => (
  value && typeof value === 'object' && !Array.isArray(value) && Object.keys(value).length ? value as Record<string, unknown> : undefined)
/** An entry of the model's `card_cast`; the model fills unused fields with "" and those name nothing. */
function castEntry(raw: unknown): SeriesShotCardCast | null {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null
  const item = raw as Record<string, unknown>
  const characterId = text(item.characterId, 160)
  if (!characterId) return null
  const [slot, animation, poseId] = [text(item.slot, 40), text(item.animation, 64).toLowerCase(), text(item.poseId, 160)]
  return { characterId, ...(slot ? { slot } : {}), ...(animation ? { animation } : {}), ...(poseId ? { poseId } : {}) }
}
function assetsOf(raw: unknown): Record<string, string> | undefined {
  const found = record(raw)
  const entries = Object.entries(found ?? {}).map(([slot, source]) => [slot, text(source, 2000)] as const).filter(([, source]) => source)
  return entries.length ? Object.fromEntries(entries) : undefined
}

/** The request body: the same fields as the MCP tool, left out when empty. */
export function cardBody(action: AgentApplySeriesShotCardAction, workspace: string): Record<string, unknown> {
  return { workspace, card: action.card, ...(action.cast?.length ? { cast: action.cast } : {}), ...(action.controls ? { controls: action.controls } : {}),
           ...(action.assets ? { assets: action.assets } : {}), ...(action.language ? { language: action.language } : {}), ...(action.approve ? { approve: true } : {}) }
}

export function cardMessage(reply: CardReply): string {
  const shot = i18n.t('wizard:replies.shotLabel', { number: reply.number ?? '', id: reply.shotId || '' }).replace('  ', ' ')
  if (reply.status === 'exporting') return i18n.t('wizard:replies.shotCardExporting', { shot, card: reply.card, scene: reply.scene })
  const approved = reply.take?.approved ? i18n.t('wizard:replies.shotCardApproved') : i18n.t('wizard:replies.shotCardWaits')
  const said = i18n.t(reply.take?.reused ? 'wizard:replies.shotCardReused' : 'wizard:replies.shotCardTake', { shot, card: reply.card, scene: reply.scene, approved })
  return [said, reply.approvalNote, ...(reply.warnings ?? [])].filter(Boolean).join(' ')
}

const EXPORT_TRIES = 8
const EXPORT_PAUSE_MS = 15_000

async function postCard(url: string, body: Record<string, unknown>): Promise<CardReply> {
  // The Wizard declares itself, so a take it approves records ``approvedBy: wizard``.
  const response = await fetch(url, { method: 'POST', headers: { 'content-type': 'application/json', 'X-Hocus-UI-Surface': 'wizard' }, body: JSON.stringify(body) })
  const reply = await response.json() as CardReply
  if (!response.ok) throw failure(reply, 'The card could not be put on the shot')
  return reply
}

export async function executeApplySeriesShotCard(action: AgentApplySeriesShotCardAction, workspace?: string,
                                                 sleep = (ms: number) => new Promise<void>(done => setTimeout(done, ms))) {
  const target = await activeShotTarget(action.seriesId, action.episodeId, workspace)
  const url = `/api/v1/series/${encodeURIComponent(target.seriesId)}/episodes/${encodeURIComponent(target.episodeId)}/shots/${encodeURIComponent(String(action.shot))}/card`
  const body = cardBody(action, target.workspace)
  let reply = await postCard(url, body)
  // Not exported yet: the same request finds the export and attaches the take.
  for (let tries = 1; reply.status === 'exporting' && tries < EXPORT_TRIES; tries += 1) {
    await sleep(EXPORT_PAUSE_MS)
    reply = await postCard(url, body)
  }
  await reloadSeries()
  return {
    message: cardMessage(reply), metadata: reply as Record<string, unknown>,
    target: { kind: 'series_episode', id: target.episodeId, title: reply.shotId || String(action.shot) },
  }
}

export function registerSeriesShotCardCapabilities(register: typeof defineCapability) {
  register<AgentApplySeriesShotCardAction>({
    name: 'apply_series_shot_card',
    title: 'Put a Video 2D card on a Series Lab shot as a new take',
    description: 'Put a Video 2D card (walk-cycle-sheet, walk-two-pose, walk-toward-camera, walk-follow-back, walk-behind-foreground, character-reaction or any card of the 2D catalog) on one 2D shot of the open (or named) Series episode as a NEW TAKE, in one step: shot_number (#N in the episode) or shot_id, card_id, and card_cast to bind the card\'s character slots [{slot: "subject_1", characterId, animation?, poseId?}] (without it the shot\'s own people fill them). The sheet cards play the character\'s APPROVED animation sheet (walk by default for the walk cards; character-reaction needs animation: wave, angry…) and the server refuses a pending or rejected one; the other cards draw its pose picture. The shot\'s location plate is the background; card_assets {slot: workspace file} fills a foreground or a prop; card_controls are the card\'s own. The shot\'s spoken lines must be recorded first. The scene opens in Video 2D and the take is a candidate the person approves in Series Lab: approve_take=true approves it only when the owner turned on one-shot mode (Settings › Services); otherwise the server refuses.',
    useWhen: 'The user asks to put a card, a walk-in, a walking shot or a character reaction on a specific shot of a Series Lab episode ("pon la tarjeta de andar en el plano 3", "que Gloria entre andando en el plano 5", "una reacción de enfado de Leo en el plano 8").',
    parameters: ['series_id', 'episode_id', 'shot_number', 'shot_id', 'card_id', 'card_cast', 'card_controls', 'card_assets', 'card_language', 'approve_take'],
    inputSchema: {
      type: 'object', additionalProperties: false,
      properties: {
        type: { const: 'apply_series_shot_card' }, series_id: { type: 'string', maxLength: 160 }, episode_id: { type: 'string', maxLength: 160 },
        shot_number: { type: 'integer', minimum: 0, maximum: 999 }, shot_id: { type: 'string', maxLength: 160 }, card_id: { type: 'string', maxLength: 120 },
        card_cast: { type: 'array', maxItems: 6, items: { type: 'object', additionalProperties: false, required: ['characterId'], properties: {
          slot: { type: 'string', maxLength: 40 }, characterId: { type: 'string', maxLength: 160 }, animation: { type: 'string', maxLength: 64 },
          poseId: { type: 'string', maxLength: 160 } } } },
        card_controls: { type: 'object' }, card_assets: { type: 'object', additionalProperties: { type: 'string' } },
        card_language: { type: 'string', maxLength: 40 }, approve_take: { type: 'boolean' },
      },
      required: ['type', 'card_id'],
    },
    risk: 'edit', confirmation: 'none', progress: 'wizard:progress.applyingShotCard',
    resolve(raw) {
      const shot = shotRef(raw)
      const card = text(raw.card_id, 120).toLowerCase()
      if (shot === null || !CARD.test(card)) return null
      const cast = Array.isArray(raw.card_cast) ? raw.card_cast.map(castEntry).filter((item): item is SeriesShotCardCast => item !== null) : []
      const controls = record(raw.card_controls)
      const assets = assetsOf(raw.card_assets)
      const language = text(raw.card_language, 40)
      return { type: 'apply_series_shot_card', seriesId: text(raw.series_id, 160), episodeId: text(raw.episode_id, 160), shot, card,
               ...(cast.length ? { cast } : {}), ...(controls ? { controls } : {}), ...(assets ? { assets } : {}), ...(language ? { language } : {}),
               approve: raw.approve_take === true }
    },
    validate(action) { return CARD.test(action.card) ? [] : ['Say which card to put on the shot.'] },
    async prepare(action) { return action },
    async execute(action, context) { return context.adapters.seriesShots.applyCard(action, context.workspace) },
    correlate(_action, outcome) { return outcome.target },
    async track(_action, outcome) { return outcome },
    report: { targetKind: 'series_episode', successState: 'completed' },
    summarize(_action, outcome) { return outcome.message },
    presentation: { destination: 'series_lab', anchors: ['review', 'shots'], replay: 'atomic' },
  })
}
