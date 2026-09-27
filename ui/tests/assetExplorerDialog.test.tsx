import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'

Object.assign(globalThis, { React })

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, {
  window: dom.window,
  document: dom.window.document,
  HTMLElement: dom.window.HTMLElement,
  HTMLButtonElement: dom.window.HTMLButtonElement,
  HTMLInputElement: dom.window.HTMLInputElement,
  HTMLImageElement: dom.window.HTMLImageElement,
  Event: dom.window.Event,
  MouseEvent: dom.window.MouseEvent,
  MutationObserver: dom.window.MutationObserver,
  ResizeObserver: class { observe() {} disconnect() {} },
})
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

test('multiple selection is independent from preview and retained across pages', async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { AssetExplorerDialog } = await import('../src/components/common/AssetExplorerDialog.tsx')
  const items = Array.from({ length: 25 }, (_, index) => ({ name: `${index}.png`, type: 'image' as const,
    mode: null, size: 1000, created_at: 1000 - index, url: `/api/v1/file/${index}.png?workspace=default`, workspace_id: 'default' }))
  let chosen: typeof items = []
  try {
    render(<AssetExplorerDialog open title="Batch" items={items} workspaceId="default" constraints={{ kinds: ['image'], maxCount: 2, optional: false }} onChoose={() => assert.fail('single callback')} onChooseMany={value => { chosen = value as typeof items }} onClose={() => {}} />)
    fireEvent.click(screen.getByTitle('0.png'))
    assert.equal((screen.getByRole('button', { name: 'Choose' }) as HTMLButtonElement).disabled, true)
    fireEvent.click(screen.getByRole('checkbox', { name: '0.png' }))
    fireEvent.click(screen.getByRole('button', { name: /Next page/ }))
    fireEvent.click(screen.getByRole('checkbox', { name: '24.png' }))
    fireEvent.click(screen.getByRole('button', { name: 'Choose' }))
    assert.deepEqual(chosen.map(item => item.name), ['0.png', '24.png'])
    assert.ok(chosen.every(item => item.url.includes('/file/') && item.thumbnail_url?.includes('/thumbnail/')))
  } finally { cleanup() }
})

test('asset explorer shows preview, name and creation date then confirms a choice', { concurrency: false }, async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { AssetExplorerDialog } = await import('../src/components/common/AssetExplorerDialog.tsx')
  const chosen: string[] = []
  const items = [
    {
      name: 'hero-running-aaaaaa.glb',
      type: 'model3d' as const,
      mode: null,
      size: 12,
      created_at: 1_725_000_000,
      url: '/api/v1/file/hero-running-aaaaaa.glb',
      thumbnail_url: '/api/v1/file/hero-running-aaaaaa.png',
    },
    {
      name: 'hero-walking-bbbbbb.glb',
      type: 'model3d' as const,
      mode: null,
      size: 14,
      created_at: 1_725_086_400,
      url: '/api/v1/file/hero-walking-bbbbbb.glb',
      thumbnail_url: '/api/v1/file/hero-walking-bbbbbb.png',
    },
  ]
  try {
    render(
      <AssetExplorerDialog
        open
        title="Choose a GLB"
        items={items}
        onClose={() => undefined}
        onChoose={item => { if (item) chosen.push(item.name) }}
      />,
    )
    assert.ok(screen.getByTestId('asset-explorer'))
    assert.ok(screen.getByText('Select an asset to preview it.'))
    fireEvent.click(screen.getByTitle('hero-walking-bbbbbb.glb'))
    assert.match(screen.getByText(/Created /).textContent || '', /Created /)
    fireEvent.click(screen.getByRole('button', { name: 'Choose' }))
    assert.deepEqual(chosen, ['hero-walking-bbbbbb.glb'])
  } finally {
    cleanup()
  }
})

test('asset explorer can cancel without choosing', { concurrency: false }, async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { AssetExplorerDialog } = await import('../src/components/common/AssetExplorerDialog.tsx')
  let closed = false
  const chosen: string[] = []
  try {
    render(
      <AssetExplorerDialog
        open
        title="Choose media"
        items={[{
          name: 'plate.png', type: 'image', mode: null, size: 2, created_at: 1_700_000_000,
          url: '/api/v1/file/plate.png', thumbnail_url: '/api/v1/file/plate.png',
        }]}
        onClose={() => { closed = true }}
        onChoose={item => { if (item) chosen.push(item.name) }}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    assert.equal(closed, true)
    assert.deepEqual(chosen, [])
  } finally {
    cleanup()
  }
})

