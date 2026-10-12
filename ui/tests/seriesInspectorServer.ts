import { JSDOM } from 'jsdom'
import { jsonResponse } from './seriesReviewFixtures'
import type { SeriesEpisodeReview, SeriesProject, SeriesReviewChange, SeriesShot } from '../src/features/series/types'

/** A browser for the Validation tab and its shot inspector. */
export function installDom() {
  const dom = new JSDOM('<!doctype html><html lang="en"><body /></html>', { url: 'http://localhost/' })
  Object.assign(globalThis, { window: dom.window, document: dom.window.document, localStorage: dom.window.localStorage, sessionStorage: dom.window.sessionStorage,
    HTMLElement: dom.window.HTMLElement, HTMLSelectElement: dom.window.HTMLSelectElement, HTMLInputElement: dom.window.HTMLInputElement,
    Event: dom.window.Event, CustomEvent: dom.window.CustomEvent, KeyboardEvent: dom.window.KeyboardEvent, MutationObserver: dom.window.MutationObserver,
    ResizeObserver: class { observe() {} disconnect() {} } })
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
  dom.window.HTMLMediaElement.prototype.pause = () => {}
  dom.window.HTMLMediaElement.prototype.load = () => {}
  dom.window.HTMLMediaElement.prototype.play = () => Promise.resolve()
  return dom
}

export type Call = { method: string; path: string; body?: Record<string, unknown> }

const LINE_KEYS = ['emotion', 'delivery', 'pauseBefore', 'voiceRoom'] as const

/** The shot as series.shot.get reads it (the parts the inspector shows). */
export function scriptOf(shot: SeriesShot) {
  const layout = shot.layout2d || {}
  const lines = shot.dialogueBeats.filter(beat => beat.text.trim()).map(beat => ({ who: beat.characterId, spanish: beat.text,
    ...Object.fromEntries(LINE_KEYS.filter(key => (beat as Record<string, unknown>)[key]).map(key => [key, (beat as Record<string, unknown>)[key]])) }))
  return { scene: shot.sceneId, location: shot.locationId, ...Object.fromEntries(Object.entries(layout).filter(([key]) => key !== 'card' && key !== 'music')),
    ...(lines.length ? { lines } : { duration: shot.durationSeconds }), ...(shot.scene3d ? { scene3d: shot.scene3d, kind: '3d' } : {}),
    ...(shot.foley ? { foley: shot.foley } : {}), ...(layout.music ? { music: layout.music } : {}) }
}

/**
 * A server double for Series Lab's Validation tab: the review, the server render, the shot view and edit, the line
 * voices and their jobs, the 3D editor round trip and the pickers. Edits are applied to its own copy of the series.
 */
