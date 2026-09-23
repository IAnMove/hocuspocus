import assert from 'node:assert/strict'
import test from 'node:test'

const store = new Map<string, string>()
Object.assign(globalThis, {
  sessionStorage: {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => { store.set(key, value) },
  },
})

test('each list remembers its own position for the tab', async () => {
  const { galleryPositionKey, readGalleryPosition, writeGalleryPosition } = await import('../src/components/MainContent/galleryPositions.ts')
  const all = galleryPositionKey('default', false, 'all')
  const uploads = galleryPositionKey('default', true, 'all')
  assert.notEqual(all, uploads)
  assert.equal(readGalleryPosition(all), null)

  writeGalleryPosition(all, { name: 'a.png', within: 40 })
  writeGalleryPosition(uploads, { name: 'b.png', within: 0 })
  assert.deepEqual(readGalleryPosition(all), { name: 'a.png', within: 40 })
  assert.deepEqual(JSON.parse(store.get('hocuspocus_gallery_positions')!).length, 2)

  writeGalleryPosition(all, null)
  assert.equal(readGalleryPosition(all), null, 'back at the top forgets the position')

  for (let index = 0; index < 60; index++) writeGalleryPosition(`ws-${index}|all`, { name: `${index}.png`, within: 0 })
  assert.equal(readGalleryPosition('ws-0|all'), null, 'oldest lists are dropped')
  assert.deepEqual(readGalleryPosition('ws-59|all'), { name: '59.png', within: 0 })
})
