import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'

function installDom() {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
  Object.assign(globalThis, {
    window: dom.window,
    document: dom.window.document,
    HTMLElement: dom.window.HTMLElement,
    HTMLButtonElement: dom.window.HTMLButtonElement,
    Element: dom.window.Element,
    Node: dom.window.Node,
    Event: dom.window.Event,
    MouseEvent: dom.window.MouseEvent,
    MutationObserver: dom.window.MutationObserver,
    localStorage: dom.window.localStorage,
    sessionStorage: dom.window.sessionStorage,
  })
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
}

installDom()

const CUDA = "No CUDA GPU detected. HocusPocus Lab's generation pipeline requires an NVIDIA GPU; generation will not work on this machine."
const FFMPEG = 'ffmpeg was not found on PATH. Video and audio export will fail. Install ffmpeg and restart HocusPocus Lab.'

async function resetNotices() {
  const { safeStorageRemove } = await import('../src/lib/safeStorage.ts')
  const { resetPreflightForTests } = await import('../src/features/notices/preflightNotices.ts')
  const { resetProfileNoticeForTests } = await import('../src/features/notices/profileNoticeState.ts')
  safeStorageRemove('session', 'maestro_preflight_dismissed')
  window.localStorage.removeItem('hocuspocus-production-profile-notice')
  resetPreflightForTests()
  resetProfileNoticeForTests()
}

test('the notice tray counts, opens, dismisses, and keeps the CUDA warning', { concurrency: false }, async () => {
  const { render, screen, fireEvent, waitFor, cleanup, within } = await import('@testing-library/react')
  const { useStore } = await import('../src/stores/useStore.ts')
  const { NoticeTray } = await import('../src/features/notices/NoticeTray.tsx')
  const { GpuNoticeDot } = await import('../src/features/notices/GpuNoticeDot.tsx')
  const { safeStorageGet } = await import('../src/lib/safeStorage.ts')
  const originalFetch = globalThis.fetch
  globalThis.fetch = async () => ({
    ok: true,
    json: async () => ({
      ok: false,
      checks: [
        { id: 'cuda', level: 'error', message: 'no cuda' },
        { id: 'ffmpeg', level: 'error', message: 'ffmpeg is missing' },
      ],
    }),
  }) as Response
  useStore.setState({
    productionProfileLoaded: true,
    productionProfileConfigured: false,
    productionProfileInvalidReason: 'tray-test',
  })
  await resetNotices()

  try {
    render(<><NoticeTray /><GpuNoticeDot /></>)
    await waitFor(() => assert.equal(screen.getByTestId('notice-tray-count').textContent, '3'))
    assert.match(screen.getByTestId('notice-tray-button').getAttribute('aria-label') || '', /3 notices/)
    const dot = screen.getByTestId('gpu-notice-dot')
    assert.equal(dot.getAttribute('title'), CUDA)
    assert.equal(dot.getAttribute('aria-label'), CUDA)

    fireEvent.click(screen.getByTestId('notice-tray-button'))
    const panel = screen.getByTestId('notice-tray-panel')
    assert.ok(within(panel).getByText(CUDA))
    assert.ok(within(panel).getByText(FFMPEG))
    assert.match(panel.textContent || '', /could not be read \(tray-test\)/)
    assert.equal(within(screen.getByTestId('preflight-notice-cuda')).queryByRole('button', { name: 'Dismiss' }), null)

    fireEvent.click(within(screen.getByTestId('preflight-notice-ffmpeg')).getByRole('button', { name: 'Dismiss' }))
    assert.equal(screen.queryByText(FFMPEG), null)
    assert.ok(screen.getByText(CUDA))
    assert.equal(safeStorageGet('session', 'maestro_preflight_dismissed'), '1')
    assert.equal(screen.getByTestId('notice-tray-count').textContent, '2')

    fireEvent.click(within(screen.getByTestId('production-profile-notice')).getByRole('button', { name: 'Dismiss' }))
    assert.equal(screen.queryByTestId('production-profile-notice'), null)
    assert.equal(screen.getByTestId('notice-tray-count').textContent, '1')
    assert.equal(screen.getByTestId('gpu-notice-dot').getAttribute('title'), CUDA)

    cleanup()
    render(<><NoticeTray /><GpuNoticeDot /></>)
    await waitFor(() => assert.equal(screen.getByTestId('notice-tray-count').textContent, '1'))
    fireEvent.click(screen.getByTestId('notice-tray-button'))
    assert.ok(screen.getByText(CUDA))
    assert.equal(screen.queryByText(FFMPEG), null)
    assert.equal(screen.queryByTestId('production-profile-notice'), null)
    assert.equal(within(screen.getByTestId('preflight-notice-cuda')).queryByRole('button', { name: 'Dismiss' }), null)
  } finally {
    cleanup()
    globalThis.fetch = originalFetch
    useStore.setState({
      productionProfileLoaded: false,
      productionProfileConfigured: false,
      productionProfileInvalidReason: '',
    })
    await resetNotices()
  }
})

test('the footer dot stays hidden when there is no CUDA notice', { concurrency: false }, async () => {
  const { render, screen, waitFor, cleanup } = await import('@testing-library/react')
  const { useStore } = await import('../src/stores/useStore.ts')
  const { NoticeTray } = await import('../src/features/notices/NoticeTray.tsx')
  const { GpuNoticeDot } = await import('../src/features/notices/GpuNoticeDot.tsx')
  const originalFetch = globalThis.fetch
  globalThis.fetch = async () => ({
    ok: true,
    json: async () => ({ ok: false, checks: [{ id: 'ffmpeg', level: 'error', message: 'ffmpeg is missing' }] }),
  }) as Response
  useStore.setState({ productionProfileLoaded: true, productionProfileConfigured: true, productionProfileInvalidReason: '' })
  await resetNotices()
  try {
    render(<><NoticeTray /><GpuNoticeDot /></>)
    await waitFor(() => assert.equal(screen.getByTestId('notice-tray-count').textContent, '1'))
    assert.equal(screen.queryByTestId('gpu-notice-dot'), null)
  } finally {
    cleanup()
    globalThis.fetch = originalFetch
    useStore.setState({ productionProfileLoaded: false, productionProfileConfigured: false })
    await resetNotices()
  }
})
