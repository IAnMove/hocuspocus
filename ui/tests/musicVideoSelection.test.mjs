import assert from 'node:assert/strict'
import test from 'node:test'

import { getPlayableFileUrl, getServerMediaReference } from '../src/api/client.ts'
import { effectiveStoryMusicCue, resolveStoryMusicSelection } from '../src/features/stories/musicVideoSelection.ts'

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

test('an explicit unknown song never falls back to the only candidate', () => {
  assert.throws(
    () => resolveStoryMusicSelection(project, 'Canción que no existe', cue.title),
    /No existe la canción/,
  )
})

test('an explicit unknown cue never falls back to the only cue', () => {
  assert.throws(
    () => resolveStoryMusicSelection(project, '', 'Cue antiguo que no existe'),
    /No existe el cue/,
  )
})

test('a canonical candidate ID wins over a stale display label', () => {
  const selection = resolveStoryMusicSelection(
    project,
    'Nombre antiguo',
    cue.title,
    cue.id,
    candidate.id,
  )
  assert.equal(selection.candidate.id, candidate.id)
})

test('a candidate ID disambiguates several versions sharing one cue title', () => {
  const first = {
    ...candidate,
    id: 'song-v1',
    displayName: 'El Himno del Sysadmin · Español · v1',
    name: 'sysadmin-v1.wav',
    source: '/home/user/hocuspocus/outputs/sysadmin-v1.wav',
  }
  const twoVersions = {
    ...project,
    music: {
      ...project.music,
      cues: [{ ...cue, candidates: [first, candidate], selectedCandidateId: first.id }],
      selectedCandidateId: first.id,
    },
  }
  const selection = resolveStoryMusicSelection(twoVersions, '', cue.title, cue.id, candidate.id)
  assert.equal(selection.candidate.id, candidate.id)
  assert.equal(selection.cue.id, cue.id)
  assert.throws(
    () => resolveStoryMusicSelection(twoVersions, '', cue.title, cue.id),
    /usa su candidate_id exacto/,
  )
})

test('an explicit cue ID cannot select a candidate from another cue', () => {
  const otherCandidate = {
    ...candidate,
    id: 'song-other',
    displayName: 'Otra canción · Español · v1',
    name: 'other.wav',
  }
  const otherCue = {
    ...cue,
    id: 'cue-other',
    title: 'Otra canción',
    candidates: [otherCandidate],
    selectedCandidateId: otherCandidate.id,
  }
  assert.throws(
    () => resolveStoryMusicSelection(
      { ...project, music: { ...project.music, cues: [cue, otherCue] } },
      '',
      '',
      cue.id,
      otherCandidate.id,
    ),
    /No existe la versión de canción con ID/,
  )
})

test('an explicit cue ID wins over a title belonging to another cue', () => {
  const otherCue = { ...cue, id: 'cue-other', title: 'Otra canción' }
  const selection = resolveStoryMusicSelection(
    { ...project, music: { ...project.music, cues: [cue, otherCue] } },
    '',
    otherCue.title,
    cue.id,
  )
  assert.equal(selection.cue?.id, cue.id)
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

test('pending candidates cannot be staged as a videoclip', () => {
  const pending = {
    ...candidate,
    id: 'song-pending',
    source: '',
    status: 'pending',
  }
  assert.throws(
    () => resolveStoryMusicSelection(
      {
        ...project,
        music: {
          ...project.music,
          cues: [{ ...cue, candidates: [pending], selectedCandidateId: pending.id }],
          selectedCandidateId: pending.id,
        },
      },
      '',
      cue.title,
      cue.id,
      pending.id,
    ),
    /todavía se está generando/,
  )
})

test('v1 and v2 remain distinct song identities', () => {
  const first = {
    ...candidate,
    id: 'song-v1',
    displayName: 'El Himno del Sysadmin · Español · v1',
    version: 1,
    name: 'sysadmin-v1.wav',
    source: '/home/user/hocuspocus/outputs/sysadmin-v1.wav',
  }
  const second = {
    ...candidate,
    id: 'song-v2',
    displayName: 'El Himno del Sysadmin · Español · v2',
    version: 2,
  }
  const twoVersions = {
    ...project,
    music: {
      ...project.music,
      cues: [{ ...cue, candidates: [first, second], selectedCandidateId: second.id }],
      selectedCandidateId: second.id,
    },
  }
  const v1 = resolveStoryMusicSelection(twoVersions, '', cue.title, cue.id, first.id)
  const v2 = resolveStoryMusicSelection(twoVersions, '', cue.title, cue.id, second.id)
  assert.equal(v1.candidate.id, 'song-v1')
  assert.equal(v2.candidate.id, 'song-v2')
  assert.notEqual(v1.candidate.id, v2.candidate.id)
})

test('workspace B cannot adopt a candidate that only exists in workspace A', () => {
  const projectB = {
    id: 'story-b',
    title: 'Otro workspace',
    music: {
      cues: [{
        ...cue,
        id: 'cue-b',
        title: 'Otra pista',
        candidates: [{
          id: 'song-b',
          displayName: 'Otra pista · Español · v1',
          title: 'Otra pista',
          name: 'b.wav',
          source: '/home/user/hocuspocus/outputs/b.wav',
        }],
        selectedCandidateId: 'song-b',
      }],
      candidates: [],
      selectedCandidateId: 'song-b',
    },
  }
  assert.throws(
    () => resolveStoryMusicSelection(projectB, '', '', 'cue-b', candidate.id),
    /No existe la versión de canción con ID/,
  )
})

test('synthetic story-song cue is refused unless the caller passed that exact id', () => {
  assert.throws(
    () => effectiveStoryMusicCue(project, undefined, candidate),
    /no tiene un cue persistido/,
  )
  const synthetic = effectiveStoryMusicCue(project, undefined, candidate, 'story-song')
  assert.equal(synthetic.id, 'story-song')
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
