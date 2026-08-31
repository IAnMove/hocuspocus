import assert from 'node:assert/strict'
import test from 'node:test'

import { getPlayableFileUrl } from '../src/api/client.ts'
import { resolveStoryMusicSelection } from '../src/features/stories/musicVideoSelection.ts'

const candidate = {
  id: 'song-v2',
  displayName: 'El Himno del Sysadmin · Español · v2',
  title: 'El Himno del Sysadmin',
  name: 'sysadmin-v2.wav',
  source: '/home/user/hocuspocus/outputs/sysadmin-v2.wav',
}

const cue = {
  id: 'cue-main',
  kind: 'story',
  title: 'El Himno del Sysadmin',
  candidates: [candidate],
  selectedCandidateId: candidate.id,
}

const project = {
  id: 'story-2',
  title: 'El Himno del Sysadmin 2',
  music: {
    cues: [cue],
    candidates: [],
    selectedCandidateId: candidate.id,
  },
}

test('a rendered version accidentally supplied as cue_title resolves its owning cue', () => {
  const selection = resolveStoryMusicSelection(project, '', candidate.displayName)
  assert.equal(selection.cue.id, cue.id)
  assert.equal(selection.candidate.id, candidate.id)
})

test('a resumed pre-render label resolves the only persisted cue and candidate', () => {
  const selection = resolveStoryMusicSelection(
    project,
    'El Himno del Sysadmin · Español',
    'El Himno del Sysadmin · Español',
  )
  assert.equal(selection.cue.id, cue.id)
  assert.equal(selection.candidate.id, candidate.id)
})

test('absolute generator paths become playable workspace URLs', () => {
  assert.equal(
    getPlayableFileUrl(candidate.source, candidate.name, 'default'),
    '/api/v1/file/sysadmin-v2.wav?workspace=default',
  )
  assert.equal(
    getPlayableFileUrl('/api/v1/file/already.wav?workspace=default', 'already.wav', 'default'),
    '/api/v1/file/already.wav?workspace=default',
  )
})
