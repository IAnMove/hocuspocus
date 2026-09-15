import assert from 'node:assert/strict'
import { readdirSync, readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import React from 'react'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
Object.assign(globalThis, {
  window: dom.window,
  document: dom.window.document,
  HTMLElement: dom.window.HTMLElement,
  localStorage: dom.window.localStorage,
  MutationObserver: dom.window.MutationObserver,
})
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

const { render, cleanup } = await import('@testing-library/react')
const {
  detectVariant,
  detectCapability,
  resolveModelCatalog,
  catalogVramGb,
  catalogRequirementKey,
} = await import('../src/lib/modelCatalog.ts')
const { ModelCatalogInfo } = await import('../src/components/Sidebar/ModelCatalogInfo.tsx')

test('classifies distilled, quantized, compact and edit variants from the model id', () => {
  assert.equal(detectVariant({ model_type: 'ltx2_22B_distilled_1_1', architecture: 'ltx2_22B', name: 'LTX-2.3 Distilled' }), 'distilled')
  assert.equal(detectVariant({ model_type: 'qwen_image_edit_20B_gguf_q4_k_m', architecture: 'qwen_image_edit_20B' }), 'gguf')
  assert.equal(detectVariant({ model_type: 'ltx2_22B_nvfp4', architecture: 'ltx2_22B' }), 'nvfp4')
  assert.equal(detectVariant({ model_type: 't2v_1.3B', architecture: 't2v_1.3B', name: 'Wan2.1 Text2video 1.3B' }), 'small')
  assert.equal(detectVariant({ model_type: 'lucy_edit_fastwan', architecture: 'lucy_edit' }), 'fast')
  assert.equal(detectVariant({ model_type: 'flux_dev_kontext', architecture: 'flux_dev_kontext' }), 'edit')
  assert.equal(detectVariant({ model_type: 'viggle_animate', name: 'Viggle-Animate Pruned 20B' }), 'pruned')
  assert.equal(detectVariant({ model_type: 'unirig', tool_only: true }), 'tool')
  assert.equal(detectVariant({ model_type: 'minimax_h3_fused_turbo' }), 'fast')
})

test('explains what each model does instead of listing only the name', () => {
  assert.equal(detectCapability({
    model_type: 'ltx2_22B', architecture: 'ltx2_22B', generates_audio: true, supports_end_frame: true, is_i2v: true, is_t2v: true,
  }), 'videoAudioFirstLast')
  assert.equal(detectCapability({
    model_type: 't2v_1.3B', architecture: 't2v_1.3B', is_t2v: true, is_i2v: false,
  }), 'videoT2v')
  assert.equal(detectCapability({
    model_type: 'flux2_klein_9b', architecture: 'flux2_klein_9b', family: 'flux2',
  }), 'image')
  assert.equal(detectCapability({
    model_type: 'qwen_image_edit_20B', architecture: 'qwen_image_edit_20B', family: 'qwen',
  }), 'imageEdit')
  assert.equal(detectCapability({
    model_type: 'ace_step_v1_5_xl', architecture: 'ace_step_v1_5_xl', family: 'tts',
  }), 'music')
  assert.equal(detectCapability({
    model_type: 'hunyuan3d-2mv-turbo', family: 'hunyuan3d', architecture: 'hunyuan3d', is_i2v: true, is_t2v: false,
  }), 'model3dMultiview')
  assert.equal(detectCapability({
    model_type: 'vace_14B', architecture: 'vace_14B', is_i2v: true, is_t2v: true,
  }), 'videoControl')
})

test('typical minima prefer API numbers and stay conservative for GGUF', () => {
  const wan = resolveModelCatalog({ model_type: 't2v_1.3B', architecture: 't2v_1.3B' })
  assert.equal(wan.requirements.vram_gb, 6)
  assert.equal(wan.fromApi, false)

  const ltx = resolveModelCatalog({ model_type: 'ltx2_22B', architecture: 'ltx2_22B' })
  assert.equal(ltx.requirements.vram_gb, 16)
  assert.equal(ltx.requirements.comfortable_vram_gb, 24)

  const gguf = resolveModelCatalog({
    model_type: 'qwen_image_edit_20B_gguf_q4_k_m', architecture: 'qwen_image_edit_20B',
  })
  assert.equal(gguf.variant, 'gguf')
  assert.equal(gguf.requirements.vram_gb, 8)

  const music = resolveModelCatalog({
    model_type: 'minimax_music3',
    architecture: 'minimax_music3',
    resource_requirements: { vram_gb: 24, storage_gb: 28, ram_gb: 32 },
  })
  assert.equal(music.fromApi, true)
  assert.equal(music.requirements.vram_gb, 24)
  assert.equal(music.requirements.storage_gb, 28)

  const hunyuanMini = resolveModelCatalog({
    model_type: 'hunyuan3d-2mini-turbo', architecture: 'hunyuan3d',
  })
  assert.equal(hunyuanMini.requirements.vram_gb, 6)
  assert.equal(hunyuanMini.variant, 'fast')
})

test('H3 keeps measured memory and does not invent a VRAM badge', () => {
  assert.equal(catalogVramGb({ model_type: 'minimax_h3' }), undefined)
  assert.equal(catalogVramGb({ model_type: 'ltx2_22B', architecture: 'ltx2_22B' }), 16)
})

test('non-H3 models show a variant line, a capability line and expandable minima', () => {
  try {
    const view = render(<ModelCatalogInfo model={{
      model_type: 'ltx2_22B_distilled_1_1',
      name: 'LTX-2.3 Distilled 1.1 22B',
      architecture: 'ltx2_22B',
      description: 'LTX-2.3 generates video up to 20s with an audio soundtrack.',
      generates_audio: true,
      supports_end_frame: true,
      is_i2v: true,
      is_t2v: true,
    }} />)
    const text = view.container.textContent ?? ''
    assert.match(text, /Distilled · Accelerated variant/)
    assert.match(text, /Video and native audio from a first frame/)
    assert.match(text, /Minimum requirements/)
    assert.match(text, /VRAM ~16 GB/)
    assert.match(text, /not a measured peak/)
    assert.doesNotMatch(text, /20s with an audio soundtrack/)
  } finally { cleanup() }
})

test('every downloadable default has mapped minima, not the generic fallback', () => {
  const defaultsDir = join(dirname(fileURLToPath(import.meta.url)), '../../app/defaults')
  const files = readdirSync(defaultsDir).filter(name => name.endsWith('.json'))
  assert.ok(files.length >= 200, `expected the full defaults catalog, got ${files.length}`)
  const missing: string[] = []
  for (const file of files) {
    const parsed = JSON.parse(readFileSync(join(defaultsDir, file), 'utf8')) as {
      model?: { architecture?: string }
    }
    const modelType = file.replace(/\.json$/, '')
    const architecture = parsed.model?.architecture || ''
    if (catalogRequirementKey(modelType, architecture) === 'fallback') {
      missing.push(`${modelType} (${architecture})`)
    }
  }
  assert.deepEqual(missing, [])
})

test('Hunyuan3D, UniRig and MMAudio extras are mapped', () => {
  const extras: Array<[string, string]> = [
    ['hunyuan3d-2mini-turbo', 'hunyuan3d'],
    ['hunyuan3d-2.1', 'hunyuan3d'],
    ['trellis2', 'hunyuan3d'],
    ['pixal3d', 'hunyuan3d'],
    ['unirig', 'unirig'],
    ['mmaudio_v2', 'mmaudio'],
  ]
  for (const [modelType, architecture] of extras) {
    assert.notEqual(catalogRequirementKey(modelType, architecture), 'fallback', modelType)
  }
})

test('H3 catalog presentation is unchanged when rendered through ModelCatalogInfo', () => {
  try {
    const view = render(<ModelCatalogInfo model={{ model_type: 'minimax_h3_fused_turbo' }} />)
    const text = view.container.textContent ?? ''
    assert.match(text, /Fused/)
    assert.match(text, /4 steps|4 pasos/)
    assert.match(text, /Memory measured|Memoria medida/)
    assert.doesNotMatch(text, /Minimum requirements|Requisitos mínimos/)
  } finally { cleanup() }
})
