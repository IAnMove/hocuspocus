import type { JSX } from 'react'
import { GalleryTile } from './GalleryTile'
import type { BlockRange, GalleryLayout } from './mediaGalleryLayout'
import type { OutputFile } from '../../types'

/** Grid and mosaic cells for the visible rows. Kept out of the entry chunk —
 *  the one-up feed is what loads with the app, and these arrive when the
 *  reader actually asks for them. The geometry comes from the shared gallery
 *  layout, so every cell is placed before its image decodes. */
export default function GalleryLayouts({
  layout, range, outputs, workspace, activeIndex, onOpen,
}: {
  layout: GalleryLayout
  range: BlockRange
  outputs: OutputFile[]
  workspace: string
  activeIndex: number
  onOpen: (index: number) => void
}) {
  const cells: JSX.Element[] = []
  for (let row = range.first; row <= range.last; row++) {
    const block = layout.blocks[row]
    if (!block) continue
    for (const cell of block.cells) {
      const file = outputs[cell.index]
      if (!file) continue
      cells.push(
        <GalleryTile
          key={file.name}
          file={file}
          workspace={workspace}
          index={cell.index}
          active={activeIndex === cell.index}
          cover={layout.view === 'grid'}
          top={block.top}
          left={cell.left}
          width={cell.width}
          height={cell.height}
          onOpen={onOpen}
        />
      )
    }
  }
  return <>{cells}</>
}
