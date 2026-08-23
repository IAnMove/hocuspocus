import assert from 'node:assert/strict'
import test from 'node:test'
import {
  clipIndexFromOutputParams,
  extractSingleClipStudioParams,
  isJoinedSequenceOutput,
  splitStudioClipPrompts,
} from '../src/features/studio/studioRestore.ts'

test('only joined multiclip filenames load as a sequence', () => {
  assert.equal(isJoinedSequenceOutput('minimax_h3_aa7b3e3f.mp4'), false)
  assert.equal(isJoinedSequenceOutput('minimax_h3_cc878b2c.mp4'), false)
  assert.equal(isJoinedSequenceOutput('minimax_h3_4f91a557_multiclip.mp4'), true)
})

test('does not split a structured H3 prompt on newlines', () => {
  const prompt = [
    'integrated_multimodal_description: [Shot 1] Plaza.',
    'Mario dice: <d>[Spanish] Vamos.</d>',
    '',
    'overall_soundscape: Empedrado.',
    '',
    'non_diegetic_music: N/A',
  ].join('\n')
  assert.deepEqual(splitStudioClipPrompts(prompt), [prompt])
})

test('splits Director clip-boundary prompts and stacked H3 shots', () => {
  assert.deepEqual(
    splitStudioClipPrompts('one\n---CLIP_BOUNDARY---\ntwo'),
    ['one', 'two'],
  )
  assert.deepEqual(
    splitStudioClipPrompts(
      'integrated_multimodal_description: [Shot 1] A.\n\noverall_soundscape: Quiet.\n\nnon_diegetic_music: N/A\nintegrated_multimodal_description: [Shot 1] B.\n\noverall_soundscape: Quiet.\n\nnon_diegetic_music: N/A',
    ).map(text => text.slice(0, 40)),
    [
      'integrated_multimodal_description: [Shot',
      'integrated_multimodal_description: [Shot',
    ],
  )
})

test('single-clip restore keeps one prompt, image and duration', () => {
  const extracted = extractSingleClipStudioParams({
    prompt: 'first\n---CLIP_BOUNDARY---\nsecond',
    image_start: ['a.png', 'b.png'],
    per_clip_frames: [124, 192],
    multi_clip_info: { index: 1, total: 2 },
    video_length: 345,
  })
  assert.equal(extracted.prompt, 'second')
  assert.equal(extracted.imageStart, 'b.png')
  assert.equal(extracted.videoLength, 192)
  assert.equal(extracted.imagePromptType, 'S')
  assert.equal(clipIndexFromOutputParams({ multi_clip_info: { index: 1 } }), 1)
})
