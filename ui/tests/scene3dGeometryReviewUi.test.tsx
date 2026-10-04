import assert from 'node:assert/strict'
import test from 'node:test'
import React, { useRef } from 'react'
import { JSDOM } from 'jsdom'
import type { Scene3DDocument } from '../src/features/scene3d/types.ts'
import type { Scene3DStageHandle } from '../src/features/scene3d/Scene3DStage.tsx'
import type { GeometrySlotSample } from '../src/features/scene3d/geometryChecks.ts'

function installDom() {
  const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
  Object.assign(globalThis, {
    window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement,
    HTMLButtonElement: dom.window.HTMLButtonElement, Event: dom.window.Event,
    MutationObserver: dom.window.MutationObserver,
  })
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
}
installDom()

const sunk = { min: [-0.3, -0.4, -0.2], max: [0.3, 1.3, 0.2] } as const
const slot = (): GeometrySlotSample => ({
  id: 'hero', character: true, ground: 0, onFloor: true, min: [...sunk.min], max: [...sunk.max], visible: true,
})

test('the geometry list seeks to the warning and leaves export available', async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { Scene3DGeometryReview } = await import('../src/features/scene3d/Scene3DGeometryReview.tsx')
  const sought: number[] = []
  const paints: number[] = []
  function Harness() {
    const stageRef = useRef<Scene3DStageHandle>({
      geometrySample: time => ({ t: time, camera: [0, 1.6, 4], slots: [slot()] }),
      paint: seconds => { paints.push(seconds); return null },
    } as Scene3DStageHandle)
    return <Scene3DGeometryReview stageRef={stageRef} document={{ duration: 1 } as Scene3DDocument} seconds={0.4} disabled={false} onSeek={time => sought.push(time)} />
  }
  try {
    render(<Harness />)
    assert.equal(screen.queryByRole('button', { name: /goes through the floor/ }), null)
    fireEvent.click(screen.getByRole('button', { name: 'Check geometry' }))
    fireEvent.click(screen.getByRole('button', { name: /hero goes through the floor/ }))
    assert.equal(sought[0], 0)
    assert.deepEqual(paints, [0.4])
    assert.equal(screen.getByText('These warnings do not block export.').textContent?.length > 0, true)
  } finally { cleanup() }
})
