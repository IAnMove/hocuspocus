import assert from 'node:assert/strict'
import test from 'node:test'
import { setGameFetch } from '../src/api/gameAssets.ts'
import { colorsFromImageData, isHexColor } from '../src/features/game-assets/styles.ts'
import { useGameAssetsStore } from '../src/features/game-assets/store.ts'
import type { Game } from '../src/features/game-assets/types.ts'

function sample(revision: number, title: string): Game {
  return {
    id: 'bosque', title, revision, createdAt: '', updatedAt: '', genre: 'platformer', view: 'side', exports: [],
    assets: [],
    style: {
      revision: 1, approval: 'draft', approvedAt: null, preset: 'pixel-16', traits: 'flat', negative: 'photo',
      palette: ['#112233'], paletteMode: 'locked', light: 'top-left', screen: 'magenta', references: [],
      pixel: { enabled: true, spriteHeight: 48, tile: 16, colors: 16, outline: 'dark-1px', dither: 'none' },
      model3d: { maxTriangles: 3000, texture: 512, look: 'toon' },
      audio: { genre: 'chiptune', instruments: 'square', bpm: [90, 140], musicLufs: -16, sfxPeakDb: -1, sampleRate: 48000 },
    },
  }
}

test('a revision conflict reloads the game from the server', async () => {
  const fresh = sample(4, 'Server')
  useGameAssetsStore.setState({
    workspace: 'lab', ready: true, games: [sample(2, 'Local')], game: sample(2, 'Local'),
    serverRevision: 2, dirty: true, editSeq: 1, saving: false, error: null, notice: null,
  })
  setGameFetch(async (_url, init) => {
    if (init?.method === 'PUT') {
      return new Response(JSON.stringify({ detail: { code: 'revision_conflict', message: 'revision conflict' } }), { status: 409 })
    }
    return new Response(JSON.stringify(fresh), { status: 200 })
  })
  try {
    const saved = await useGameAssetsStore.getState().saveNow()
    assert.equal(saved?.title, 'Server')
    assert.equal(saved?.revision, 4)
    assert.equal(useGameAssetsStore.getState().dirty, false)
    assert.equal(useGameAssetsStore.getState().notice, 'revision_conflict')
    assert.equal(useGameAssetsStore.getState().serverRevision, 4)
  } finally {
    setGameFetch(null)
    useGameAssetsStore.setState({ workspace: '', ready: false, game: null, games: [], dirty: false, notice: null })
  }
})

test('palette colors are hex and median cut keeps separated colors', () => {
  assert.equal(isHexColor('#112233'), true)
  assert.equal(isHexColor('#abc'), false)
  assert.equal(isHexColor('red'), false)
  const data = new Uint8ClampedArray([255, 0, 0, 255, 0, 0, 255, 255])
  const colors = colorsFromImageData(data, 2).sort()
  assert.deepEqual(colors, ['#0000ff', '#ff0000'])
})
