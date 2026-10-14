import { useSyncExternalStore } from 'react'
import { cancelJob } from '../../api/client'
import { fetchCharacterKitLibrary, rigFlatCharacter, saveCharacterKit, type FlatRigResult } from '../../api/characters'
import { createCharacterKit, type CharacterKit, type CharacterKitAsset } from '../../lib/characterKit'
import type { CharacterStyle } from '../../lib/characterStyles'
import type { CustomCharacterVoice } from '../../lib/characterVoice'
import type { SpokenLanguage } from '../../lib/speechLanguage'
import { randomUuid } from '../../lib/uuid'
import { CANDIDATE_COUNT, candidateCount, generateKeyedCandidates, keyCandidate, type CandidateDependencies, type KeyedCandidate } from './characterCandidates'

export type RigShown = Pick<FlatRigResult, 'review' | 'unwipedPoses' | 'warnings'>
export type Step = 'options' | 'keying' | 'rig' | 'pose' | 'addPose'
/** The options of the character, or the options of a new pose of it. */
export type Lane = 'candidates' | 'poseCandidates'

/** Why an option has no picture, when the reason is not an error of the server: the view says it in the person's language. */
export const INTERRUPTED = 'interrupted'
export const CANCELLED = 'cancelled'

/** What the person has done in the creator. It outlives the screen (a tab change must not stop or forget the work) and is kept in the browser. */
export type CreatorDraft = {
  styleId: string; model: string
  name: string; description: string; count: number
  /** A failed rig keeps the saved draft; trying another option updates that same character. */
  draftId: string
  candidates: KeyedCandidate[]; picked?: string
  kit?: CharacterKit; rig?: RigShown
  pose: string; poseCandidates: KeyedCandidate[]; pickedPose?: string
}
/** What the creator tells the person after a step, as the translation key the view says it with. */
export type CreatorMessage = 'styleCreator.pick' | 'styleCreator.noneReady' | 'styleCreator.ready' | 'styleCreator.poseAdded' | 'imageCreator.cancelled'
type Run = { busy: '' | Step; error: string; message: '' | CreatorMessage }
export type CreatorView = CreatorDraft & Run
/** What a run needs from the screen: the style and model chosen, and what to do once pictures exist. */
export type CreatorContext = { style: CharacterStyle; model: string; onPictures?: () => void }

const storageKey = (workspace: string) => `hocuspocus.characterCreator.v1:${workspace}`

export const poseId = (description: string) => description.toLowerCase().normalize('NFKD').replace(/[^a-z0-9]+/g, '-')
  .replace(/^-+|-+$/g, '').slice(0, 40) || `pose-${randomUuid().slice(0, 6)}`

function keyedAsset(id: string, name: string, source: string, workspace: string, prompt: string, model: string): CharacterKitAsset {
  return { id, name, source, kind: 'image', alphaStatus: 'transparent', reviewState: 'approved', workspace, prompt, model }
}

function fresh(carry?: Partial<Pick<CreatorDraft, 'styleId' | 'model' | 'count' | 'name' | 'description'>>): CreatorDraft {
  return { styleId: carry?.styleId ?? '', model: carry?.model ?? '', name: carry?.name ?? '', description: carry?.description ?? '',
    count: candidateCount(carry?.count), draftId: `character-${randomUuid()}`, candidates: [], pose: '', poseCandidates: [] }
}

const STATUSES = new Set(['generating', 'drawn', 'keying', 'ready', 'failed'])
const isCandidate = (item: unknown): item is KeyedCandidate => Boolean(item) && typeof item === 'object'
  && typeof (item as KeyedCandidate).id === 'string' && typeof (item as KeyedCandidate).seed === 'number' && STATUSES.has((item as KeyedCandidate).status)
/** A picture that was being drawn without an image job to follow again was lost with the page. */
const settled = (items: unknown): KeyedCandidate[] => (Array.isArray(items) ? items.filter(isCandidate) : [])
  .map(item => item.status === 'generating' && !item.jobId ? { ...item, status: 'failed' as const, error: INTERRUPTED } : item)
const text = (value: unknown, limit: number) => typeof value === 'string' ? value.slice(0, limit) : ''
const object = <T>(value: unknown): T | undefined => value && typeof value === 'object' && !Array.isArray(value) ? value as T : undefined