function glb(name: string, created_at: number) {
  return {
    name, type: 'model3d' as const, mode: null, size: 12, created_at,
    url: `/api/v1/file/${name}`, thumbnail_url: `/api/v1/file/${name}.png`,
  }
}

test('double-click does not confirm and the first card is not preselected', { concurrency: false }, async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { AssetExplorerDialog } = await import('../src/components/common/AssetExplorerDialog.tsx')
  const chosen: string[] = []
  try {
    render(
      <AssetExplorerDialog
        open
        title="Choose a GLB"
        items={[glb('hero-running-aaaaaa.glb', 1_725_000_000)]}
        onClose={() => undefined}
        onChoose={item => { if (item) chosen.push(item.name) }}
      />,
    )
    assert.equal((screen.getByRole('button', { name: 'Choose' }) as HTMLButtonElement).disabled, true)
    fireEvent.doubleClick(screen.getByTitle('hero-running-aaaaaa.glb'))
    assert.deepEqual(chosen, [])
  } finally {
    cleanup()
  }
})

test('None confirms empty while Cancel does not, and search does not remount the choice', { concurrency: false }, async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { AssetExplorerDialog } = await import('../src/components/common/AssetExplorerDialog.tsx')
  const chosen: Array<string | null> = []
  const items = [
    glb('hero-running-aaaaaa.glb', 1_725_000_000),
    glb('hero-walking-bbbbbb.glb', 1_725_086_400),
  ]
  try {
    render(
      <AssetExplorerDialog
        open
        title="Choose a GLB"
        items={items}
        allowNone
        onClose={() => undefined}
        onChoose={item => { chosen.push(item ? item.name : null) }}
      />,
    )
    fireEvent.click(screen.getByTitle('hero-running-aaaaaa.glb'))
    fireEvent.change(screen.getByPlaceholderText('Search by name'), { target: { value: 'walking' } })
    assert.ok(screen.getByText(/The selected asset is hidden/))
    assert.equal((screen.getByRole('button', { name: 'Choose' }) as HTMLButtonElement).disabled, false)
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    assert.deepEqual(chosen, [])
    fireEvent.click(screen.getByRole('button', { name: 'None' }))
    assert.deepEqual(chosen, [null])
  } finally {
    cleanup()
  }
})

test('sort applies to the whole list before paging', { concurrency: false }, async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { AssetExplorerDialog } = await import('../src/components/common/AssetExplorerDialog.tsx')
  const items = Array.from({ length: 25 }, (_, index) => glb(
    `${String.fromCharCode(97 + (index % 26))}-${String(index).padStart(2, '0')}.glb`,
    1_700_000_000 + index,
  ))
  try {
    render(
      <AssetExplorerDialog
        open
        title="Choose a GLB"
        items={items}
        onClose={() => undefined}
        onChoose={() => undefined}
      />,
    )
    const newest = items[24].name
    assert.ok(screen.getByTitle(newest))
    fireEvent.change(screen.getByLabelText('Sort'), { target: { value: 'name_asc' } })
    assert.ok(screen.getByTitle(items[0].name))
    assert.equal(screen.queryByTitle(newest), null)
  } finally {
    cleanup()
  }
})

test('incompatible kinds cannot be confirmed', { concurrency: false }, async () => {
  const { render, screen, cleanup } = await import('@testing-library/react')
  const { AssetExplorerDialog } = await import('../src/components/common/AssetExplorerDialog.tsx')
  try {
    render(
      <AssetExplorerDialog
        open
        title="Choose audio"
        selectedName="plate.png"
        items={[{
          name: 'plate.png', type: 'image', mode: null, size: 2, created_at: 1_700_000_000,
          url: '/api/v1/file/plate.png', thumbnail_url: '/api/v1/file/plate.png',
        }]}
        constraints={{ kinds: ['audio'], maxCount: 1, optional: false }}
        onClose={() => undefined}
        onChoose={() => undefined}
      />,
    )
    assert.ok(screen.getByText('This asset type is not allowed here.'))
    assert.equal((screen.getByRole('button', { name: 'Choose' }) as HTMLButtonElement).disabled, true)
  } finally {
    cleanup()
  }
})

