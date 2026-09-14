import assert from 'node:assert/strict'
import test from 'node:test'
import React, { useEffect, useState } from 'react'
import { JSDOM } from 'jsdom'

function installDom() {
  const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
  Object.assign(globalThis, {
    window: dom.window,
    document: dom.window.document,
    HTMLElement: dom.window.HTMLElement,
    HTMLButtonElement: dom.window.HTMLButtonElement,
    HTMLSelectElement: dom.window.HTMLSelectElement,
    Event: dom.window.Event,
    MutationObserver: dom.window.MutationObserver,
    ResizeObserver: class {
      observe() {}
      disconnect() {}
    },
    React,
  })
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
  Object.defineProperty(dom.window.HTMLElement.prototype, 'scrollIntoView', {
    configurable: true,
    value: () => undefined,
  })
}

installDom()

test('Help opens the tutorial overlay in English and Spanish', async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { useStore } = await import('../src/stores/useStore.ts')
  const { TabFilter } = await import('../src/components/MainContent/TabFilter.tsx')
  const { HelpOverlay } = await import('../src/components/Help/HelpOverlay.tsx')
  const { setUiLanguage } = await import('../src/i18n/index.ts')
  await setUiLanguage('en')
  useStore.setState({ mediaFilter: 'all', outputSearchQuery: '' })

  function OpenableHelp() {
    const [open, setOpen] = useState(false)
    useEffect(() => {
      const onOpen = () => setOpen(true)
      window.addEventListener('hocuspocus:help-open', onOpen)
      return () => window.removeEventListener('hocuspocus:help-open', onOpen)
    }, [])
    return <>
      <TabFilter />
      <HelpOverlay open={open} onClose={() => setOpen(false)} />
    </>
  }

  try {
    render(<OpenableHelp />)
    assert.equal(screen.queryByRole('dialog'), null)
    const opener = screen.getByRole('button', { name: 'Open the HocusPocus tutorial' })
    opener.focus()
    fireEvent.click(opener)
    const dialog = await screen.findByRole('dialog', { name: 'How to use HocusPocus' })
    assert.equal(dialog.parentElement, document.body)
    const language = screen.getByLabelText('Tutorial language')
    const lastLink = screen.getByRole('link', { name: 'Example outputs' })
    assert.equal(document.activeElement, language)
    fireEvent.keyDown(language, { key: 'Tab', shiftKey: true })
    assert.equal(document.activeElement, lastLink)
    fireEvent.keyDown(lastLink, { key: 'Tab' })
    assert.equal(document.activeElement, language)
    assert.ok(screen.getByText('Talking faces (9×6 pack)'))
    assert.ok(screen.getByText('Cut-paper example (Tijeral)'))
    fireEvent.change(screen.getByLabelText('Tutorial language'), { target: { value: 'es' } })
    assert.ok(screen.getByRole('dialog', { name: 'Cómo usar HocusPocus' }))
    assert.ok(screen.getByText('Caras que hablan (pack 9×6)'))
    assert.ok(screen.getByRole('button', { name: 'Abrir el tutorial de HocusPocus' }))
    assert.ok(screen.getByText('Ayuda'))
    assert.equal(document.activeElement, language)
    fireEvent.keyDown(language, { key: 'Escape' })
    assert.equal(screen.queryByRole('dialog'), null)
    assert.equal(document.activeElement, opener)

    fireEvent.click(opener)
    assert.ok(await screen.findByRole('dialog', { name: 'Cómo usar HocusPocus' }))
    fireEvent.click(screen.getByRole('button', { name: 'Cerrar ayuda' }))
    assert.equal(screen.queryByRole('dialog'), null)
    assert.equal(document.activeElement, opener)

    fireEvent.click(opener)
    const reopened = await screen.findByRole('dialog', { name: 'Cómo usar HocusPocus' })
    fireEvent.mouseDown(screen.getByRole('heading', { name: 'Cómo usar HocusPocus' }))
    assert.ok(screen.getByRole('dialog'))
    fireEvent.mouseDown(reopened)
    assert.equal(screen.queryByRole('dialog'), null)
    assert.equal(document.activeElement, opener)
  } finally {
    cleanup()
    await setUiLanguage('en')
  }
})

test('Escape closes Help without closing the underlying modal or reaching app shortcuts', async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { ModalShell } = await import('../src/components/common/ModalShell.tsx')
  const { HelpOverlay } = await import('../src/components/Help/HelpOverlay.tsx')
  let parentCloses = 0
  let windowEscapes = 0
  const onWindowKey = () => { windowEscapes += 1 }
  window.addEventListener('keydown', onWindowKey)

  function NestedHelp() {
    const [open, setOpen] = useState(false)
    return <ModalShell open title="Parent" onClose={() => { parentCloses += 1 }}>
      <button onClick={() => setOpen(true)}>Open help</button>
      <HelpOverlay open={open} onClose={() => setOpen(false)} />
    </ModalShell>
  }

  try {
    render(<NestedHelp />)
    const opener = screen.getByRole('button', { name: 'Open help' })
    fireEvent.click(opener)
    assert.ok(screen.getByRole('dialog', { name: 'How to use HocusPocus' }))
    fireEvent.keyDown(screen.getByLabelText('Tutorial language'), { key: 'Escape' })
    assert.equal(screen.queryByRole('dialog', { name: 'How to use HocusPocus' }), null)
    assert.ok(screen.getByRole('dialog', { name: 'Parent' }))
    assert.equal(parentCloses, 0)
    assert.equal(windowEscapes, 0)
    assert.equal(document.activeElement, opener)
  } finally {
    cleanup()
    window.removeEventListener('keydown', onWindowKey)
  }
})