function readDraft(workspace: string): CreatorDraft {
  try {
    if (typeof localStorage === 'undefined') return fresh()
    const stored = JSON.parse(localStorage.getItem(storageKey(workspace)) ?? 'null') as { version?: number; draft?: Record<string, unknown> } | null
    const saved = stored?.version === 1 ? stored.draft : undefined
    if (!saved) return fresh()
    const candidates = settled(saved.candidates), poseCandidates = settled(saved.poseCandidates)
    const has = (items: KeyedCandidate[], id: unknown) => typeof id === 'string' && items.some(item => item.id === id) ? id : undefined
    return { ...fresh({ styleId: text(saved.styleId, 80), model: text(saved.model, 120), count: Number(saved.count) || CANDIDATE_COUNT,
      name: text(saved.name, 80), description: text(saved.description, 2000) }),
    draftId: text(saved.draftId, 160) || `character-${randomUuid()}`,
    candidates, picked: has(candidates, saved.picked),
    kit: object<CharacterKit>(saved.kit), rig: object<RigShown>(saved.rig),
    pose: text(saved.pose, 200), poseCandidates, pickedPose: has(poseCandidates, saved.pickedPose) }
  } catch { return fresh() }
}

/**
 * One workspace's Character Creator: its draft, the run in progress and the work that keeps going when the screen is left.
 * The screen only reads it and calls it. Leaving the tab never stops a run; only Cancel does. A reloaded page reads the draft
 * back and follows the image jobs that were still drawing.
 */
export class CharacterCreatorSession {
  private draft: CreatorDraft
  private run: Run = { busy: '', error: '', message: '' }
  private view: CreatorView
  private listeners = new Set<() => void>()
  private operation: { controller: AbortController; jobs: string[] } | null = null
  private resumed = false

  readonly workspace: string
  private readonly dependencies: Partial<CandidateDependencies>

