import assert from 'node:assert/strict'
import test from 'node:test'
import { ACE_STEP_MUSIC_MODEL, normalizeStoryMusicModel, songWriteTarget } from '../src/features/stories/musicModel.ts'

test('new stories default to ACE-Step and keep MiniMax only when chosen', () => {
  assert.equal(normalizeStoryMusicModel(''), ACE_STEP_MUSIC_MODEL)
  assert.equal(normalizeStoryMusicModel('ace_step_v1_5_xl_sft_lm_4b'), ACE_STEP_MUSIC_MODEL)
  assert.equal(normalizeStoryMusicModel('music-3.0'), 'music-3.0')
  assert.equal(normalizeStoryMusicModel('music-2.6'), 'music-2.6')
  assert.equal(songWriteTarget(ACE_STEP_MUSIC_MODEL), 'ace-step')
  assert.equal(songWriteTarget('music-3.0'), 'minimax')
})
