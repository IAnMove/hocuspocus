import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
import { defaultModelScreen, parseMediaScreen, type MediaScreen } from '../src/features/scene3d/mediaScreen'
import type { Scene3DSlot } from '../src/features/scene3d/types'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { React, window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement,
  HTMLInputElement: dom.window.HTMLInputElement, Event: dom.window.Event, MutationObserver: dom.window.MutationObserver })
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
const nodes = ['Armature', 'Mesh_0', 'Head', 'headfront']

test('mesh mode offers meshes; plane mode offers bones and a clear empty choice', async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { Scene3DScreenControls } = await import('../src/features/scene3d/Scene3DScreenControls')
  const slot: Scene3DSlot = { id: 'actor', slot: 'subject_1', media: 'model3d', sourceUrl: '/actor.glb', clip: null,
    position: [0, 0, 0], rotationY: 0, scale: 1, screen: defaultModelScreen(nodes, ['Mesh_0']) }
  let next: MediaScreen | undefined
  const props = { slot, meshes: ['Mesh_0'], nodes, items: [], disabled: false,
    onChange: (value: MediaScreen | undefined) => { next = value }, onChoose: () => {}, onRemove: () => {} }
  try {
    const view = render(<Scene3DScreenControls {...props} />)
    const anchors = screen.getByLabelText('Bone or node') as HTMLSelectElement
    assert.deepEqual(Array.from(anchors.options, item => item.value), ['', ...new Set(['headfront', ...nodes])])
    fireEvent.change(screen.getByLabelText('How to attach'), { target: { value: 'mesh' } })
    assert.equal(next?.targetMesh, 'Mesh_0')
    view.rerender(<Scene3DScreenControls {...props} slot={{ ...slot, screen: next }} />)
    const meshes = screen.getByLabelText('Screen mesh') as HTMLSelectElement
    assert.deepEqual(Array.from(meshes.options, item => item.value), ['Mesh_0'])
  } finally { cleanup() }
})

test('placement fields use the same limits as reopening a scene', async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { Scene3DScreenControls } = await import('../src/features/scene3d/Scene3DScreenControls')
  const slot: Scene3DSlot = { id: 'actor', slot: 'subject_1', media: 'model3d', sourceUrl: '/actor.glb', clip: null,
    position: [0, 0, 0], rotationY: 0, scale: 1, screen: defaultModelScreen(nodes, ['Mesh_0']) }
  let next = slot.screen!
  try {
    render(<Scene3DScreenControls slot={slot} meshes={['Mesh_0']} nodes={nodes} items={[]} disabled={false}
      onChange={value => { next = value! }} onChoose={() => {}} onRemove={() => {}} />)
    fireEvent.change(screen.getByLabelText('Offset X'), { target: { value: '7' } })
    assert.equal(next.offset[0], 2)
    assert.deepEqual(parseMediaScreen(next)?.offset, next.offset)
    fireEvent.change(screen.getByLabelText('Yaw (°)'), { target: { value: '540' } })
    assert.equal(next.yaw, Math.PI)
    assert.equal(parseMediaScreen(next)?.yaw, next.yaw)
  } finally { cleanup() }
})

test('a cutout character can enable, time, align and reorder held poses in the editor', async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { Scene3DScreenControls } = await import('../src/features/scene3d/Scene3DScreenControls')
  const slot: Scene3DSlot = { id: 'knight', slot: 'subject_1', media: 'image', surface: 'cutout', sourceUrl: '/knight.png', clip: null,
    position: [0, 0, 0], rotationY: 0, scale: 1 }
  let saved: MediaScreen | undefined
  function Harness({ disabled = false }) {
    const [value, setValue] = React.useState<MediaScreen>()
    return <Scene3DScreenControls slot={{ ...slot, screen: value }} meshes={[]} items={[]} disabled={disabled} workspace="example"
      onChange={next => { saved = parseMediaScreen(next); setValue(saved) }} onChoose={() => {}} onRemove={() => {}} />
  }
  try {
    const view = render(<Harness />)
    fireEvent.click(screen.getByLabelText('Animate this layer'))
    fireEvent.click(screen.getByLabelText('Held poses'))
    assert.equal(saved?.poseSequence?.[0].sourceUrl, '/knight.png')
    assert.equal(saved?.transparent, true)
    fireEvent.change(screen.getByLabelText('Duration (s) 1'), { target: { value: '1.4' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add pose' }))
    fireEvent.change(screen.getByLabelText('Relative height 2'), { target: { value: '.5' } })
    fireEvent.click(screen.getAllByRole('button', { name: 'Move earlier' })[1])
    assert.deepEqual(saved?.poseSequence?.map(p => p.height), [.5, .9])
    assert.deepEqual(saved?.poseSequence?.map(p => p.duration), [1.4, 1.4])
    assert.equal(parseMediaScreen(JSON.parse(JSON.stringify(saved)))?.poseSequence?.length, 2)
    assert.ok(screen.getByLabelText('Playback speed'))
    view.rerender(<Harness disabled />)
    assert.equal((screen.getByRole('button', { name: 'Add pose' }) as HTMLButtonElement).disabled, true)
  } finally { cleanup() }
})
