// Extend and Blend outputs cannot be restored yet: Load Settings lands on Frames with no source
// clip (the sidecar's image_mode is already rewritten to 0 and nothing reads video_source/_blend_*),
// so a reroll silently submitted a plain text-to-video, and a Blend reroll one with a deleted temp
// end frame. Until the restore exists, the pencil and reroll buttons are disabled for those outputs.
// Full restore (image_mode 3/4, continue video, blend clips, no temp-frame fetch): see VF_c.REPORT.md follow-ups.
import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<!doctype html><html lang="en"><body></body></html>', { url: 'http://localhost/' })
class ObserverStub { observe() {} disconnect() {} }
Object.assign(globalThis, {
  window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement,
  Event: dom.window.Event, MouseEvent: dom.window.MouseEvent, MutationObserver: dom.window.MutationObserver,
  ResizeObserver: ObserverStub, IntersectionObserver: ObserverStub, React,
})
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
window.matchMedia = (() => ({ matches: false, addEventListener() {}, removeEventListener() {} })) as unknown as typeof window.matchMedia

const LTX = 'ltx2_22B_distilled_1_1'
// simulated_video_dffcd527.meta.json: an Extend produced through POST /api/v1/generate
const EXTEND = { model_type: LTX, generation_mode: 'video', prompt: 'Extend and then it leaps', image_mode: 0, image_prompt_type: 'V',
  video_prompt_type: 'T', video_source: '/uploads/1b06bc70b2c341b9aa63f00fc78f6ae7.mp4', video_length: 97, seed: 4242 }
// simulated_video_7cb9234f.meta.json: a Blend produced through POST /api/v1/blend
const BLEND = { model_type: LTX, generation_mode: 'video', prompt: 'Blend whip pan', image_mode: 0, image_prompt_type: 'VE',
  video_source: '/tmp/blend_lhr00jdy/motion_prefix.mp4', image_end: '/tmp/blend_lhr00jdy/b_overlap_end.png',
  _blend_mode: 'overlap', _blend_clip_a: '/uploads/clip.mp4', _blend_clip_b: '/uploads/clip.mp4', _blend_overlap_sec: 1, video_length: 97 }
const TEXT_TO_VIDEO = { model_type: LTX, generation_mode: 'video', prompt: 'A street', image_mode: 0, image_prompt_type: '', video_length: 97 }
const IMAGE_TO_VIDEO = { ...TEXT_TO_VIDEO, image_prompt_type: 'SE', image_start: '/uploads/a.png', image_end: '/uploads/b.png' }
const RETAKE = { model_type: LTX, generation_mode: 'video', edit_sub_mode: 'retake', image_prompt_type: 'V', video_source: '/uploads/clip.mp4' }

const video = { name: 'clip.mp4', url: '/api/v1/file/clip.mp4', type: 'video' as const, mode: 'video' as const,
  favorite: false, size: 1, created_at: 1 }

const { isExtendOrBlendOutput } = await import('../src/features/studio/studioRestore.ts')
const { ensureUiI18n } = await import('../src/i18n/index.ts')
const RESTORE_TITLE = 'Load settings'
const REROLL_TITLE = 'Re-generate with same settings'
const BLOCKED_TITLE = () => ensureUiI18n().t('activity:extendBlendRestoreUnavailable')

test('Extend and Blend sidecars are recognised; plain, image-to-video and edit sidecars are not', () => {
  assert.equal(isExtendOrBlendOutput(EXTEND), true)
  assert.equal(isExtendOrBlendOutput(BLEND), true)
  assert.equal(isExtendOrBlendOutput({ ...TEXT_TO_VIDEO, _blend_mode: 'cut' }), true)
  assert.equal(isExtendOrBlendOutput(TEXT_TO_VIDEO), false)
  assert.equal(isExtendOrBlendOutput(IMAGE_TO_VIDEO), false)
  assert.equal(isExtendOrBlendOutput({ ...TEXT_TO_VIDEO, image_prompt_type: 'V' }), false, 'a V flag without a source clip is not an Extend')
  assert.equal(isExtendOrBlendOutput(RETAKE), false)
  assert.equal(isExtendOrBlendOutput(null), false)
  assert.equal(isExtendOrBlendOutput(undefined), false)
})

async function renderActionBar(params: Record<string, unknown>) {
  const { render } = await import('@testing-library/react')
  const { OutputActionBar } = await import('../src/components/MainContent/OutputActionBar.tsx')
  ensureUiI18n().changeLanguage('en')
  return render(<OutputActionBar file={video} index={0} params={params} />)
}

for (const [label, params] of [['Extend', EXTEND], ['Blend', BLEND]] as const) {
  test(`gallery card: pencil and reroll are disabled for a ${label} output`, async () => {
    const { cleanup } = await import('@testing-library/react')
    const view = await renderActionBar(params)
    try {
      const blocked = view.getAllByTitle(BLOCKED_TITLE()) as HTMLButtonElement[]
      assert.equal(blocked.length, 2, 'pencil + reroll')
      assert.deepEqual(blocked.map(button => button.disabled), [true, true])
      assert.equal(view.queryByTitle(REROLL_TITLE), null)
    } finally { cleanup() }
  })
}

test('gallery card: pencil and reroll stay enabled for a plain text-to-video output', async () => {
  const { cleanup } = await import('@testing-library/react')
  const view = await renderActionBar(TEXT_TO_VIDEO)
  try {
    assert.equal((view.getByTitle(RESTORE_TITLE) as HTMLButtonElement).disabled, false)
    assert.equal((view.getByTitle(REROLL_TITLE) as HTMLButtonElement).disabled, false)
  } finally { cleanup() }
})

async function renderInfoBar(params: Record<string, unknown>) {
  const { render } = await import('@testing-library/react')
  const { VideoInfoBar } = await import('../src/components/MainContent/VideoInfoBar.tsx')
  const { useStore } = await import('../src/stores/useStore.ts')
  const outputs = [video]
  useStore.setState({ filteredOutputs: () => outputs, selectedOutput: 0, metadataLoading: false,
    selectedOutputMeta: { params } as never })
  ensureUiI18n().changeLanguage('en')
  return render(<VideoInfoBar />)
}

for (const [label, params] of [['Extend', EXTEND], ['Blend', BLEND]] as const) {
  test(`info bar: pencil and reroll are disabled for a ${label} output`, async () => {
    const { cleanup } = await import('@testing-library/react')
    const view = await renderInfoBar(params)
    try {
      const blocked = view.getAllByTitle(BLOCKED_TITLE()) as HTMLButtonElement[]
      assert.equal(blocked.length, 2, 'pencil + reroll')
      assert.deepEqual(blocked.map(button => button.disabled), [true, true])
    } finally { cleanup() }
  })
}

test('info bar: pencil and reroll stay enabled for a plain text-to-video output', async () => {
  const { cleanup } = await import('@testing-library/react')
  const view = await renderInfoBar(TEXT_TO_VIDEO)
  try {
    assert.equal((view.getByTitle('Load settings') as HTMLButtonElement).disabled, false)
    assert.equal((view.getByTitle(REROLL_TITLE) as HTMLButtonElement).disabled, false)
  } finally { cleanup() }
})
