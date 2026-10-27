import { useEffect, useState, type ReactNode } from 'react'
import { useUiTranslation } from '../../i18n'
import { workbenchLayout, type WorkbenchLayout } from './layout'

export type WorkbenchProps = {
  topBar?: ReactNode
  outline?: ReactNode
  viewport: ReactNode
  inspector?: ReactNode
  transport?: ReactNode
  /** Viewport width in pixels. Omit it to follow the window. */
  width?: number
}

function useViewportWidth(override?: number) {
  const [width, setWidth] = useState(override ?? 1280)
  useEffect(() => {
    if (override != null) {
      setWidth(override)
      return
    }
    const read = () => setWidth(window.innerWidth)
    read()
    window.addEventListener('resize', read)
    return () => window.removeEventListener('resize', read)
  }, [override])
  return width
}

function PanelToggle({ pressed, label, testId, onClick }: {
  pressed: boolean
  label: string
  testId: string
  onClick: () => void
}) {
  return (
    <button
      type="button"
      data-testid={testId}
      aria-pressed={pressed}
      onClick={onClick}
      className="inline-flex min-h-10 shrink-0 items-center rounded-lg border border-border px-3 text-xs text-text-primary"
    >
      {label}
    </button>
  )
}

/**
 * Shared work desk: top bar, scrolling side panels, a viewport that keeps the free space,
 * and a transport bar that sits under the viewport. It knows nothing about 3D.
 */
export function Workbench({ topBar, outline, viewport, inspector, transport, width }: WorkbenchProps) {
  const { t } = useUiTranslation('workbench')
  const measured = useViewportWidth(width)
  const layout: WorkbenchLayout = workbenchLayout(measured)
  const [outlineCollapsed, setOutlineCollapsed] = useState(false)
  const [inspectorCollapsed, setInspectorCollapsed] = useState(false)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const stacked = layout === 'stack'
  const drawer = layout === 'drawer'
  const outlineOpen = !outlineCollapsed
  const inspectorOpen = drawer ? drawerOpen : !inspectorCollapsed
  const outlineLabel = outlineCollapsed ? t('expandOutline') : t('collapseOutline')
  const inspectorLabel = inspectorOpen ? (drawer ? t('closeInspector') : t('collapseInspector')) : (drawer ? t('openInspector') : t('expandInspector'))

  const closeInspector = () => {
    if (drawer) setDrawerOpen(false)
    else setInspectorCollapsed(true)
  }
  const toggleInspector = () => {
    if (drawer) setDrawerOpen(open => !open)
    else setInspectorCollapsed(collapsed => !collapsed)
  }

  return (
    <div
      data-testid="workbench"
      data-layout={layout}
      className="relative flex h-full min-h-0 w-full flex-col overflow-hidden bg-bg-primary"
    >
      <header className="flex shrink-0 flex-nowrap items-center gap-2 border-b border-border px-2 py-2">
        <PanelToggle
          pressed={outlineOpen}
          label={outlineLabel}
          testId="workbench-toggle-outline"
          onClick={() => setOutlineCollapsed(collapsed => !collapsed)}
        />
        <div data-slot="topBar" className="min-w-0 flex-1">{topBar}</div>
        <PanelToggle
          pressed={inspectorOpen}
          label={inspectorLabel}
          testId="workbench-toggle-inspector"
          onClick={toggleInspector}
        />
      </header>
      <div className={`flex min-h-0 flex-1 ${stacked ? 'flex-col overflow-y-auto' : 'flex-row overflow-hidden'}`}>
        <aside
          data-slot="outline"
          aria-label={t('outline')}
          hidden={!outlineOpen}
          className={outlineOpen
            ? `min-h-0 shrink-0 overflow-y-auto border-border ${stacked ? 'max-h-[40vh] w-full border-b' : 'w-64 border-r'}`
            : 'hidden'}
        >
          {outlineOpen ? outline : null}
        </aside>
        <div
          data-slot="viewport"
          aria-label={t('viewport')}
          className={`min-h-0 min-w-0 flex-1 overflow-hidden ${stacked ? 'min-h-[16rem]' : ''}`}
        >
          {viewport}
        </div>
        {!drawer && (
          <aside
            data-slot="inspector"
            aria-label={t('inspector')}
            hidden={!inspectorOpen}
            className={inspectorOpen
              ? `min-h-0 shrink-0 overflow-y-auto border-border ${stacked ? 'max-h-[40vh] w-full border-t' : 'w-80 border-l'}`
              : 'hidden'}
          >
            {inspectorOpen ? inspector : null}
          </aside>
        )}
      </div>
      {drawer && inspectorOpen && (
        <div className="absolute inset-0 z-30 flex justify-end bg-black/40">
          <button type="button" aria-hidden="true" tabIndex={-1} className="min-w-0 flex-1" onClick={closeInspector} />
          <aside
            data-slot="inspector"
            aria-label={t('inspector')}
            className="h-full w-80 max-w-[85vw] overflow-y-auto border-l border-border bg-bg-primary shadow-2xl"
          >
            {inspector}
          </aside>
        </div>
      )}
      <footer data-slot="transport" aria-label={t('transport')} className="shrink-0 border-t border-border">
        {transport}
      </footer>
    </div>
  )
}
