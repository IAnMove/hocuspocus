import { useMemo, useRef, type PointerEvent as ReactPointerEvent } from 'react'
import { Lock } from 'lucide-react'
import { useComicStore } from './store'
import type {
  ComicElement,
  ComicImageElement,
  ComicPanelElement,
  ComicTextElement,
  ComicProject,
} from './types'

const FILTERS: Record<ComicImageElement['filter'], string | undefined> = {
  none: undefined,
  bw: 'grayscale(1) contrast(1.1)',
  sepia: 'sepia(.9) contrast(1.08)',
  contrast: 'contrast(1.35) saturate(1.2)',
  halftone: 'grayscale(.3) contrast(1.3)',
}

function TextView({ element }: { element: ComicTextElement }) {
  const bubble = element.bubble
  const radius = bubble === 'thought' ? '50%' : bubble === 'speech' ? '45%' : bubble === 'scream' ? '12%' : 4
  const clipPath = bubble === 'scream'
    ? 'polygon(50% 0%,61% 20%,78% 8%,80% 30%,100% 29%,84% 48%,100% 63%,78% 66%,80% 92%,60% 78%,48% 100%,40% 78%,18% 94%,20% 68%,0 64%,16% 48%,0 30%,21% 29%,20% 6%,40% 21%)'
    : undefined
  return (
    <div
      className="w-full h-full flex items-center justify-center px-3 py-2 whitespace-pre-wrap break-words overflow-hidden"
      style={{
        color: element.color,
        fontFamily: element.fontFamily,
        fontSize: element.fontSize,
        fontWeight: element.bold ? 800 : 500,
        fontStyle: element.italic ? 'italic' : 'normal',
        textAlign: element.align,
        lineHeight: 1.08,
        background: bubble === 'none' ? 'transparent' : element.bubbleBackground,
        border: bubble === 'none' ? undefined : `${element.bubbleStrokeWidth}px solid ${element.bubbleStrokeColor}`,
        borderRadius: radius,
        clipPath,
        textShadow: bubble === 'none' ? '0 1px 2px #fff, 0 0 2px #fff' : undefined,
      }}
    >
      {element.content}
    </div>
  )
}

function ImageView({ element }: { element: ComicImageElement }) {
  const asset = useComicStore(state => state.project.assets[element.assetId])
  if (!asset || asset.missing) {
    return (
      <div className="w-full h-full grid place-items-center bg-red-950/40 text-red-300 text-xs border border-red-500/40">
        Missing asset
      </div>
    )
  }
  return (
    <div className="w-full h-full overflow-hidden relative">
      <img
        src={asset.source}
        alt={asset.name}
        draggable={false}
        className="w-full h-full select-none pointer-events-none"
        style={{
          objectFit: element.objectFit,
          filter: FILTERS[element.filter],
          opacity: element.opacity ?? 1,
          transform: `${element.flipH ? 'scaleX(-1)' : ''} ${element.flipV ? 'scaleY(-1)' : ''}`,
        }}
      />
      {element.filter === 'halftone' && (
        <div
          className="absolute inset-0 pointer-events-none opacity-20"
          style={{ backgroundImage: 'radial-gradient(#000 1px, transparent 1px)', backgroundSize: '4px 4px' }}
        />
      )}
    </div>
  )
}

function ElementContent({ element }: { element: ComicElement }) {
  if (element.type === 'image') return <ImageView element={element} />
  if (element.type === 'text') return <TextView element={element} />
  return null
}

type DragState = {
  pointerId: number
  mode: 'move' | 'resize' | 'rotate'
  startX: number
  startY: number
  x: number
  y: number
  width: number
  height: number
  rotation: number
  snapshot: ComicProject
}

