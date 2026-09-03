import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import { createStoryProject } from '../src/features/stories/model.ts'
import {
  effectiveMusicCue,
  musicCandidateById,
  musicCueForCandidate,
} from '../src/features/stories/storyProductionController.ts'
import type { StoryMusicCandidate } from '../src/features/stories/types.ts'

function candidate(id: string, overrides: Partial<StoryMusicCandidate> = {}): StoryMusicCandidate {
  return {
    id,
    title: 'Theme song',
    displayName: 'Theme song · Español · v1',
    language: 'Español',
    version: 1,
    name: `${id}.wav`,
    source: `/outputs/${id}.wav`,
    prompt: 'Heavy metal anthem',
    lyrics: '[Verse]\nWe keep the servers alive',
    provider: 'local',
    model: 'ace_step_v1_5_xl_sft_lm_4b',
    durationSeconds: 90,
    createdAt: '2026-09-03T00:00:00.000Z',
    ...overrides,
  }
}

test('music production resolves cue and candidate by durable IDs', () => {
  const project = createStoryProject('music_video')
  const nested = candidate('song-nested')
  const global = candidate('song-global')
  project.music.cues = [{
    id: 'cue-story',
    kind: 'story',
    targetId: project.id,
    title: 'Story theme',
    purpose: 'Carry the story',
    referenceSong: '',
    brief: 'A server-room anthem',
    style: 'Heavy metal',
    lyrics: nested.lyrics,
    lyriaPrompt: '',
    instrumental: false,
    durationSeconds: 90,
    candidates: [nested],
    selectedCandidateId: nested.id,
  }]
  project.music.candidates = [global]

  assert.equal(musicCueForCandidate(project, nested.id)?.id, 'cue-story')
  assert.equal(musicCandidateById(project, nested.id)?.id, nested.id)
  assert.equal(musicCandidateById(project, global.id)?.id, global.id)
  assert.equal(musicCandidateById(project, 'missing-song'), undefined)
})

test('effective music cue preserves the selected song context for legacy candidates', () => {
  const project = createStoryProject('music_video')
  project.music.brief = 'A heroic uptime story'
  project.music.style = '80s heavy metal'
  const selected = candidate('song-legacy', { lyrics: '', durationSeconds: 42 })

  const cue = effectiveMusicCue(project, undefined, selected)

  assert.equal(cue.id, 'story-song')
  assert.equal(cue.targetId, project.id)
  assert.equal(cue.style, selected.prompt)
  assert.equal(cue.lyrics, project.music.lyrics)
  assert.equal(cue.instrumental, true)
  assert.equal(cue.durationSeconds, 42)
  assert.deepEqual(cue.candidates.map(item => item.id), [selected.id])
})

test('Story Lab delegates Director handoff orchestration to the production controller', () => {
  const panel = readFileSync(new URL('../src/features/stories/StoryLabPanel.tsx', import.meta.url), 'utf8')
  const controller = readFileSync(new URL('../src/features/stories/storyProductionController.ts', import.meta.url), 'utf8')

  assert.match(panel, /loadStoryFilmProduction/)
  assert.match(panel, /loadStoryMusicVideoProduction/)
  assert.doesNotMatch(panel, /directorAdoptAndAnalyze/)
  assert.doesNotMatch(panel, /buildMusicVideoAdaptation/)
  assert.match(controller, /export async function loadStoryFilmProduction/)
  assert.match(controller, /export async function loadStoryMusicVideoProduction/)
})
