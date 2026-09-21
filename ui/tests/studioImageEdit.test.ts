import assert from 'node:assert/strict'
import test from 'node:test'
import { concreteImageResolution, snapImageResolution } from '../src/lib/imageResolution.ts'
import { IMAGE_STUDIO_INTENTS } from '../src/features/studio/imageStudioIntent.ts'
import { mergeVideoPromptLetters, studioImageEditCapabilities } from '../src/lib/studioImageEdit.ts'

test('lists the four Studio image intents', () => {
  assert.deepEqual(IMAGE_STUDIO_INTENTS.map(item => item.id), ['new', 'edit', 'character', 'loop'])
})

test('unlocks 2.1 image-generation tools from model options', () => {
  const locked = studioImageEditCapabilities({
    image_ref_choices: null,
    inpaint_support: false,
    outpaint_support: false,
    native_rgba: false,
  } as never)
  assert.equal(locked, null)

  const open = studioImageEditCapabilities({
    image_ref_choices: { choices: [['Subject', 'KI'], ['People', 'I']] },
    max_image_refs: 10,
    inpaint_support: true,
    image_ref_inpaint: true,
    outpaint_support: true,
    native_rgba: true,
    resolution_presets: { '1080p': { label: '2K', values: { '1:1': '2048x2048' } } },
  } as never)
  assert.deepEqual(open, {
    refs: true,
    maxRefs: 10,
    inpaint: true,
    outpaint: true,
    rgba: true,
    twoK: true,
  })
})

test('materializeLocalEditFields uploads every media token before command submit', async () => {
  const urls = globalThis.URL as typeof URL & { createObjectURL?: (file: Blob) => string; revokeObjectURL?: (url: string) => void }
  urls.createObjectURL ??= () => 'blob:test-fields'
  urls.revokeObjectURL ??= () => undefined
  const { rememberLocalImage, materializeLocalEditFields } = await import('../src/lib/localEditImages.ts')
  const originalFetch = globalThis.fetch
  globalThis.fetch = (async () => ({
    ok: true,
    json: async () => ({ filename: 'fields.png', url: '/api/v1/uploads/fields.png', path: '/tmp/fields.png' }),
  })) as typeof fetch
  try {
    const token = rememberLocalImage(new File(['xyz'], 'fields.png', { type: 'image/png' }))
    const params: Record<string, unknown> = { image_guide: token, image_refs: [token] }
    await materializeLocalEditFields(params, ['image_guide', 'image_refs', 'image_mask'])
    assert.equal(params.image_guide, '/api/v1/uploads/fields.png')
    assert.deepEqual(params.image_refs, ['/api/v1/uploads/fields.png'])
    assert.equal(params.image_mask, undefined)
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('turns browser-local edit tokens into upload URLs', async () => {
  const urls = globalThis.URL as typeof URL & { createObjectURL?: (file: Blob) => string; revokeObjectURL?: (url: string) => void }
  urls.createObjectURL ??= () => 'blob:test'
  urls.revokeObjectURL ??= () => undefined
  const { rememberLocalImage, materializeLocalEditImage, studioMediaUrl } = await import('../src/lib/localEditImages.ts')
  assert.equal(
    studioMediaUrl('http://192.168.1.87:42010/api/v1/uploads/photo.png'),
    '/api/v1/uploads/photo.png',
  )
  const originalFetch = globalThis.fetch
  globalThis.fetch = (async () => ({
    ok: true,
    json: async () => ({ filename: 'kept.png', url: '/api/v1/uploads/kept.png', path: '/tmp/kept.png' }),
  })) as typeof fetch
  try {
    const token = rememberLocalImage(new File(['abc'], 'from-disk.png', { type: 'image/png' }))
    assert.match(token, /^local-edit:\d+$/)
    assert.equal(await materializeLocalEditImage(token), '/api/v1/uploads/kept.png')
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('turns Auto into a pixel canvas for image commands', () => {
  assert.equal(concreteImageResolution('auto', 'qwen_image_21'), '2048x2048')
  assert.equal(concreteImageResolution('auto_1080p', 'qwen_image_21'), '2048x2048')
  assert.equal(concreteImageResolution('auto', 'flux'), '1024x1024')
  assert.equal(concreteImageResolution('1921x1080'), '1920x1080')
  assert.equal(snapImageResolution(3000, 2000, 2048), '2048x1368')
})

test('keeps identity letters when adding or clearing a local-edit mask', () => {
  assert.equal(mergeVideoPromptLetters('KI', 'VAG'), 'KIVAG')
  assert.equal(mergeVideoPromptLetters('KIVAG', '', 'VAG'), 'KI')
  assert.equal(mergeVideoPromptLetters('KI', 'V', ''), 'KIV')
  assert.equal(mergeVideoPromptLetters('KIVAG', 'V', 'AG'), 'KIV')
})
