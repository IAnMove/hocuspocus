import { useCallback, useMemo, useRef, useState } from 'react'
import { useUiTranslation } from '../../i18n'
import type { OutputFile } from '../../types'
import { runGalleryBatch, type GalleryBatchAction } from './galleryBatch'

const EMPTY: ReadonlySet<string> = new Set()

/** Multi-select for the dense views: pick by tap, extend with shift-click,
 *  start with a touch long-press, and apply one action to every pick. Picks
 *  are output names, so they survive rows moving as outputs load. */
export function useGallerySelection(outputs: OutputFile[]) {
  const { t } = useUiTranslation('activity')
  const [selecting, setSelecting] = useState(false)
  const [picked, setPicked] = useState<ReadonlySet<string>>(EMPTY)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const anchor = useRef<number | null>(null)

  const clear = useCallback(() => {
    setSelecting(false)
    setPicked(EMPTY)
    setError(null)
    anchor.current = null
  }, [])

  const start = useCallback(() => {
    setSelecting(true)
    setError(null)
  }, [])

  const pick = useCallback((index: number, range: boolean) => {
    const file = outputs[index]
    if (!file) return
    setError(null)
    // Read the range start now: the updater runs after the anchor moves.
    const start = anchor.current
    setPicked(current => {
      const next = new Set(current)
      if (range && start != null) {
        const [from, to] = start < index ? [start, index] : [index, start]
        for (let at = from; at <= to; at++) if (outputs[at]) next.add(outputs[at].name)
      } else if (next.has(file.name)) {
        next.delete(file.name)
      } else {
        next.add(file.name)
      }
      return next
    })
    anchor.current = index
  }, [outputs])

  const longPress = useCallback((index: number) => {
    const file = outputs[index]
    if (!file) return
    setSelecting(true)
    setError(null)
    setPicked(new Set([file.name]))
    anchor.current = index
  }, [outputs])

  const selectAll = useCallback(() => setPicked(new Set(outputs.map(file => file.name))), [outputs])

  const apply = useCallback(async (action: GalleryBatchAction) => {
    const files = outputs.filter(file => picked.has(file.name))
    if (!files.length) return
    setBusy(true)
    setError(null)
    try {
      const { failed } = await runGalleryBatch(action, files)
      if (failed.length) {
        setPicked(new Set(failed))
        setError(t('selection.failed', { names: failed.slice(0, 3).join(', ') + (failed.length > 3 ? '…' : '') }))
      } else if (action.kind === 'favorite') {
        setPicked(EMPTY)
      } else {
        clear()
      }
    } finally {
      setBusy(false)
    }
  }, [outputs, picked, clear, t])

  // Exactly two picked images can be opened side by side.
  const comparePair = useMemo(() => {
    const files = outputs.filter(file => picked.has(file.name))
    return files.length === 2 && files.every(file => file.type === 'image') ? [files[0].name, files[1].name] as const : null
  }, [outputs, picked])

  return { selecting, picked, busy, error, start, clear, pick, longPress, selectAll, apply, comparePair }
}
