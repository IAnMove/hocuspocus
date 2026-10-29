import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
Object.assign(globalThis, {
  React,
  window: dom.window,
  document: dom.window.document,
  HTMLElement: dom.window.HTMLElement,
  HTMLButtonElement: dom.window.HTMLButtonElement,
  Event: dom.window.Event,
  MutationObserver: dom.window.MutationObserver,
})
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

test('workbench shows every slot and collapses the side panels', async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { Workbench } = await import('../src/components/workbench/Workbench')
  const { workbenchLayout } = await import('../src/components/workbench/layout')
  assert.equal(workbenchLayout(1600), 'dock')
  assert.equal(workbenchLayout(1100), 'drawer')
  assert.equal(workbenchLayout(700), 'stack')
  try {
    render(
      <Workbench
        width={1600}
        topBar={<span>Top mark</span>}
        outline={<span>Outline mark</span>}
        viewport={<span>Viewport mark</span>}
        inspector={<span>Inspector mark</span>}
        transport={<span>Transport mark</span>}
      />,
    )
    const root = screen.getByTestId('workbench')
    assert.equal(root.getAttribute('data-layout'), 'dock')
    assert.equal(root.querySelector('[data-slot="topBar"]')?.textContent, 'Top mark')
    assert.equal(root.querySelector('[data-slot="outline"]')?.textContent, 'Outline mark')
    assert.equal(root.querySelector('[data-slot="viewport"]')?.textContent, 'Viewport mark')
    assert.equal(root.querySelector('[data-slot="inspector"]')?.textContent, 'Inspector mark')
    assert.equal(root.querySelector('[data-slot="transport"]')?.textContent, 'Transport mark')
    fireEvent.click(screen.getByTestId('workbench-toggle-outline'))
    assert.equal(screen.queryByText('Outline mark'), null)
    fireEvent.click(screen.getByTestId('workbench-toggle-outline'))
    assert.equal(screen.getByText('Outline mark').textContent, 'Outline mark')
    fireEvent.click(screen.getByTestId('workbench-toggle-inspector'))
    assert.equal(screen.queryByText('Inspector mark'), null)
    assert.equal(screen.getByText('Viewport mark').textContent, 'Viewport mark')
  } finally {
    cleanup()
  }
})

test('below 1100 the inspector is a drawer and a phone stacks the panels', async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { Workbench } = await import('../src/components/workbench/Workbench')
  try {
    const drawer = render(
      <Workbench
        width={1100}
        outline={<span>Outline mark</span>}
        viewport={<span>Viewport mark</span>}
        inspector={<span>Inspector mark</span>}
      />,
    )
    assert.equal(screen.getByTestId('workbench').getAttribute('data-layout'), 'drawer')
    assert.equal(screen.queryByText('Inspector mark'), null)
    assert.equal(screen.getByText('Viewport mark').textContent, 'Viewport mark')
    fireEvent.click(screen.getByRole('button', { name: 'Open inspector' }))
    assert.equal(screen.getByText('Inspector mark').textContent, 'Inspector mark')
    fireEvent.click(screen.getByTestId('workbench-toggle-inspector'))
    assert.equal(screen.queryByText('Inspector mark'), null)
    drawer.unmount()

    render(
      <Workbench
        width={600}
        outline={<span>Outline mark</span>}
        viewport={<span>Viewport mark</span>}
        inspector={<span>Inspector mark</span>}
      />,
    )
    const stacked = screen.getByTestId('workbench')
    assert.equal(stacked.getAttribute('data-layout'), 'stack')
    assert.equal(stacked.querySelector('[data-slot="outline"]')?.textContent, 'Outline mark')
    assert.equal(stacked.querySelector('[data-slot="inspector"]')?.textContent, 'Inspector mark')
    assert.equal(stacked.querySelector('[data-slot="viewport"]')?.textContent, 'Viewport mark')
  } finally {
    cleanup()
  }
})