function ElementFrame({
  element,
  pageId,
  children,
}: {
  element: ComicElement
  pageId: string
  children: React.ReactNode
}) {
  const selected = useComicStore(state => state.selectedId === element.id)
  const zoom = useComicStore(state => state.zoom)
  const select = useComicStore(state => state.setSelected)
  const update = useComicStore(state => state.updateElement)
  const drag = useRef<DragState | null>(null)
  const frame = useRef<HTMLDivElement>(null)

  const start = (event: ReactPointerEvent, mode: DragState['mode']) => {
    event.stopPropagation()
    select(element.id)
    if (element.locked || event.button !== 0) return
    drag.current = {
      pointerId: event.pointerId,
      mode,
      startX: event.clientX,
      startY: event.clientY,
      x: element.x,
      y: element.y,
      width: element.width,
      height: element.height,
      rotation: element.rotation,
      snapshot: structuredClone(useComicStore.getState().project),
    }
    event.currentTarget.setPointerCapture(event.pointerId)
  }

  const move = (event: ReactPointerEvent) => {
    const current = drag.current
    if (!current || current.pointerId !== event.pointerId) return
    const dx = (event.clientX - current.startX) / zoom
    const dy = (event.clientY - current.startY) / zoom
    if (current.mode === 'move') {
      update(pageId, element.id, { x: current.x + dx, y: current.y + dy })
    } else if (current.mode === 'resize') {
      update(pageId, element.id, {
        width: Math.max(30, current.width + dx),
        height: Math.max(30, current.height + dy),
      })
    } else if (frame.current) {
      const rect = frame.current.getBoundingClientRect()
      const angle = Math.atan2(event.clientY - (rect.top + rect.height / 2), event.clientX - (rect.left + rect.width / 2))
      update(pageId, element.id, { rotation: Math.round((angle * 180 / Math.PI + 90) / 2) * 2 })
    }
  }

  const finish = (event: ReactPointerEvent) => {
    if (!drag.current || drag.current.pointerId !== event.pointerId) return
    const snapshot = drag.current.snapshot
    drag.current = null
    useComicStore.getState().commitSnapshot(snapshot)
  }

  return (
    <div
      ref={frame}
      data-comic-element={element.id}
      className={`absolute touch-none ${selected ? 'ring-2 ring-accent-blue ring-offset-1 ring-offset-transparent' : ''}`}
      style={{
        left: element.x,
        top: element.y,
        width: element.width,
        height: element.height,
        zIndex: element.zIndex,
        transform: `rotate(${element.rotation || 0}deg)`,
        transformOrigin: 'center',
        display: element.visible === false ? 'none' : undefined,
      }}
      onPointerDown={event => start(event, 'move')}
      onPointerMove={move}
      onPointerUp={finish}
      onPointerCancel={finish}
    >
      {children}
      {selected && element.locked && (
        <div className="absolute -top-6 left-0 bg-bg-secondary rounded p-1 text-yellow-400"><Lock size={12} /></div>
      )}
      {selected && !element.locked && (
        <>
          <button
            className="absolute -right-2 -bottom-2 w-4 h-4 rounded-full bg-white border-2 border-accent-blue cursor-se-resize"
            onPointerDown={event => start(event, 'resize')}
            title="Resize"
          />
          <button
            className="absolute left-1/2 -translate-x-1/2 -top-7 w-4 h-4 rounded-full bg-accent-blue border-2 border-white cursor-grab"
            onPointerDown={event => start(event, 'rotate')}
            title="Rotate"
          />
        </>
      )}
    </div>
  )
}

function PanelFrame({ panel, pageId, children }: {
  panel: ComicPanelElement
  pageId: string
  children: ComicElement[]
}) {
  const clipPath = panel.points
    ? `polygon(${panel.points.map(([x, y]) => `${x * 100}% ${y * 100}%`).join(',')})`
    : undefined
  return (
    <ElementFrame element={panel} pageId={pageId}>
      <div
        className="absolute inset-0 overflow-hidden"
        style={{
          background: panel.background,
          border: `${panel.borderWidth}px solid ${panel.borderColor}`,
          borderRadius: panel.borderRadius,
          clipPath,
        }}
      >
        {children.sort((a, b) => a.zIndex - b.zIndex).map(child => (
          <ElementFrame key={child.id} element={child} pageId={pageId}>
            <ElementContent element={child} />
          </ElementFrame>
        ))}
      </div>
    </ElementFrame>
  )
}

export function ComicCanvas() {
  const project = useComicStore(state => state.project)
  const pageId = useComicStore(state => state.currentPageId)
  const zoom = useComicStore(state => state.zoom)
  const select = useComicStore(state => state.setSelected)
  const page = project.pages.find(item => item.id === pageId)
  const { parents, loose } = useMemo(() => {
    if (!page) return { parents: [] as ComicPanelElement[], loose: [] as ComicElement[] }
    return {
      parents: page.elements.filter((el): el is ComicPanelElement => el.type === 'panel' && !el.parentId)
        .sort((a, b) => a.zIndex - b.zIndex),
      loose: page.elements.filter(el => !el.parentId && el.type !== 'panel').sort((a, b) => a.zIndex - b.zIndex),
    }
  }, [page])
  if (!page) return null

  return (
    <div
      className="relative shrink-0 shadow-2xl"
      style={{ width: page.width * zoom, height: page.height * zoom }}
      onPointerDown={() => select(null)}
    >
      <div
        id="maestro-comic-page"
        className="absolute origin-top-left overflow-hidden"
        style={{
          width: page.width,
          height: page.height,
          transform: `scale(${zoom})`,
          background: page.background,
        }}
      >
        {parents.map(panel => (
          <PanelFrame
            key={panel.id}
            panel={panel}
            pageId={page.id}
            children={page.elements.filter(element => element.parentId === panel.id)}
          />
        ))}
        {loose.map(element => (
          <ElementFrame key={element.id} element={element} pageId={page.id}>
            <ElementContent element={element} />
          </ElementFrame>
        ))}
        {project.pageNumbering.style !== 'none' && (
          <div className={`absolute bottom-3 right-4 z-[999] text-sm font-semibold ${
            project.pageNumbering.style === 'circle' ? 'w-8 h-8 rounded-full bg-black text-white grid place-items-center' : 'text-black'
          }`}>
            {project.pages.findIndex(item => item.id === page.id) + 1}
          </div>
        )}
      </div>
    </div>
  )
}