export function installServer(t: { after: (fn: () => void) => void }, project: SeriesProject, options: { kits?: unknown; editorDocument?: unknown } = {}) {
  const calls: Call[] = []
  const series = structuredClone(project)
  const episode = series.episodesById.ep1
  const review: SeriesEpisodeReview = structuredClone(episode.review || { mode: 'direct', shots: {} })
  const recorded = new Set<string>()
  let revision = series.revision, noteCount = 0, jobCount = 0
  const jobs = new Map<string, Record<string, unknown>>()
  const original = globalThis.fetch
  t.after(() => { globalThis.fetch = original })
  const findShot = (ref: string) => episode.shots.find(item => item.id === ref || String(item.order) === ref)
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input), path = url.replace(/^.*\/api\/v1/, '').split('?')[0]
    const body = init?.body ? JSON.parse(String(init.body)) : undefined
    const method = init?.method ?? 'GET'
    calls.push({ method, path, body })
    if (path === '/series/native-render/recovery') return jsonResponse({ jobs: [] })
    if (path.endsWith('/native-render')) return jsonResponse({ jobId: 'native-9', seriesId: series.id, episodeId: 'ep1', current: 0, total: 1, status: 'queued',
      mode: review.mode, waiting: [], items: (body?.shotIds as string[] || ['s1']).map(shotId => ({ shotId, stage: 'voices', status: 'queued' })) })
    if (path === '/character-kits/library') return jsonResponse(options.kits || { version: 1, revision: 1, kits: {} })
    if (path.endsWith('/shot-files')) return jsonResponse({ kind: 'audio', files: ['sfx-boom.wav', 'mus-tema.wav'] })
    if (path.endsWith('/review')) {
      const change = body as SeriesReviewChange
      if (change.mode) review.mode = change.mode
      const noteIds: Record<string, string> = {}
      for (const item of change.shots || []) {
        const entry = review.shots[item.shotId] ??= { plan: 'pending', preview: 'pending', notes: [] }
        if (item.plan) entry.plan = item.plan
        if (item.preview) { entry.preview = item.preview; if (entry.plan !== 'approved' && item.preview === 'approved') entry.plan = 'approved' }
        if (item.note) {
          const id = item.note.id || `note_${++noteCount}`
          entry.notes = entry.notes.filter(note => note.id !== id)
          if (item.note.text) entry.notes.push({ id, at: '2026-10-06T10:00:00Z', stage: item.note.stage || 'plan', text: item.note.text, by: 'user' })
          noteIds[item.shotId] = id
        }
      }
      revision += 1
      return jsonResponse({ revision, episodeId: 'ep1', episodeUpdatedAt: `2026-10-06T10:00:0${revision % 10}Z`, review: structuredClone(review), noteIds })
    }
    const voiceJob = path.match(/^\/series\/voice-jobs\/(.+)$/)
    if (voiceJob) {
      const job = jobs.get(voiceJob[1])!
      job.status = 'completed'
      recorded.add(String(job.beatId))
      return jsonResponse({ ...job, result: { filename: `ln-ep1-${job.beatId}-key.wav`, url: `/api/v1/file/ln-ep1-${job.beatId}-key.wav?workspace=plus-ultra` } })
    }
    const shotRoute = path.match(/^\/series\/[^/]+\/episodes\/ep1\/shots\/([^/]+)(\/.*)?$/)
    if (shotRoute && shotRoute[1] === 'edit' && method === 'POST') {
      const target = findShot(String(body?.shot))!
      const changes = (body?.changes || {}) as Record<string, unknown>
      for (const [key, value] of Object.entries(changes)) {
        if (key === 'lines') {
          target.dialogueBeats = ((value as Array<Record<string, string>>) || []).map((line, index) => ({ id: `${target.id}_b${index}`, characterId: line.who,
            text: line.spanish || '', emotion: line.emotion || '', delivery: line.delivery || '' }))
        } else if (key === 'scene3d') target.scene3d = value as SeriesShot['scene3d']
        else if (key === 'foley') target.foley = value as SeriesShot['foley']
        else {
          const layout = { ...(target.layout2d || {}) } as Record<string, unknown>
          if (value === null) delete layout[key]; else layout[key] = value
          target.layout2d = layout
        }
      }
      delete target.approvedAttemptId
      revision += 1
      return jsonResponse({ shotId: target.id, number: target.order, changed: Object.keys(changes), approvalReset: true, missingLines: {}, revision,
        shot: { shotId: target.id, number: target.order, productionMethod: target.productionMethod, takes: [], script: scriptOf(target) },
        ...(body?.stored ? { stored: { episodeId: 'ep1', episodeUpdatedAt: '2026-10-06T11:00:00Z', shot: structuredClone(target), review: structuredClone(review) } } : {}) })
    }
    if (shotRoute) {
      const target = findShot(decodeURIComponent(shotRoute[1]))
      if (!target) return jsonResponse({ detail: { code: 'shot_not_found', message: 'no such shot' } }, 404)
      const rest = shotRoute[2] || ''
      if (rest === '/voices' && method === 'GET') {
        const lines = target.dialogueBeats.filter(beat => beat.text.trim()).map((beat, index) => ({ beatId: beat.id, number: index + 1, characterId: beat.characterId,
          text: beat.text, voice: true, key: 'key', filename: `ln-ep1-${beat.id}-key.wav`, recorded: recorded.has(beat.id),
          ...(recorded.has(beat.id) ? { url: `/api/v1/file/ln-ep1-${beat.id}-key.wav?workspace=plus-ultra`, recordedAt: 1, newerThanTake: true } : {}) }))
        return jsonResponse({ shotId: target.id, language: 'spanish', lines, recording: [] })
      }
      if (rest === '/voices' && method === 'POST') {
        const beat = target.dialogueBeats.find(item => item.id === body?.line) || target.dialogueBeats[Number(body?.line) - 1]
        const job = { jobId: `voice-${++jobCount}`, shotId: target.id, beatId: beat.id, status: 'queued', retake: body?.retake === true }
        jobs.set(job.jobId, job)
        return jsonResponse(job)
      }
      if (rest === '/scene3d/editor') return jsonResponse({ shotId: target.id, sceneId: 'w3d-1', revision: 2, source: { template: target.scene3d?.template },
        duration: target.durationSeconds, document: options.editorDocument || { version: 1, slots: [] } })
      if (rest === '/scene3d/from-editor') return jsonResponse({ shotId: target.id, file: 'mp-es-ep1-plan-0a.world3d.scene.json', removedObjects: [],
        scene3d: { ...target.scene3d, template: undefined, scene: 'mp-es-ep1-plan-0a.world3d.scene.json' } })
      return jsonResponse({ shotId: target.id, number: target.order, productionMethod: target.productionMethod, takes: [], script: scriptOf(target) })
    }
    return jsonResponse({ outputs: [], total: 0 })
  }) as typeof fetch
  const posts = (suffix: string) => calls.filter(call => call.method === 'POST' && call.path.endsWith(suffix)).map(call => call.body)
  return { calls, posts, series }
}
