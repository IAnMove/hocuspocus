import { useMemo, useRef, type PointerEvent as ReactPointerEvent, type WheelEvent as ReactWheelEvent } from 'react'
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
  posterize: 'contrast(1.8) saturate(1.4)',
  halftone: 'grayscale(.3) contrast(1.3)',
}

function TextView({ element }: { element: ComicTextElement }) {
  const bubble = element.bubble
  const radius = bubble === 'thought' || bubble === 'ellipse' || bubble === 'cloud'
    ? '50%'
    : bubble === 'speech' ? '38%' : bubble === 'rect' ? 16 : bubble === 'scream' || bubble === 'electric' || bubble === 'burst' ? '12%' : 4
  const clipPath = bubble === 'scream' || bubble === 'electric' || bubble === 'burst'
    ? 'polygon(50% 0%,61% 20%,78% 8%,80% 30%,100% 29%,84% 48%,100% 63%,78% 66%,80% 92%,60% 78%,48% 100%,40% 78%,18% 94%,20% 68%,0 64%,16% 48%,0 30%,21% 29%,20% 6%,40% 21%)'
    : undefined
  const effectColor = element.textEffectColor ?? '#111111'
  const textShadow = element.textEffect === 'extrude'
    ? `2px 2px ${effectColor}, 4px 4px ${effectColor}, 6px 6px ${effectColor}`
    : element.textEffect === 'glow'
      ? `0 0 5px ${effectColor}, 0 0 12px ${effectColor}`
      : element.textEffect === 'shadow'
        ? `3px 4px 0 ${effectColor}`
        : bubble === 'none' ? '0 1px 2px #fff, 0 0 2px #fff' : undefined
  return (
    <div
      className="relative w-full h-full flex items-center justify-center whitespace-pre-wrap break-words overflow-hidden"
      style={{
        fontFamily: element.fontFamily,
        fontSize: element.fontSize,
        fontWeight: element.bold ? 800 : 500,
        fontStyle: element.italic ? 'italic' : 'normal',
        textAlign: element.align,
        lineHeight: element.lineHeight ?? 1.08,
        letterSpacing: element.letterSpacing ?? 0,
        padding: element.bubblePadding ?? 12,
        background: bubble === 'none' ? 'transparent' : element.bubbleBackground,
        border: bubble === 'none' ? undefined : `${element.bubbleStrokeWidth}px ${element.bubbleStrokeStyle === 'dashed' ? 'dashed' : 'solid'} ${element.bubbleStrokeColor}`,
        borderRadius: radius,
        clipPath,
        boxShadow: element.bubbleShadow ? '0 8px 16px #0006' : undefined,
      }}
    >
      <span style={{
        color: element.textFill === 'gradient' ? 'transparent' : element.color,
        backgroundImage: element.textFill === 'gradient'
          ? `linear-gradient(${element.gradientStart ?? '#fff45c'}, ${element.gradientEnd ?? '#ff7a00'})`
          : undefined,
        backgroundClip: element.textFill === 'gradient' ? 'text' : undefined,
        WebkitBackgroundClip: element.textFill === 'gradient' ? 'text' : undefined,
        WebkitTextStroke: (element.textStrokeWidth ?? 0) > 0
          ? `${element.textStrokeWidth}px ${element.textStrokeColor ?? '#111111'}`
          : undefined,
        paintOrder: 'stroke fill',
        textShadow,
      }}>{element.content}</span>
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
  mode: 'move' | 'rotate' | 'nw' | 'n' | 'ne' | 'e' | 'se' | 's' | 'sw' | 'w'
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
  const snapEnabled = useComicStore(state => state.snapEnabled)
  const drag = useRef<DragState | null>(null)
  const frame = useRef<HTMLDivElement>(null)
  const wheelSnapshot = useRef<ComicProject | null>(null)
  const wheelTimer = useRef<number | null>(null)

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
    const snap = (value: number) => snapEnabled ? Math.round(value / 10) * 10 : value
    if (current.mode === 'move') {
      update(pageId, element.id, { x: snap(current.x + dx), y: snap(current.y + dy) })
    } else if (current.mode !== 'rotate') {
      let x = current.x
      let y = current.y
      let width = current.width
      let height = current.height
      if (current.mode.includes('e')) width = current.width + dx
      if (current.mode.includes('s')) height = current.height + dy
      if (current.mode.includes('w')) {
        width = current.width - dx
        x = current.x + dx
      }
      if (current.mode.includes('n')) {
        height = current.height - dy
        y = current.y + dy
      }
      if (width < 30) {
        if (current.mode.includes('w')) x = current.x + current.width - 30
        width = 30
      }
      if (height < 30) {
        if (current.mode.includes('n')) y = current.y + current.height - 30
        height = 30
      }
      update(pageId, element.id, {
        x: snap(x),
        y: snap(y),
        width: snap(width),
        height: snap(height),
      })
    } else if (frame.current) {
      const rect = frame.current.getBoundingClientRect()
      const angle = Math.atan2(event.clientY - (rect.top + rect.height / 2), event.clientX - (rect.left + rect.width / 2))
      update(pageId, element.id, { rotation: Math.round((angle * 180 / Math.PI + 90) / 2) * 2 })
    }
  }

  const finish = (event: ReactPointerEvent) => {
    if (!drag.current || drag.current.pointerId !== event.pointerId) return
    const { snapshot, mode } = drag.current
    drag.current = null
    if (mode === 'move' && (element.type === 'image' || element.type === 'text')) {
      useComicStore.getState().reparentElement(pageId, element.id)
    }
    useComicStore.getState().commitSnapshot(snapshot)
  }
  const scaleImage = (event: ReactWheelEvent) => {
    if (!event.ctrlKey || element.type !== 'image' || !selected || element.locked) return
    event.preventDefault()
    event.stopPropagation()
    if (!wheelSnapshot.current) wheelSnapshot.current = structuredClone(useComicStore.getState().project)
    const factor = event.deltaY < 0 ? 1.05 : 1 / 1.05
    const width = Math.max(30, element.width * factor)
    const height = Math.max(30, element.height * factor)
    update(pageId, element.id, {
      width,
      height,
      x: element.x + (element.width - width) / 2,
      y: element.y + (element.height - height) / 2,
    })
    if (wheelTimer.current) window.clearTimeout(wheelTimer.current)
    wheelTimer.current = window.setTimeout(() => {
      if (wheelSnapshot.current) useComicStore.getState().commitSnapshot(wheelSnapshot.current)
      wheelSnapshot.current = null
      wheelTimer.current = null
    }, 600)
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
      onWheel={scaleImage}
    >
      {children}
      {selected && element.locked && (
        <div className="absolute -top-6 left-0 bg-bg-secondary rounded p-1 text-yellow-400"><Lock size={12} /></div>
      )}
      {selected && !element.locked && (
        <>
          {([
            ['nw', '-left-2 -top-2 cursor-nw-resize'],
            ['n', 'left-1/2 -translate-x-1/2 -top-2 cursor-n-resize'],
            ['ne', '-right-2 -top-2 cursor-ne-resize'],
            ['e', '-right-2 top-1/2 -translate-y-1/2 cursor-e-resize'],
            ['se', '-right-2 -bottom-2 cursor-se-resize'],
            ['s', 'left-1/2 -translate-x-1/2 -bottom-2 cursor-s-resize'],
            ['sw', '-left-2 -bottom-2 cursor-sw-resize'],
            ['w', '-left-2 top-1/2 -translate-y-1/2 cursor-w-resize'],
          ] as const).map(([direction, position]) => (
            <button
              key={direction}
              className={`absolute ${position} z-[1100] size-3 rounded-full border-2 border-accent-blue bg-white`}
              onPointerDown={event => start(event, direction)}
              title={`Resize ${direction}`}
            />
          ))}
          <button
            className="absolute left-1/2 -translate-x-1/2 -top-8 z-[1100] w-4 h-4 rounded-full bg-accent-blue border-2 border-white cursor-grab"
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
  const selected = useComicStore(state => state.selectedId === panel.id)
  const zoom = useComicStore(state => state.zoom)
  const update = useComicStore(state => state.updateElement)
  const vertexDrag = useRef<{
    pointerId: number
    index: number
    startX: number
    startY: number
    points: [number, number][]
    snapshot: ComicProject
  } | null>(null)
  const clipPath = panel.points
    ? `polygon(${panel.points.map(([x, y]) => `${x * 100}% ${y * 100}%`).join(',')})`
    : undefined
  const startVertex = (event: ReactPointerEvent, index: number) => {
    if (!panel.points) return
    event.stopPropagation()
    vertexDrag.current = {
      pointerId: event.pointerId,
      index,
      startX: event.clientX,
      startY: event.clientY,
      points: panel.points.map(point => [...point] as [number, number]),
      snapshot: structuredClone(useComicStore.getState().project),
    }
    event.currentTarget.setPointerCapture(event.pointerId)
  }
  const moveVertex = (event: ReactPointerEvent) => {
    const drag = vertexDrag.current
    if (!drag || drag.pointerId !== event.pointerId) return
    const points = drag.points.map(point => [...point] as [number, number])
    points[drag.index] = [
      Math.max(0, Math.min(1, points[drag.index][0] + (event.clientX - drag.startX) / (panel.width * zoom))),
      Math.max(0, Math.min(1, points[drag.index][1] + (event.clientY - drag.startY) / (panel.height * zoom))),
    ]
    update(pageId, panel.id, { points })
  }
  const finishVertex = (event: ReactPointerEvent) => {
    const drag = vertexDrag.current
    if (!drag || drag.pointerId !== event.pointerId) return
    vertexDrag.current = null
    useComicStore.getState().commitSnapshot(drag.snapshot)
  }
  return (
    <ElementFrame element={panel} pageId={pageId}>
      <div
        className="absolute inset-0 overflow-hidden"
        style={{
          background: panel.background,
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
      {panel.points ? (
        <svg
          className="absolute inset-0 size-full pointer-events-none z-[999]"
          viewBox={`0 0 ${panel.width} ${panel.height}`}
          preserveAspectRatio="none"
        >
          <polygon
            points={panel.points.map(([x, y]) => `${x * panel.width},${y * panel.height}`).join(' ')}
            fill="none"
            stroke={panel.borderColor}
            strokeWidth={panel.borderWidth}
            strokeLinejoin="miter"
          />
        </svg>
      ) : (
        <div
          className="absolute inset-0 pointer-events-none z-[999]"
          style={{
            border: `${panel.borderWidth}px solid ${panel.borderColor}`,
            borderRadius: panel.borderRadius,
          }}
        />
      )}
      {selected && panel.points?.map(([x, y], index) => (
        <button
          key={index}
          className="absolute z-[1200] size-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white bg-emerald-500 cursor-move"
          style={{ left: `${x * 100}%`, top: `${y * 100}%` }}
          title="Drag polygon vertex"
          onPointerDown={event => startVertex(event, index)}
          onPointerMove={moveVertex}
          onPointerUp={finishVertex}
          onPointerCancel={finishVertex}
        />
      ))}
    </ElementFrame>
  )
}

export function ComicCanvas() {
  const project = useComicStore(state => state.project)
  const pageId = useComicStore(state => state.currentPageId)
  const zoom = useComicStore(state => state.zoom)
  const snapEnabled = useComicStore(state => state.snapEnabled)
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
          backgroundImage: snapEnabled
            ? 'linear-gradient(#00000012 1px, transparent 1px), linear-gradient(90deg, #00000012 1px, transparent 1px)'
            : undefined,
          backgroundSize: snapEnabled ? '10px 10px' : undefined,
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
