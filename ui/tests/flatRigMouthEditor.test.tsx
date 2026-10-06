import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
import { createCharacterKit, type CharacterKit } from '../src/lib/characterKit'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement,
  Event: dom.window.Event, MutationObserver: dom.window.MutationObserver })
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

const file = (name: string) => `/api/v1/file/${name}.png?workspace=cast`

function warpKit(): CharacterKit {
  const kit = createCharacterKit('Blas')
  kit.id = 'blas'
  const pose = (id: string) => ({ id, name: id, source: file(id), kind: 'image' as const, alphaStatus: 'transparent' as const, reviewState: 'approved' as const })
  kit.base = pose('kit-blas-base-rig-1')
  kit.poses = { busto: pose('kit-blas-busto-rig-1') }
  kit.mouth = { closed: { ...pose('blas-mouth-closed'), kind: 'overlay', source: file('kit-blas-base-mouth-closed') } }
  kit.anchors = { base: { mouth: { offsetX: 0, offsetY: -20, scale: .2, rotation: 0 }, mouthSources: { closed: file('kit-blas-base-mouth-closed') } },
    busto: { mouth: { offsetX: 0, offsetY: -10, scale: .2, rotation: 0 }, mouthSources: { closed: file('kit-blas-busto-mouth-closed') } } }
  kit.provenance = [{ method: 'flat-rig', sources: { base: file('blas-key'), busto: file('blas-busto-key') }, style: { mouthStyle: 'warp' },
    hints: { busto: { mouth: [61.6, 20.1], mouthWidth: 6.5 } }, mouthLines: {} }]
  return kit
}

const preview = (mouth: [number, number], mouthWidth: number) => ({ pose: 'busto', mouth, mouthWidth, found: true, from: 'hint',
  line: [[mouth[0] - mouthWidth / 2, mouth[1]], [mouth[0] + mouthWidth / 2, mouth[1]]], view: [[50, 10], [70, 30]], hint: null,
  states: Object.fromEntries(['closed', 'small', 'medium', 'wide', 'round', 'pucker'].map(state => [state, `data:image/jpeg;base64,${state}`])) })

test('the mouth line editor previews a pose live, moves its line by hand and saves it as the pose hint', async t => {
  const { render, fireEvent, waitFor, cleanup } = await import('@testing-library/react')
  const { FlatRigMouthEditor } = await import('../src/features/characters/FlatRigMouthEditor')
  const kit = warpKit()
  const originalFetch = globalThis.fetch
  const posts: Array<{ url: string; body: Record<string, unknown> }> = []
  globalThis.fetch = async (input, init) => {
    const url = String(input)
    if (init?.method === 'POST') {
      const body = JSON.parse(String(init.body))
      posts.push({ url, body })
      if (url.endsWith('/flat-rig/preview')) return new Response(JSON.stringify(preview(body.mouth ?? [61.6, 20.48], body.mouthWidth ?? 6.5)))
      return new Response(JSON.stringify({ revision: 8, character: kit, review: file('review'), unwipedPoses: [] }))
    }
    assert.ok(url.includes('/api/v1/character-kits/library?workspace=cast'))
    return new Response(JSON.stringify({ version: 1, revision: 7, activeId: 'blas', kits: { blas: kit } }))
  }
  t.after(() => { cleanup(); globalThis.fetch = originalFetch })
  const rigged: unknown[] = []
  const view = render(<FlatRigMouthEditor kit={kit} poseId="busto" workspace="cast" onRigged={result => { rigged.push(result) }} />)
  // A warp kit opens on its pose: the saved hint is previewed first, on the pose's rigged original.
  await waitFor(() => assert.equal(posts.length, 1))
  assert.deepEqual(posts[0].body, { workspace: 'cast', pose: 'busto', mouth: [61.6, 20.1], mouthWidth: 6.5 })
  await waitFor(() => assert.equal(view.getAllByRole('img', { name: /Blas saying/ }).length, 6))
  const face = view.getByRole('img', { name: "Blas's mouth, enlarged" }) as HTMLImageElement
  assert.equal(face.getAttribute('src'), file('blas-busto-key'))
  Object.defineProperty(face, 'naturalWidth', { value: 896 })
  Object.defineProperty(face, 'naturalHeight', { value: 1152 })
  fireEvent.load(face)
  await waitFor(() => assert.ok(view.getByRole('button', { name: 'Point on the mouth line' })))
  const save = view.getByRole('button', { name: 'Save mouth' }) as HTMLButtonElement
  assert.equal(save.disabled, true, 'nothing to save before the line moves')
  fireEvent.click(view.getByRole('button', { name: 'Down' }))
  fireEvent.click(view.getByRole('button', { name: 'Wider' }))
  await waitFor(() => assert.deepEqual(posts.at(-1)!.body, { workspace: 'cast', pose: 'busto', mouth: [61.6, 20.2], mouthWidth: 6.7 }))
  fireEvent.click(save)
  await waitFor(() => assert.equal(rigged.length, 1))
  const rig = posts.find(post => post.url.endsWith('/flat-rig'))!
  assert.deepEqual(rig.body, { workspace: 'cast', baseRevision: 7, style: { mouthStyle: 'warp' }, poses: ['base', 'busto'],
    hints: { busto: { mouth: [61.6, 20.2], mouthWidth: 6.7 } } })
  assert.ok(view.getByRole('status').textContent?.includes('rendered again'), 'says which shots need rendering again')
})

