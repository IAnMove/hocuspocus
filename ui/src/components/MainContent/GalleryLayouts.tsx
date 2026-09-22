import { useMemo } from 'react'
import type { JSX } from 'react'
import { GalleryTile } from './GalleryTile'
import type { OutputFile } from '../../types'

const GAP = 12
const MIN_TILE = 190

/** Grid and mosaic layouts for the gallery. Kept out of the entry chunk —
 *  the one-up feed is what loads with the app, and these arrive when the
 *  reader actually asks for them. */
export default function GalleryLayouts({
  view, outputs, workspace, activeIndex, containerWidth, containerHeight, scrollTop, onOpen,
}: {
  view: 'grid' | 'masonry'
  outputs: OutputFile[]
  workspace: string
  activeIndex: number
  containerWidth: number
  containerHeight: number
  scrollTop: number
  onOpen: (index: number) => void
}) {
  const columns = Math.max(1, Math.floor((containerWidth + GAP) / (MIN_TILE + GAP)))
  const tile = Math.floor((containerWidth - GAP * (columns - 1)) / columns)
  const tileHeight = view === 'grid' ? tile : tile * 3 / 4
  const rowHeight = tileHeight + GAP

  // Both layouts reserve row sizes before decoding. Mosaic contains the whole
  // image in a landscape tile; Grid crops to a square. DOM order stays row-first.
  const grid = useMemo(() => {
    const totalRows = Math.ceil(outputs.length / columns)
    const overscan = 2
    const firstRow = Math.max(0, Math.floor(scrollTop / rowHeight) - overscan)
    const lastRow = Math.min(totalRows, Math.ceil((scrollTop + containerHeight) / rowHeight) + overscan)
    const cells: JSX.Element[] = []
    for (let row = firstRow; row < lastRow; row++) {
      for (let column = 0; column < columns; column++) {
        const index = row * columns + column
        const file = outputs[index]
        if (!file) break
        cells.push(
          <GalleryTile
            key={file.name}
            file={file}
            workspace={workspace}
            active={activeIndex === index}
            fixedAspect={view === 'grid'}
            onOpen={() => onOpen(index)}
            style={{
              position: 'absolute',
              top: row * rowHeight,
              left: column * (tile + GAP),
              width: tile,
              height: tileHeight,
            }}
          />
        )
      }
    }
    return { cells, height: totalRows * rowHeight }
  }, [view, outputs, columns, rowHeight, tile, tileHeight, scrollTop, containerHeight, activeIndex, workspace, onOpen])

  return <div className="relative" style={{ height: grid.height }}>{grid.cells}</div>
}
