// The job card of an Edit-tab submission (Retake, Outpaint, Recast, Repaint) must be listed under the
// Edit tab ('avatars' gallery filter) while submitting, once queued, after the first status poll and
// when the submit fails. The placeholder carried no generation details, and the server reported
// generation_mode 'video' without edit_sub_mode, so the card was hidden everywhere on that tab.
import assert from 'node:assert/strict'
import test from 'node:test'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { window: dom.window, document: dom.window.document,
  localStorage: dom.window.localStorage, Event: dom.window.Event, CustomEvent: dom.window.CustomEvent })
window.matchMedia = (() => ({ matches: false })) as typeof window.matchMedia
const { useStore } = await import('../src/stores/useStore')
const { jobFitsGalleryFilter } = await import('../src/lib/galleryListQuery')
const { editJobGenerationDetails } = await import('../src/features/studio/editJobDetails')
const { DEFAULT_RECAST_MAPPING } = await import('../src/features/studio/store/studioEditSlice')

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })

function cards() {
  return useStore.getState().jobs.map(job => ({ status: job.status, edit: jobFitsGalleryFilter(job, 'avatars'),
    video: jobFitsGalleryFilter(job, 'videos'), details: job.generationDetails }))
}

async function withEdit(state: Record<string, unknown>, fetchImpl: typeof fetch, run: () => Promise<void>) {
  const before = useStore.getState(), beforeFetch = globalThis.fetch
  try {
    globalThis.fetch = fetchImpl
    useStore.setState({ generationMode: 'avatar', mediaFilter: 'avatars', jobs: [], activeWorkspace: 'edit-cards',
      editVideoPath: '/uploads/clip.mp4', editStartTime: 0.2, editEndTime: 1.4,
      params: { ...before.params, model_type: 'ltxv_13B', prompt: 'smile' },
      maybeRefreshGallery: async () => {}, ...state })
    await run()
  } finally {
    useStore.setState({ jobs: [] })       // stops the 2 s status poll (it exits when its job is gone)
    await new Promise(resolve => setTimeout(resolve, 2100))
    useStore.setState(before); globalThis.fetch = beforeFetch
  }
}

test('Retake: the card is on the Edit tab while submitting, queued, polled with the server details, and failed', async () => {
  let releasePost!: () => void
  const postGate = new Promise<void>(resolve => { releasePost = resolve })
  await withEdit({ editSubMode: 'retake' }, (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.includes('/retake') && init?.method === 'POST') { await postGate; return json({ job_id: 'job-cards' }) }
    // GET /api/v1/status/<id> of a Retake: services/kernel/jobs.py publishes generation_mode 'video' plus edit_sub_mode
    if (url.includes('job-cards')) return json({ status: 'running', progress: 10, step: 1, total_steps: 8, phase: 'Denoising',
      message: 'Generating...', output_files: [], error: null,
      generation_details: { model_type: 'ltxv_13B', model_name: 'LTX Video 0.9.8 13B', generation_mode: 'video', edit_sub_mode: 'retake', steps: 8 } })
    return json({})
  }) as typeof fetch, async () => {
    const run = useStore.getState().startGeneration()
    await new Promise(resolve => setTimeout(resolve, 10))
    const submitting = cards()
    releasePost(); await run
    const queued = cards()
    await new Promise(resolve => setTimeout(resolve, 2300))   // one status poll
    const polled = cards()
    assert.equal(submitting[0]?.edit, true, 'Submitting... card hidden on the Edit tab')
    assert.equal(queued[0]?.edit, true, 'Queued... card hidden on the Edit tab')
    assert.equal(polled[0]?.edit, true, 'running card (server generation_details) hidden on the Edit tab')
    assert.equal(polled[0]?.video, true, 'an edit is a video: the card also shows on the Video tab')
  })
})

const EDITS = [
  ['retake', { editSubMode: 'retake' }, '/retake'],
  ['outpaint', { editSubMode: 'outpaint', editVideoResolution: '832x480', outpaintAspect: '16:9', outpaintVideoBox: { x: 0.1, y: 0.3, w: 0.8, h: 0.4 } }, '/outpaint'],
  ['recast', { editSubMode: 'recast', editRecastMappings: [{ ...DEFAULT_RECAST_MAPPING, target: 'a woman', refPath: '/uploads/ref.png' }] }, '/recast'],
  ['restyle', { editSubMode: 'restyle', editRepaintFramePath: '/uploads/frame.png', editRepaintMappings: [] }, '/repaint'],
] as const

for (const [name, state, route] of EDITS) {
  test(`${name}: the submitting card and the failed-submit card are on the Edit tab`, async () => {
    let releasePost!: () => void
    const postGate = new Promise<void>(resolve => { releasePost = resolve })
    let posted = false
    await withEdit(state as Record<string, unknown>, (async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).includes(route) && init?.method === 'POST') { posted = true; await postGate; return json({ detail: 'SAM service not available' }, 503) }
      return json({})
    }) as typeof fetch, async () => {
      const run = useStore.getState().startGeneration()
      await new Promise(resolve => setTimeout(resolve, 10))
      const submitting = cards()
      releasePost(); await run
      const failed = cards()
      assert.equal(posted, true, `${name}: the submission never reached ${route}`)
      assert.equal(submitting[0]?.edit, true, `${name}: Submitting card hidden on the Edit tab`)
      assert.equal(failed[0]?.status, 'failed')
      assert.equal(failed[0]?.edit, true, `${name}: failed card hidden on the Edit tab`)
    })
  })
}

test('editJobGenerationDetails names the model and the edit', () => {
  const state = { params: { model_type: 'ltxv_13B' }, models: [{ model_type: 'ltxv_13B', name: 'LTX Video 0.9.8 13B' }], editSubMode: 'inpaint' }
  assert.deepEqual(editJobGenerationDetails(state as never),
    { model_type: 'ltxv_13B', model_name: 'LTX Video 0.9.8 13B', generation_mode: 'avatar', edit_sub_mode: 'inpaint' })
  assert.deepEqual(editJobGenerationDetails({ ...state, params: {}, models: [] } as never),
    { generation_mode: 'avatar', edit_sub_mode: 'inpaint' })
})