test('the editor refuses to save over unsaved changes and stays out of kits the flat rig did not make', async t => {
  const { render, fireEvent, waitFor, cleanup } = await import('@testing-library/react')
  const { FlatRigMouthEditor } = await import('../src/features/characters/FlatRigMouthEditor')
  const kit = warpKit()
  const stored = { ...kit, name: 'Blas (saved)' }
  const originalFetch = globalThis.fetch
  const posts: string[] = []
  globalThis.fetch = async (input, init) => {
    if (init?.method === 'POST') {
      posts.push(String(input))
      return new Response(JSON.stringify(preview([61.6, 20.48], 6.5)))
    }
    return new Response(JSON.stringify({ version: 1, revision: 3, activeId: 'blas', kits: { blas: stored } }))
  }
  t.after(() => { cleanup(); globalThis.fetch = originalFetch })
  const plain = render(<FlatRigMouthEditor kit={createCharacterKit('Drawn')} poseId="base" workspace="cast" onRigged={() => {}} />)
  assert.equal(plain.container.innerHTML, '')
  plain.unmount()
  const view = render(<FlatRigMouthEditor kit={kit} poseId="base" workspace="cast" onRigged={() => {}} />)
  await waitFor(() => assert.equal(view.getAllByRole('img', { name: /Blas saying/ }).length, 6))
  fireEvent.click(view.getByRole('button', { name: 'Down' }))
  fireEvent.click(view.getByRole('button', { name: 'Save mouth' }))
  await waitFor(() => assert.match(view.getByRole('alert').textContent ?? '', /Save the character's other changes first/))
  assert.ok(posts.every(url => url.endsWith('/flat-rig/preview')), 'no rig over unsaved changes')
})

test('the editor says when a small face was read on the head alone and warped enlarged', async t => {
  const { render, waitFor, cleanup } = await import('@testing-library/react')
  const { FlatRigMouthEditor } = await import('../src/features/characters/FlatRigMouthEditor')
  const kit = warpKit()
  const originalFetch = globalThis.fetch
  let face: Record<string, unknown> = { size: 'small', head: 84, pass: 'head', upscale: 5 }
  globalThis.fetch = async () => new Response(JSON.stringify({ ...preview([61.6, 20.48], 6.5), faceSize: face }))
  t.after(() => { cleanup(); globalThis.fetch = originalFetch })
  const small = render(<FlatRigMouthEditor kit={kit} poseId="busto" workspace="cast" />)
  await waitFor(() => assert.ok(small.getByTestId('mouth-line-face')))
  const note = small.getByTestId('mouth-line-face').textContent ?? ''
  assert.match(note, /Small face \(head 84 px\).*enlarged 5×/)
  assert.match(note, /read on the head alone/)
  small.unmount()
  face = { size: 'normal', head: 264, pass: 'whole', upscale: 1 }
  const bust = render(<FlatRigMouthEditor kit={kit} poseId="busto" workspace="cast" />)
  await waitFor(() => assert.equal(bust.getAllByRole('img', { name: /Blas saying/ }).length, 6))
  assert.equal(bust.queryByTestId('mouth-line-face'), null, 'a bust read whole and warped as it is says nothing')
})