  constructor(workspace: string, dependencies: Partial<CandidateDependencies> = {}) {
    this.workspace = workspace
    this.dependencies = dependencies
    this.draft = readDraft(workspace)
    this.view = { ...this.draft, ...this.run }
  }

  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener) } }
  snapshot = () => this.view

  private publish() {
    this.view = { ...this.draft, ...this.run }
    this.listeners.forEach(listener => listener())
  }
  private save() {
    try { if (typeof localStorage !== 'undefined') localStorage.setItem(storageKey(this.workspace), JSON.stringify({ version: 1, draft: this.draft })) } catch { /* private mode or full: the draft lives on in memory */ }
  }
  private commit(patch?: Partial<CreatorDraft>, run?: Partial<Run>) {
    if (patch) { this.draft = { ...this.draft, ...patch }; this.save() }
    if (run) this.run = { ...this.run, ...run }
    this.publish()
  }
  private pickedIn = (lane: Lane) => lane === 'candidates' ? this.draft.picked : this.draft.pickedPose
  private put(lane: Lane, items: KeyedCandidate[]) { this.commit(lane === 'candidates' ? { candidates: items } : { poseCandidates: items }) }
  private patch(lane: Lane, id: string, change: Partial<KeyedCandidate>) {
    this.put(lane, this.draft[lane].map(item => item.id === id ? { ...item, ...change } : item))
  }

  /** The description, name, count or pose text being typed. */
  edit(patch: Partial<Pick<CreatorDraft, 'name' | 'description' | 'count' | 'pose' | 'model'>>) {
    this.commit({ ...patch, ...(patch.count !== undefined ? { count: candidateCount(patch.count) } : {}) })
  }
  /** Another style starts over (its options are not this style's), keeping what was typed. */
  setStyle(styleId: string) {
    if (styleId === this.draft.styleId) return
    this.cancel()
    this.resumed = false
    this.draft = fresh({ ...this.draft, styleId }); this.save()
    this.run = { busy: '', error: '', message: '' }; this.publish()
  }
  /** A new character: the options, the saved one and its poses are let go (the pictures stay in the workspace). */
  reset() {
    this.cancel()
    this.draft = fresh({ styleId: this.draft.styleId, model: this.draft.model, count: this.draft.count }); this.save()
    this.run = { busy: '', error: '', message: '' }; this.publish()
  }

  private async execute(step: Step, task: (signal: AbortSignal) => Promise<void>) {
    if (this.operation) return
    const controller = new AbortController(); this.operation = { controller, jobs: [] }
    this.commit(undefined, { busy: step, error: '', message: '' })
    try { await task(controller.signal) }
    catch (cause) { if (!controller.signal.aborted) this.commit(undefined, { error: (cause as Error).message }) }
    finally { if (this.operation?.controller === controller) { this.operation = null; this.commit(undefined, { busy: '' }) } }
  }

  /** Stops the run and the image jobs it started. The pictures already drawn stay. */
  cancel() {
    const operation = this.operation
    if (!operation) return
    this.operation = null; operation.controller.abort()
    const jobs = new Set(operation.jobs)
    const stop = (items: KeyedCandidate[]) => items.map((item): KeyedCandidate => {
      if (item.status === 'generating') { if (item.jobId) jobs.add(item.jobId); return { ...item, status: 'failed', error: CANCELLED } }
      return item.status === 'keying' ? { ...item, status: 'drawn' } : item
    })
    jobs.forEach(id => void cancelJob(id).catch(() => {}))
    this.commit({ candidates: stop(this.draft.candidates), poseCandidates: stop(this.draft.poseCandidates) }, { busy: '', message: 'imageCreator.cancelled' })
  }

  private async generate(lane: Lane, context: CreatorContext, signal: AbortSignal, existing?: KeyedCandidate[]) {
    const poses = lane === 'poseCandidates'
    const identity = poses ? this.draft.kit?.identityReference?.source || this.draft.kit?.base?.source : undefined
    const found = await generateKeyedCandidates({
      workspace: this.workspace, style: context.style, kind: poses ? 'pose' : 'character', description: (poses ? this.draft.pose : this.draft.description).trim(),
      model: context.model, ...(identity ? { references: [identity] } : {}), count: this.draft.count, ...(existing ? { existing } : {}), signal,
      picked: () => this.pickedIn(lane), onUpdate: items => this.put(lane, items), onJobSubmitted: id => { this.operation?.jobs.push(id) },
    }, this.dependencies)
    context.onPictures?.()
    const usable = found.some(item => item.status === 'drawn' || item.status === 'keying' || item.status === 'ready')
    this.commit(undefined, { message: !usable ? 'styleCreator.noneReady' : this.pickedIn(lane) ? '' : 'styleCreator.pick' })
  }

  createOptions(context: CreatorContext) {
    return this.execute('options', async signal => {
      this.commit({ candidates: [], picked: undefined, kit: undefined, rig: undefined })
      await this.generate('candidates', context, signal)
    })
  }
  createPoseOptions(context: CreatorContext) {
    return this.execute('pose', async signal => {
      if (!this.draft.kit) return
      this.commit({ poseCandidates: [], pickedPose: undefined })
      await this.generate('poseCandidates', context, signal)
    })
  }

  /** Picks an option that has its picture. One that still has its background gets it removed now (unless a run is doing that). */
  pick(lane: Lane, id: string) {
    const item = this.draft[lane].find(candidate => candidate.id === id)
    if (!item || item.status === 'generating' || item.status === 'failed') return
    this.commit(lane === 'candidates' ? { picked: id } : { pickedPose: id })
    if (item.status === 'drawn' && !this.operation) {
      void this.execute('keying', signal => keyCandidate({ workspace: this.workspace, candidate: item, signal, onUpdate: change => this.patch(lane, id, change) }, this.dependencies))
    }
  }

  saveAndRig(context: CreatorContext) {
    return this.execute('rig', async signal => {
      const { style } = context
      const chosen = this.draft.candidates.find(candidate => candidate.id === this.draft.picked)
      if (!chosen?.keyed) return
      const description = this.draft.description.trim()
      const draft = createCharacterKit(this.draft.name.trim()); draft.id = this.draft.draftId
      draft.style = style.kitStyle as CharacterKit['style']
      draft.base = keyedAsset(`${draft.id}-base`, draft.name, chosen.keyed, this.workspace, description, context.model)
      draft.identityReference = { ...draft.base, id: `${draft.id}-identity` }
      draft.lookNotes = description
      draft.provenance = [{ method: 'character-style-create', style: style.id, source: chosen.raw, keyed: chosen.keyed, model: context.model, seed: chosen.seed }]
      const library = await fetchCharacterKitLibrary(this.workspace); signal.throwIfAborted()
      const saved = await saveCharacterKit(this.workspace, library, draft); signal.throwIfAborted()
      const rigged = await rigFlatCharacter({ workspace: this.workspace, kitId: draft.id, baseRevision: saved.revision, style: style.rig }); signal.throwIfAborted()
      this.commit({ kit: rigged.character, rig: rigged }, { message: 'styleCreator.ready' })
    })
  }

  addPose(context: CreatorContext) {
    return this.execute('addPose', async signal => {
      const { kit } = this.draft
      const chosen = this.draft.poseCandidates.find(candidate => candidate.id === this.draft.pickedPose)
      if (!kit || !chosen?.keyed) return
      const label = this.draft.pose.trim(), id = poseId(this.draft.pose)
      const library = await fetchCharacterKitLibrary(this.workspace); signal.throwIfAborted()
      const current = library.kits[kit.id] ?? kit
      const next: CharacterKit = { ...current, poses: { ...current.poses,
        [id]: keyedAsset(`${kit.id}-${id}`.slice(0, 120), `${kit.name} ${label}`.slice(0, 240), chosen.keyed, this.workspace, label, context.model) } }
      const saved = await saveCharacterKit(this.workspace, library, next); signal.throwIfAborted()
      const rigged = await rigFlatCharacter({ workspace: this.workspace, kitId: kit.id, baseRevision: saved.revision, style: context.style.rig, poses: ['base', id] })
      signal.throwIfAborted()
      this.commit({ kit: rigged.character, rig: rigged, pose: '', poseCandidates: [], pickedPose: undefined }, { message: 'styleCreator.poseAdded' })
    })
  }

  /** The first designed voice also becomes the default voice for every other language. */
  async saveVoice(language: SpokenLanguage, voice: CustomCharacterVoice) {
    const { kit } = this.draft
    if (!kit) return
    const library = await fetchCharacterKitLibrary(this.workspace)
    const current = library.kits[kit.id] ?? kit
    const saved = await saveCharacterKit(this.workspace, library, { ...current, voice: current.voice ?? voice,
      voicesByLanguage: { ...current.voicesByLanguage, [language]: voice } })
    this.commit({ kit: saved.kits[kit.id] })
  }

  /** Once per page: reads the saved character again and follows the pictures that were still being drawn or keyed. */
  resume(context: CreatorContext) {
    if (this.resumed) return
    this.resumed = true
    if (this.draft.kit) void this.refreshKit()
    const lane = (['candidates', 'poseCandidates'] as const).find(name => this.draft[name].some(item => item.status === 'generating' || item.status === 'keying'))
    if (!lane || this.operation) return
    const existing = this.draft[lane].map((item): KeyedCandidate => item.status === 'keying' ? { ...item, status: 'drawn' } : item)
    void this.execute(lane === 'candidates' ? 'options' : 'pose', signal => this.generate(lane, context, signal, existing))
  }

  /** The saved character may have been changed or deleted since the draft was written. */
  private async refreshKit() {
    try {
      const library = await fetchCharacterKitLibrary(this.workspace)
      const kit = this.draft.kit && library.kits[this.draft.kit.id]
      if (kit) this.commit({ kit })
      else this.commit({ kit: undefined, rig: undefined, poseCandidates: [], pickedPose: undefined })
    } catch { /* offline: the draft shows what was saved last */ }
  }
}

const sessions = new Map<string, CharacterCreatorSession>()
export function creatorSession(workspace: string): CharacterCreatorSession {
  let session = sessions.get(workspace)
  if (!session) { session = new CharacterCreatorSession(workspace); sessions.set(workspace, session) }
  return session
}
/** Tests: a session whose pictures and keying come from the test. */
export const registerCreatorSession = (session: CharacterCreatorSession) => { sessions.set(session.workspace, session) }
/** Tests: forget every session, so a draft does not leak from one test into the next. */
export function forgetCreatorSessions() {
  sessions.forEach(session => session.cancel())
  sessions.clear()
}
export function useCreatorSession(workspace: string): { session: CharacterCreatorSession; view: CreatorView } {
  const session = creatorSession(workspace)
  return { session, view: useSyncExternalStore(session.subscribe, session.snapshot) }
}
