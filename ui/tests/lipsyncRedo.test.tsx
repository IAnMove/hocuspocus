import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { setUiLanguage } from '../src/i18n/index.ts'
import { AGENT_ACTION_TYPES } from '../src/features/agent/agentActionTypes.ts'
import { isExpensiveAction } from '../src/features/agent/agentContract.ts'
import { getCapability } from '../src/features/agent/capabilityRegistry.ts'
import { HOCUSPOCUS_AGENT_SYSTEM_PROMPT } from '../src/features/agent/agentKnowledge.ts'
import { InspectorMedia } from '../src/features/series/inspector/InspectorMedia.tsx'
import type { TakeEntry } from '../src/features/series/inspector/model.ts'
import type { SeriesProject, SeriesShot } from '../src/features/series/types.ts'
import { ProductionShotsPanel } from '../src/features/production-shots/ProductionShotsPanel.tsx'
import type { ShotView } from '../src/features/production-shots/types.ts'
import {
  confirmLipsyncDownload, interpretLipsyncReply, lipsyncRedoEnvelope, runLipsyncRedo,
} from '../src/features/lipsync-redo/request.ts'

Object.assign(globalThis, { React })

function view(): ShotView {
  return {
    workspace_id: 'film', production_id: 'clip1', project: null, title: 'Night bus', status: 'completed',
    format: 'music_video', sources: ['music'], limits: [], shot_count: 1, truncated: false,
    shots: [{
      id: 's1', order: 1, start: 0, end: 4, duration: 4, text: null, text_kind: null,
      takes: [
        { id: 'take-b.mp4', file: 'take-b.mp4', selected: true },
        { id: 'still.png', file: 'still.png', selected: false },
      ],
      selected_take_id: 'take-b.mp4', review: null, technical_status: null, scene: null, montage: null,
      provenance: { source: 'music' },
    }],
  }
}

test('the reply names a new take, a disk size, or a download that already started', () => {
  assert.deepEqual(lipsyncRedoEnvelope({ workspace: 'film', engine: 'infinitetalk', production_id: 'mv', shot: 'o05' }, 'job-1'), {
    operation: 'shot.lipsync.redo', version: 1, intent_id: 'job-1',
    input: { workspace: 'film', engine: 'infinitetalk', production_id: 'mv', shot: 'o05' },
  })
  assert.equal(interpretLipsyncReply(200, { result: { file: 'lipsync-o05.mp4', verdict: 'ok' } }).kind, 'done')
  const missing = interpretLipsyncReply(409, { detail: { code: 'model_unavailable', bytes: 12, model_type: 'longcat_avatar', message: 'missing' } })
  assert.equal(missing.kind, 'download')
  assert.equal(missing.bytes, 12)
  assert.equal(missing.modelType, 'longcat_avatar')
  assert.equal(interpretLipsyncReply(200, { result: { status: 'downloading', bytes: 12, model_type: 'infinitetalk' } }).kind, 'downloading')
  assert.equal(interpretLipsyncReply(422, { detail: { code: 'shot_locked', message: 'This shot is locked.' } }).message, 'This shot is locked.')
  assert.equal(interpretLipsyncReply(500, { detail: 'nope' }).message, 'nope')
})

test('a video take offers the lip redo and a still does not', async () => {
  await setUiLanguage('en')
  const html = renderToStaticMarkup(<ProductionShotsPanel view={view()} workspace="film" onClose={() => {}} />)
  assert.match(html, /Redo the lips/)
  assert.match(html, /data-action="lipsync-redo"/)
  assert.match(html, /data-action="lipsync-engine"/)
  assert.match(html, /infinitetalk/)
  assert.match(html, /longcat_avatar/)
  assert.equal(html.match(/data-action="lipsync-redo"/g)?.length, 1)
  await setUiLanguage('es')
  const spanish = renderToStaticMarkup(<ProductionShotsPanel view={view()} workspace="film" onClose={() => {}} />)
  assert.match(spanish, /Rehacer los labios/)
})

