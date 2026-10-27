import { useCallback, useEffect, useRef, useState } from 'react'
import { getComicPanels, type ComicDraftClip, type ComicPanelResult } from '../../api/montages'
import type { ClipExtra } from './comicEdits'

interface DraftClip { id: string; source: string; trimStart: number; trimEnd: number }

/** What a panel shows depends on the clip as it is in the editor now, so a replaced or trimmed clip reprints. */
export function comicPanelKey(workspace: string, clip: DraftClip, frame: number | undefined): string {
  return [workspace, clip.id, clip.source, clip.trimStart, clip.trimEnd, frame ?? 'auto'].join('|')
}

function draftClip(clip: DraftClip, frame: number | undefined): ComicDraftClip {
  const drafted: ComicDraftClip = { id: clip.id, source: clip.source, trimStart: clip.trimStart, trimEnd: clip.trimEnd }
  if (typeof frame === 'number') drafted.comic = { frame }
  return drafted
}

/** One cached print per clip, loaded in batches as panels scroll into view. */
export function useComicPanels(input: {
  workspace: string
  file: string
  clips: DraftClip[]
  extras: Record<string, ClipExtra | undefined>
  onError: (message: string | null) => void
}): { imageFor: (id: string) => ComicPanelResult | undefined; observe: (id: string, element: Element | null) => void } {
  const [images, setImages] = useState<Map<string, ComicPanelResult>>(new Map())
  const latest = useRef(input)
  const imagesRef = useRef(images)
  const nodes = useRef(new Map<string, Element>())
  const visible = useRef(new Set<string>())
  const inflight = useRef(new Set<string>())
  const observerRef = useRef<IntersectionObserver | null>(null)
  latest.current = input
  imagesRef.current = images

  const keyOf = useCallback((clip: DraftClip) =>
    comicPanelKey(latest.current.workspace, clip, latest.current.extras[clip.id]?.comic?.frame), [])

  const load = useCallback(async (ids: string[]) => {
    const { clips, extras, workspace, file } = latest.current
    const wanted = clips.filter(clip => ids.includes(clip.id)).map(clip => ({ clip, key: keyOf(clip) }))
      .filter(item => !imagesRef.current.has(item.key) && !inflight.current.has(item.key))
    for (let start = 0; start < wanted.length; start += 24) {
      const batch = wanted.slice(start, start + 24)
      batch.forEach(item => inflight.current.add(item.key))
      try {
        const result = await getComicPanels(workspace, file, batch.map(({ clip }) => draftClip(clip, extras[clip.id]?.comic?.frame)))
        setImages(current => {
          const next = new Map(current)
          result.panels.forEach((panel, index) => {
            if (batch[index]?.clip.id === panel.clip_id) next.set(batch[index].key, panel)
          })
          return next
        })
      } catch (error) {
        latest.current.onError((error as Error).message)
      } finally {
        batch.forEach(item => inflight.current.delete(item.key))
      }
    }
  }, [keyOf])

  const signature = input.clips.map(keyOf).join('\n')
  useEffect(() => {
    if (visible.current.size) void load([...visible.current])
  }, [signature, load])

  useEffect(() => {
    const pending = new Set<string>()
    let timer = 0
    const observer = new IntersectionObserver(entries => {
      for (const entry of entries) {
        const id = (entry.target as HTMLElement).dataset.clipId
        if (!id) continue
        if (entry.isIntersecting) { visible.current.add(id); pending.add(id) }
        else { visible.current.delete(id); pending.delete(id) }
      }
      window.clearTimeout(timer)
      timer = window.setTimeout(() => {
        if (!pending.size) return
        void load([...pending])
        pending.clear()
      }, 50)
    }, { rootMargin: '240px' })
    observerRef.current = observer
    for (const element of nodes.current.values()) observer.observe(element)
    return () => { window.clearTimeout(timer); observer.disconnect(); observerRef.current = null }
  }, [load])

  const observe = useCallback((id: string, element: Element | null) => {
    const previous = nodes.current.get(id)
    if (previous) observerRef.current?.unobserve(previous)
    if (!element) { nodes.current.delete(id); visible.current.delete(id); return }
    element.setAttribute('data-clip-id', id)
    nodes.current.set(id, element)
    observerRef.current?.observe(element)
  }, [])

  const imageFor = (id: string) => {
    const clip = input.clips.find(item => item.id === id)
    return clip ? images.get(keyOf(clip)) : undefined
  }
  return { imageFor, observe }
}
