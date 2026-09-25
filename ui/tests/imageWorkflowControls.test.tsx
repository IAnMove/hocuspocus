import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/', pretendToBeVisual: true })
Object.assign(globalThis, { window: dom.window, document: dom.window.document, localStorage: dom.window.localStorage,
  HTMLElement: dom.window.HTMLElement, IS_REACT_ACT_ENVIRONMENT: true })
const { render, cleanup, fireEvent, act } = await import('@testing-library/react')
const { useStore } = await import('../src/stores/useStore')
const { ImageStudioPanel } = await import('../src/components/Sidebar/ImageStudioPanel')
const { snapshotStudioImageIntent } = await import('../src/features/studio/prepareGeneration')
const { setStudioImageSource } = await import('../src/features/studio/imageInputActions')
const initial = useStore.getState(), originalFetch = globalThis.fetch
test.beforeEach(() => {
  globalThis.fetch = async () => new Response(JSON.stringify({ assets: [], outputs: [] }))
  useStore.setState({ ...initial, generationMode: 'image', imageStudioIntent: 'chooser', imageStudioDrafts: {}, imageRefs: [],
    params: { ...initial.params, model_type: 'qwen_image_layered_20B' }, activeWorkspace: 'audit' }, true)
})
test.afterEach(() => { cleanup(); useStore.setState(initial, true); globalThis.fetch = originalFetch })

test('batch controls count image/prompt pairs and keep settings in the edit draft', async () => {
  useStore.setState({ imageStudioIntent: 'edit', modelOptions: { image_source_support: true } as never,
    params: { ...initial.params, prompt: 'watercolor\n\noil painting', model_type: 'qwen_image_21' } })
  const { ImageBatchControls } = await import('../src/components/Sidebar/ImageBatchControls')
  const view = render(<ImageBatchControls />)
  fireEvent.click(view.getByRole('checkbox'))
  fireEvent.change(view.getByTestId('image-batch-files'), { target: { files: [
    new File(['one'], 'one.png', { type: 'image/png' }), new File(['two'], 'two.png', { type: 'image/png' }),
  ] } })
  assert.equal(useStore.getState().imageBatch?.sources.length, 2)
  fireEvent.change(view.getByRole('combobox'), { target: { value: 'lines' } })
  assert.match(view.getByRole('status').textContent || '', /4/)
  await act(async () => useStore.getState().setImageStudioIntent('new'))
  assert.equal(useStore.getState().imageBatch, undefined)
  await act(async () => useStore.getState().setImageStudioIntent('edit'))
  assert.equal(useStore.getState().imageBatch?.perLine, true)
  assert.equal(useStore.getState().imageBatch?.sources.length, 2)
  fireEvent.change(view.getByRole('combobox'), { target: { value: 'whole' } })
  assert.match(view.getByRole('status').textContent || '', /2/)
  fireEvent.click(view.getByRole('button', { name: 'Remove one.png', exact: true }))
  assert.equal(useStore.getState().imageBatch?.sources.length, 1)
  await act(async () => useStore.getState().resetImageStudio())
  assert.equal(useStore.getState().imageBatch, undefined)
})

test('Layered offers its source and layer count instead of an impossible text/reference workflow', async () => {
  useStore.setState({ modelOptions: { image_source_support: true, image_source_required: true,
    image_layer_count: { min: 1, max: 16, default: 4 }, image_outputs: true } as never })
  const view = render(<ImageStudioPanel />)
  assert.equal(view.queryByRole('button', { name: /New image/ }), null)
  assert.equal(view.queryByRole('button', { name: /References/ }), null)
  await act(async () => fireEvent.click(view.getByRole('button', { name: /Edit image/ })))
  assert.equal(view.container.querySelectorAll('input[type="file"]').length, 1)
  const layers = view.getByLabelText('Number of layers') as HTMLInputElement
  assert.equal(layers.value, '4')
  fireEvent.change(layers, { target: { value: '6' } })
  await act(async () => setStudioImageSource('/api/v1/uploads/layer-source.png'))
  const intent = snapshotStudioImageIntent(useStore.getState())
  assert.equal(intent.params.image_guide, '/api/v1/uploads/layer-source.png')
  assert.equal(intent.params.batch_size, 6)
  assert.equal(useStore.getState().outputCount, 1)
})

test('Qwen Edit Plus exposes source, mask, method and extra references in the same edit form', async () => {
  useStore.setState({ modelOptions: { image_source_support: true, inpaint_support: true, image_ref_inpaint: true,
    outpaint_support: true, image_conditioning_required: true,
    image_ref_choices: { choices: [['Subject', 'KI']] },
    image_edit_modes: { default: 1, choices: [['LoRA inpainting', 1], ['Masked denoising', 0], ['LanPaint', 3]] },
  } as never })
  useStore.getState().setImageStudioIntent('edit')
  useStore.getState().setParams({ image_guide: '/api/v1/uploads/source.png', image_mask: '/api/v1/uploads/mask.png',
    video_prompt_type: 'VAG', masking_strength: .6 })
  const view = render(<ImageStudioPanel />)
  await act(async () => {})
  assert.equal(view.container.querySelectorAll('input[type="file"]').length, 3)
  assert.ok(view.getByLabelText('Inpainting method'))
  assert.ok(view.getByLabelText(/Outpaint margins/))
  fireEvent.change(view.getByLabelText('Inpainting method'), { target: { value: '3' } })
  assert.equal(useStore.getState().params.model_mode, 3)
  await act(async () => useStore.getState().addImageRef(new File(['synthetic'], 'ref.png', { type: 'image/png' })))
  const intent = snapshotStudioImageIntent(useStore.getState())
  assert.equal(intent.params.image_mask, '/api/v1/uploads/mask.png')
  assert.equal(intent.imageRefs.length, 1)
})