test('the series inspector shows the same control only when the shot has a take', async () => {
  await setUiLanguage('en')
  const series = { id: 'show', locations: [] } as unknown as SeriesProject
  const shot = { id: 'o05', productionMethod: 'generated_video' } as SeriesShot
  const takes = [{ url: '/v.mp4', thumbnail: '', number: 1, attempt: { id: 'a1' } }] as TakeEntry[]
  const withTake = renderToStaticMarkup(<InspectorMedia series={series} shot={shot} takes={takes} onSelect={() => {}} kits={null} workspace="film" episodeId="ep1" />)
  assert.match(withTake, /data-action="lipsync-redo"/)
  const planOnly = renderToStaticMarkup(<InspectorMedia series={series} shot={shot} takes={[]} onSelect={() => {}} kits={null} workspace="film" episodeId="ep1" />)
  assert.doesNotMatch(planOnly, /data-action="lipsync-redo"/)
  const noPlace = renderToStaticMarkup(<InspectorMedia series={series} shot={shot} takes={takes} onSelect={() => {}} kits={null} />)
  assert.doesNotMatch(noPlace, /data-action="lipsync-redo"/)
})

test('the Wizard calls shot.lipsync.redo and shows the disk size without downloading', async () => {
  assert.equal(AGENT_ACTION_TYPES.includes('lipsync_redo'), true)
  assert.equal(isExpensiveAction('lipsync_redo'), true)
  assert.match(HOCUSPOCUS_AGENT_SYSTEM_PROMPT, /lipsync_redo/)
  const capability = getCapability('lipsync_redo')!
  assert.equal(capability.resolve({ type: 'lipsync_redo', engine: 'infinitetalk', input: { shot: 'o05' } }), null)
  const action = capability.resolve({
    type: 'lipsync_redo', confirm: true, engine: 'longcat_avatar',
    input: { production_id: 'mv', shot: 'o05', extra: 'no' },
  })
  assert.equal(action?.engine, 'longcat_avatar')
  const sent: Array<{ url: string, body: Record<string, unknown>, headers?: Record<string, string> }> = []
  const previous = globalThis.fetch
  globalThis.fetch = (async (url: string, init?: { body?: string, headers?: Record<string, string> }) => {
    sent.push({ url: String(url), body: JSON.parse(init?.body || '{}'), headers: init?.headers })
    return { ok: false, status: 409, json: async () => ({ detail: { code: 'model_unavailable', bytes: 99, model_type: 'longcat_avatar', message: 'missing' } }) }
  }) as typeof fetch
  try {
    const { createDefaultApplicationAdapters } = await import('../src/features/agent/applicationAdapters.ts')
    const adapters = createDefaultApplicationAdapters()
    const outcome = await capability.execute(action!, { adapters, workspace: 'orcos-libres', generationContext: { actor: 'wizard', commandId: 'lip-1' } })
    assert.match(outcome.message, /99 bytes on disk/)
    assert.match(outcome.message, /longcat_avatar/)
    assert.equal(sent.length, 1)
    assert.equal(sent[0].headers?.['X-Hocus-UI-Surface'], 'wizard')
    assert.deepEqual(sent[0].body.input, {
      workspace: 'orcos-libres', engine: 'longcat_avatar', production_id: 'mv', shot: 'o05',
    })
    await assert.rejects(capability.execute({
      type: 'lipsync_redo', engine: 'infinitetalk', confirm: true, input: { workspace: 'other', clip: 'a.mp4' },
    }, { adapters, workspace: 'film' }), /active workspace/)
  } finally {
    globalThis.fetch = previous
  }
})

test('confirming the download uses the existing model download', async () => {
  const previous = globalThis.fetch
  const sent: string[] = []
  globalThis.fetch = (async (url: string, init?: { method?: string }) => {
    sent.push(`${init?.method || 'GET'} ${url}`)
    const download = String(url).includes('/download')
    return {
      ok: true, status: 200,
      json: async () => download
        ? { status: 'downloading', model_type: 'infinitetalk' }
        : { result: { file: 'lipsync-closeup-infinitetalk.mp4', verdict: 'ok' } },
    }
  }) as typeof fetch
  try {
    const posted = await runLipsyncRedo(
      { workspace: 'film', engine: 'infinitetalk', clip: 'closeup.mp4', audio: 'voice.wav' },
      (key, options) => `${key}:${JSON.stringify(options || {})}`,
    )
    assert.match(posted.note, /replies.lipsRedone/)
    await confirmLipsyncDownload('infinitetalk')
    assert.ok(sent.some(item => item.startsWith('POST ') && item.includes('/api/v1/models/infinitetalk/download')))
  } finally {
    globalThis.fetch = previous
  }
})
