import assert from 'node:assert/strict'
import test from 'node:test'
import { outputImageUrl, outputMediaUrl } from '../src/lib/storedImageFiles.ts'

test('listed gallery files pin the workspace so serve_file does not use the active folder', () => {
  assert.equal(outputMediaUrl('sunset.mp4', 'film'), '/api/v1/file/sunset.mp4?workspace=film')
  assert.equal(outputImageUrl('hero.png', 'ads'), '/api/v1/file/hero.png?workspace=ads')
})

test('the uploads view uses the uploads route instead of an invalid workspace query', () => {
  assert.equal(outputMediaUrl('clip.mp4', '__uploads__'), '/api/v1/uploads/clip.mp4')
  assert.equal(outputImageUrl('ref.png', '__uploads__'), '/api/v1/uploads/ref.png')
})