test('growing the item list does not wipe a provisional choice', { concurrency: false }, async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { AssetExplorerDialog } = await import('../src/components/common/AssetExplorerDialog.tsx')
  const first = [glb('hero-running-aaaaaa.glb', 1_725_000_000)]
  const extra = glb('hero-walking-bbbbbb.glb', 1_725_086_400)
  const props = {
    open: true,
    title: 'Choose a GLB',
    onClose: () => undefined,
    onChoose: () => undefined,
  }
  try {
    const view = render(<AssetExplorerDialog {...props} items={first} />)
    fireEvent.click(screen.getByTitle('hero-running-aaaaaa.glb'))
    view.rerender(<AssetExplorerDialog {...props} items={[...first, extra]} />)
    assert.equal((screen.getByRole('button', { name: 'Choose' }) as HTMLButtonElement).disabled, false)
    assert.ok(screen.getByTitle('hero-walking-bbbbbb.glb'))
  } finally {
    cleanup()
  }
})

test('homonymous files confirm the clicked url, not the first name match', { concurrency: false }, async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { AssetExplorerDialog } = await import('../src/components/common/AssetExplorerDialog.tsx')
  const chosen: string[] = []
  const items = [
    { ...glb('same.glb', 1), url: '/api/v1/file/a/same.glb', thumbnail_url: '/a.png' },
    { ...glb('same.glb', 2), url: '/api/v1/file/b/same.glb', thumbnail_url: '/b.png' },
  ]
  try {
    render(
      <AssetExplorerDialog
        open
        title="Choose a GLB"
        workspaceId="film"
        items={items}
        onClose={() => undefined}
        onChoose={item => { if (item) chosen.push(item.url) }}
      />,
    )
    fireEvent.click(screen.getAllByTitle('same.glb')[0])
    fireEvent.click(screen.getByRole('button', { name: 'Choose' }))
    assert.deepEqual(chosen, ['/api/v1/file/b/same.glb'])
  } finally {
    cleanup()
  }
})

test('workspace change, deletion and compatibility drop block confirm', { concurrency: false }, async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { AssetExplorerDialog } = await import('../src/components/common/AssetExplorerDialog.tsx')
  const item = glb('hero-running-aaaaaa.glb', 1_725_000_000)
  const chosen: string[] = []
  const props = {
    open: true,
    title: 'Choose a GLB',
    onClose: () => undefined,
    onChoose: (value: { name: string } | null) => { if (value) chosen.push(value.name) },
  }
  try {
    const view = render(<AssetExplorerDialog {...props} workspaceId="alpha" items={[item]} />)
    fireEvent.click(screen.getAllByTitle(item.name)[0])
    assert.equal((screen.getByRole('button', { name: 'Choose' }) as HTMLButtonElement).disabled, false)
    view.rerender(<AssetExplorerDialog {...props} workspaceId="beta" items={[item]} />)
    assert.equal((screen.getByRole('button', { name: 'Choose' }) as HTMLButtonElement).disabled, true)
    view.rerender(<AssetExplorerDialog {...props} workspaceId="alpha" items={[item]} />)
    fireEvent.click(screen.getAllByTitle(item.name)[0])
    view.rerender(<AssetExplorerDialog {...props} workspaceId="alpha" items={[]} />)
    assert.equal((screen.getByRole('button', { name: 'Choose' }) as HTMLButtonElement).disabled, true)
    view.rerender(<AssetExplorerDialog {...props} workspaceId="alpha" items={[item]} constraints={{ kinds: ['audio'], maxCount: 1, optional: false }} />)
    fireEvent.click(screen.getAllByTitle(item.name)[0])
    assert.equal((screen.getByRole('button', { name: 'Choose' }) as HTMLButtonElement).disabled, true)
    assert.deepEqual(chosen, [])
  } finally {
    cleanup()
  }
})
