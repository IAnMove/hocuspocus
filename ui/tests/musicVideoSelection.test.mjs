import assert from 'node:assert/strict'
import test from 'node:test'

import { getPlayableFileUrl, getServerMediaReference } from '../src/api/client.ts'
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

test('media the server already holds is handed over by name, not by bytes', () => {
  // An absolute generator path is a file in the workspace folder: the backend
  // resolves the bare name against that root, so Director never has to pull
  // the track through the browser to hand it back.
  assert.deepEqual(
    getServerMediaReference(candidate.source, candidate.name, 'default'),
    { audio_path: 'sysadmin-v2.wav', workspace: 'default' },
  )
  // The workspace written into the URL wins over the active one — the song
  // is where it was saved, not where the user is standing now.
  assert.deepEqual(
    getServerMediaReference('/api/v1/file/already.wav?workspace=other', 'already.wav', 'default'),
    { audio_path: 'already.wav', workspace: 'other' },
  )
  // Generated names carry spaces, commas, brackets and accents.
  assert.deepEqual(
    getServerMediaReference('/api/v1/file/caf%C3%A9%20%5BIntro%5D.wav?workspace=default', 'x.wav', 'default'),
    { audio_path: 'café [Intro].wav', workspace: 'default' },
  )
  // Uploads keep their subfolder: the permitted root is uploads/, not
  // uploads/audio/, and they belong to no workspace.
  assert.deepEqual(
    getServerMediaReference('/api/v1/uploads/audio/9f2.wav', '9f2.wav', 'default'),
    { audio_path: 'audio/9f2.wav' },
  )
  // Only in the browser, or on another host: these still need the download.
  assert.equal(getServerMediaReference('blob:http://x/9f2', 'song.wav', 'default'), null)
  assert.equal(getServerMediaReference('https://cdn.example/song.wav', 'song.wav', 'default'), null)
})
