import assert from 'node:assert/strict'
import test from 'node:test'
import type { OutputFile } from '../src/types/index.ts'

const file = (name: string, type: OutputFile['type'], extra: Partial<OutputFile> = {}): OutputFile =>
  ({ name, url: `/f/${name}`, type, mode: null, favorite: false, size: 1, created_at: 1, ...extra })

test('only images and videos without a size or colour are still missing facts', async () => {
  const { missingFactNames } = await import('../src/components/MainContent/useLiveMediaFacts.ts')
  assert.deepEqual(missingFactNames([
    file('done.png', 'image', { width: 10, height: 10, color: '#112233' }),
    file('no-colour.png', 'image', { width: 10, height: 10 }),
    file('no-size.mp4', 'video', { color: '#112233' }),
    file('song.mp3', 'audio'),
    file('saved.scene.json', 'scene'),
  ]), ['no-colour.png', 'no-size.mp4'])
})

test('late facts merge into the listed outputs and report what changed', async () => {
  const { useStore } = await import('../src/stores/useStore.ts')
  const untouched = file('other.png', 'image', { width: 1, height: 1, color: '#000000' })
  useStore.setState({ outputs: [file('clip.mp4', 'video'), untouched] })
  const merge = useStore.getState().mergeOutputFacts
  assert.equal(merge({ 'clip.mp4': { width: 720, height: 1280, color: '#aabbcc' }, 'gone.png': { color: '#ffffff' } }), 1)
  const [clip, other] = useStore.getState().outputs
  assert.deepEqual([clip.width, clip.height, clip.color], [720, 1280, '#aabbcc'])
  assert.equal(other, untouched, 'unchanged outputs keep their identity')
  assert.equal(merge({ 'clip.mp4': { width: 720, height: 1280, color: '#aabbcc' } }), 0)
  assert.equal(merge({ 'clip.mp4': { color: 'red' } }), 0, 'malformed colours are ignored')
  assert.equal(merge({ 'clip.mp4': { width: 1920 } }), 0, 'a width without a height is ignored')
})
