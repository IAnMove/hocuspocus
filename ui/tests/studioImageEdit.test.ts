import assert from 'node:assert/strict'
import test from 'node:test'
import { mergeVideoPromptLetters, studioImageEditCapabilities } from '../src/lib/studioImageEdit.ts'

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

test('keeps identity letters when adding or clearing a local-edit mask', () => {
  assert.equal(mergeVideoPromptLetters('KI', 'VAG'), 'KIVAG')
  assert.equal(mergeVideoPromptLetters('KIVAG', '', 'VAG'), 'KI')
  assert.equal(mergeVideoPromptLetters('KI', 'V', ''), 'KIV')
  assert.equal(mergeVideoPromptLetters('KIVAG', 'V', 'AG'), 'KIV')
})
