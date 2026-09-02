import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'

function installDom() {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
  Object.assign(globalThis, {
    window: dom.window,
    document: dom.window.document,
    HTMLElement: dom.window.HTMLElement,
    HTMLButtonElement: dom.window.HTMLButtonElement,
    HTMLSelectElement: dom.window.HTMLSelectElement,
    Event: dom.window.Event,
  })
  Object.defineProperty(globalThis, 'navigator', {
    configurable: true,
    value: dom.window.navigator,
  })
  return dom
}

installDom()

test('alternative song capabilities parse exact videoclip and audio names', async () => {
  const { parseAgentTurn } = await import('../src/features/agent/agentActions.ts')
  const attach = parseAgentTurn(JSON.stringify({
    reply: 'Añado la versión en inglés.',
    actions: [{
      type: 'attach_videoclip_alternative_song',
      videoclip_name: 'sysadmin_de_medianoche_h3_legacy_t2v_unique.mp4',
      audio_output_name: 'sysadmin-en.mp3',
      ignored: true,
    }],
  }))
  assert.equal(attach.actions[0].type, 'attach_videoclip_alternative_song')
  assert.equal(attach.actions[0].videoclipName, 'sysadmin_de_medianoche_h3_legacy_t2v_unique.mp4')
  assert.equal(attach.actions[0].audioOutputName, 'sysadmin-en.mp3')

  const mount = parseAgentTurn(JSON.stringify({
    reply: 'Montaré el videoclip con esa canción.',
    actions: [{
      type: 'mount_videoclip_alternative_song',
      videoclip_name: 'sysadmin_de_medianoche_h3_legacy_t2v_unique.mp4',
      audio_output_name: 'sysadmin-en.mp3',
      confirm: true,
    }],
  }))
  assert.equal(mount.actions[0].type, 'mount_videoclip_alternative_song')
  assert.equal(mount.actions[0].confirm, true)

  const denied = parseAgentTurn(JSON.stringify({
    reply: 'No monto sin confirmar.',
    actions: [{
      type: 'mount_videoclip_alternative_song',
      videoclip_name: 'sysadmin_de_medianoche_h3_legacy_t2v_unique.mp4',
      audio_output_name: 'sysadmin-en.mp3',
    }],
  }))
  assert.equal(denied.actions.length, 0)
})

test('alternative songs dialog lists attached songs and the remount action', async () => {
  const { render, screen, cleanup } = await import('@testing-library/react')
  const { AlternativeSongsDialog } = await import('../src/components/MainContent/AlternativeSongsDialog.tsx')
  const { useStore } = await import('../src/stores/useStore.ts')
  useStore.setState({ activeWorkspace: 'default', loadOutputs: async () => {}, setMediaFilter: () => {} })
  const previousFetch = globalThis.fetch
  globalThis.fetch = async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.includes('/alternative-songs') && !url.includes('/mount')) {
      return new Response(JSON.stringify({
        parent: 'clip.mp4',
        duration_seconds: 10,
        source_clip_count: 3,
        adaptation: 'random_extras',
        songs: [{
          id: 'song-abc', audio_name: 'en.mp3', duration_seconds: 12,
          created_at: 1, status: 'attached', mounted_output: null, job_id: null,
          extra_clip_count: 0, planned_clip_count: 0,
        }],
      }), { headers: { 'content-type': 'application/json' } })
    }
    return new Response(JSON.stringify({ outputs: [{ name: 'en.mp3', type: 'audio' }] }), {
      headers: { 'content-type': 'application/json' },
    })
  }

  try {
    render(<AlternativeSongsDialog name="clip.mp4" onClose={() => {}} />)
    await screen.findByRole('dialog', { name: /alternative songs/i })
    await screen.findByRole('button', { name: 'Mount' })
    assert.ok(screen.getAllByText('en.mp3').length >= 1)
  } finally {
    cleanup()
    globalThis.fetch = previousFetch
  }
})
