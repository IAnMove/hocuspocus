import { useCallback, useEffect, useRef, useState } from 'react'
import { getComicPanels, type ComicPanelImage } from '../../api/montages'
import type { ClipExtra } from './comicEdits'

interface ClipRef { id: string }

/** One cached print per clip, loaded in batches as panels scroll into view. */
export function useComicPanels(input: {
  workspace: string
  file: string
  clips: ClipRef[]
  extras: Record<string, ClipExtra | undefined>
  revision: number
  onError: (message: string | null) => void
}): { imageFor: (id: string) => ComicPanelImage | undefined; observe: (id: string, element: Element | null) => void } {
  const [images, setImages] = useState<Map<string, ComicPanelImage>>(new Map())
  const imagesRef = useRef(images)
  const extrasRef = useRef(input.extras)
  const revisionRef = useRef(input.revision)
  const onErrorRef = useRef(input.onError)
  const nodes = useRef(new Map<string, Element>())
  const visible = useRef(new Set<string>())
  const inflight = useRef(new Set<string>())
  const generation = useRef(0)
  const observerRef = useRef<IntersectionObserver | null>(null)
  imagesRef.current = images
  extrasRef.current = input.extras
  revisionRef.current = input.revision
  onErrorRef.current = input.onError

  const keyFor = useCallback((id: string) => {
    const frame = extrasRef.current[id]?.comic?.frame
    return `${revisionRef.current}|${id}|${typeof frame === 'number' ? frame : 'auto'}`
  }, [])

  const load = useCallback(async (ids: string[], token: number, revision: number) => {
    const keyOf = (id: string) => {
      const frame = extrasRef.current[id]?.comic?.frame
      return `${revision}|${id}|${typeof frame === 'number' ? frame : 'auto'}`
    }
    const wanted = ids.filter(id => !imagesRef.current.has(keyOf(id)) && !inflight.current.has(keyOf(id)))
    for (let start = 0; start < wanted.length; start += 24) {
      if (token !== generation.current) return
      const batch = wanted.slice(start, start + 24)
      const frames: Record<string, number> = {}
      const keys: string[] = []
      for (const id of batch) {
        const frame = extrasRef.current[id]?.comic?.frame
        if (typeof frame === 'number') frames[id] = frame
        const key = keyOf(id)
        keys.push(key)
        inflight.current.add(key)
      }
      try {
        const result = await getComicPanels(input.workspace, input.file, batch, frames)
        if (token !== generation.current) return
        setImages(current => {
          const next = new Map(current)
          for (const panel of result.panels) {
            const frame = frames[panel.clip_id]
            next.set(`${revision}|${panel.clip_id}|${typeof frame === 'number' ? frame : 'auto'}`, panel)
          }
          return next
        })
      } catch (error) {
        onErrorRef.current((error as Error).message)
      } finally {
        for (const key of keys) inflight.current.delete(key)
      }
    }
  }, [input.file, input.workspace])

  const frameSig = input.clips.map(clip => `${clip.id}:${input.extras[clip.id]?.comic?.frame ?? ''}`).join('|')

  useEffect(() => {
    const token = ++generation.current
    const ids = [...visible.current]
    if (ids.length) void load(ids, token, input.revision)
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
      timer = window.setTimeout(() => { if (pending.size) void load([...pending], generation.current, revisionRef.current) }, 50)
    }, { rootMargin: '240px' })
    observerRef.current = observer
    for (const element of nodes.current.values()) observer.observe(element)
    return () => { window.clearTimeout(timer); observer.disconnect(); observerRef.current = null }
  }, [frameSig, input.file, input.revision, input.workspace, load])

  const observe = useCallback((id: string, element: Element | null) => {
    const previous = nodes.current.get(id)
    if (previous) observerRef.current?.unobserve(previous)
    if (!element) { nodes.current.delete(id); visible.current.delete(id); return }
    element.setAttribute('data-clip-id', id)
    nodes.current.set(id, element)
    observerRef.current?.observe(element)
  }, [])

  return { imageFor: id => images.get(keyFor(id)), observe }
}
