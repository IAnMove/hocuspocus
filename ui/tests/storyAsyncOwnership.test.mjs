import assert from 'node:assert/strict'
import test from 'node:test'

test('late async results update their source Story after navigating A → B', async () => {
  const { useStoryStore, createStoryProject } = await import('../src/features/stories/store.ts')
  const first = createStoryProject()
  first.id = 'story-a'
  first.title = 'A'
  const second = createStoryProject()
  second.id = 'story-b'
  second.title = 'B'
  useStoryStore.setState({
    project: first,
    projects: { [first.id]: first, [second.id]: second },
    activeProjectOperations: {},
  })

  const sourceProjectId = useStoryStore.getState().project.id
  useStoryStore.getState().beginProjectOperation(sourceProjectId)
  useStoryStore.getState().openProject(second.id)
  let release
  const deferred = new Promise(resolve => { release = resolve })
  const operation = deferred.then(() => {
    useStoryStore.getState().updateProjectById(sourceProjectId, project => ({
      ...project,
      title: 'A completed',
    }))
    useStoryStore.getState().endProjectOperation(sourceProjectId)
  })
  release()
  await operation

  const state = useStoryStore.getState()
  assert.equal(state.project.id, second.id)
  assert.equal(state.projects[first.id].title, 'A completed')
  assert.equal(state.projects[second.id].title, 'B')
})

test('duplicating a Story remaps every nested identity and active work blocks destructive actions', async () => {
  const { useStoryStore, createStoryProject } = await import('../src/features/stories/store.ts')
  const source = createStoryProject()
  source.id = 'story-source'
  source.title = 'Source'
  const character = source.characters[0] = {
    id: 'character-source', name: 'Hero', role: '', age: '', pronouns: '', personality: '', desire: '', need: '',
    flaw: '', conflict: '', arc: '', voice: '', appearance: '', wardrobe: '', visualPrompt: '', negativePrompt: '',
    referenceAssetIds: ['asset-source'], primaryReferenceAssetId: 'asset-source', approval: 'approved',
  }
  source.world.locations.push({ id: 'location-source', name: 'Home', purpose: '', description: '', visualPrompt: '', negativePrompt: '', referenceAssetIds: ['asset-source'] })
  source.characters.push({ ...character, id: 'character-side', name: 'Side' })
  source.assets['asset-source'] = {
    id: 'asset-source', name: 'Hero', source: '/hero.png', prompt: '', provider: 'upload', createdAt: new Date().toISOString(), approval: 'approved',
  }
  source.relationships.push({ id: 'relationship-source', fromCharacterId: character.id, toCharacterId: 'character-side', label: '', dynamic: 'allies', evolution: '' })
  source.beats.push({ id: 'beat-source', stage: '', title: 'Beat', summary: '', goal: '', conflict: '', turn: '' })
  const sharedCandidate = { id: 'song-source', name: 'song', source: '/song.mp3', prompt: '', lyrics: '', provider: 'local', model: '', durationSeconds: 1, createdAt: new Date().toISOString() }
  source.music.candidates.push(sharedCandidate)
  source.music.selectedCandidateId = sharedCandidate.id
  source.music.cues.push({
    id: 'cue-source', kind: 'character', targetId: character.id, title: 'Cue', purpose: '', referenceSong: '', brief: '', style: '', lyrics: '', lyriaPrompt: '', instrumental: true, durationSeconds: 20,
    candidates: [{ ...sharedCandidate }], selectedCandidateId: sharedCandidate.id,
  })
  useStoryStore.setState({ project: source, projects: { [source.id]: source }, activeProjectOperations: {} })

  useStoryStore.getState().beginProjectOperation(source.id)
  useStoryStore.getState().duplicateProject(source.id)
  assert.equal(Object.keys(useStoryStore.getState().projects).length, 1)
  useStoryStore.getState().deleteProject(source.id)
  assert.equal(useStoryStore.getState().projects[source.id], source)
  useStoryStore.getState().endProjectOperation(source.id)

  useStoryStore.getState().duplicateProject(source.id)
  const duplicate = useStoryStore.getState().project
  assert.notEqual(duplicate.id, source.id)
  assert.notEqual(duplicate.characters[0].id, source.characters[0].id)
  assert.notEqual(duplicate.world.locations[0].id, source.world.locations[0].id)
  assert.notEqual(duplicate.beats[0].id, source.beats[0].id)
  assert.notEqual(Object.keys(duplicate.assets)[0], Object.keys(source.assets)[0])
  assert.notEqual(duplicate.relationships[0].id, source.relationships[0].id)
  assert.notEqual(duplicate.music.cues[0].id, source.music.cues[0].id)
  assert.equal(duplicate.relationships[0].fromCharacterId, duplicate.characters[0].id)
  assert.equal(duplicate.characters[0].primaryReferenceAssetId, Object.keys(duplicate.assets)[0])
  assert.equal(duplicate.music.cues[0].targetId, duplicate.characters[0].id)
  assert.notEqual(duplicate.music.candidates[0].id, source.music.candidates[0].id)
  assert.notEqual(duplicate.music.cues[0].candidates[0].id, duplicate.music.candidates[0].id)
  assert.equal(duplicate.music.cues[0].selectedCandidateId, duplicate.music.cues[0].candidates[0].id)
  assert.equal(duplicate.music.selectedCandidateId, duplicate.music.candidates[0].id)
  assert.deepEqual(duplicate.productions, [])
  assert.deepEqual(duplicate.visualJobs, {})
})
