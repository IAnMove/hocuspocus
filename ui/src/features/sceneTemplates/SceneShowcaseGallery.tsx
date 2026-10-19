import { useEffect, useMemo, useRef, useState } from 'react'
import type { Scene } from '../../types'
import i18n, { useUiTranslation } from '../../i18n'
import { parseSceneFile } from '../../lib/sceneFile'
import { MAX_SCENE_JSON_BYTES, parseShowcaseManifest, type ShowcaseFileReference, type ShowcaseItem, type ShowcaseManifest } from './showcaseManifest'

export interface SceneShowcaseGalleryProps {
  manifest: ShowcaseManifest
  onOpenScene: (scene: Scene) => void
}

type ManifestCheck = { manifest: ShowcaseManifest | null; error: string }

function errorText(reason: unknown): string {
  return reason instanceof Error ? reason.message : i18n.t('scene3d:templateErrors.openFailed')
}

async function sha256(bytes: ArrayBuffer): Promise<string> {
  if (!globalThis.crypto?.subtle) throw new Error(i18n.t('scene3d:templateErrors.shaNeedsLoopback'))
  const digest = await globalThis.crypto.subtle.digest('SHA-256', bytes)
  return Array.from(new Uint8Array(digest), value => value.toString(16).padStart(2, '0')).join('')
}

function rejectOversizedSceneJson(): never {
  throw new Error(i18n.t('scene3d:templateErrors.sceneJsonTooLarge'))
}

/** Reads a scene response with a hard cap, including responses without Content-Length. */
async function readSceneBytes(response: Response): Promise<ArrayBuffer> {
  const declaredLength = response.headers.get('content-length')
  if (declaredLength !== null) {
    const length = Number(declaredLength)
    if (!Number.isSafeInteger(length) || length < 0) throw new Error(i18n.t('scene3d:templateErrors.invalidContentLength'))
    if (length > MAX_SCENE_JSON_BYTES) rejectOversizedSceneJson()
  }
  if (!response.body) {
    const bytes = await response.arrayBuffer()
    if (bytes.byteLength > MAX_SCENE_JSON_BYTES) rejectOversizedSceneJson()
    return bytes
  }
  const reader = response.body.getReader()
  const chunks: Uint8Array[] = []
  let total = 0
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      if (!value) continue
      if (value.byteLength > MAX_SCENE_JSON_BYTES - total) {
        await reader.cancel().catch(() => undefined)
        rejectOversizedSceneJson()
      }
      chunks.push(value)
      total += value.byteLength
    }
  } finally {
    reader.releaseLock()
  }
  const bytes = new Uint8Array(total)
  let offset = 0
  for (const chunk of chunks) {
    bytes.set(chunk, offset)
    offset += chunk.byteLength
  }
  return bytes.buffer
}

/** Loads the exact stored JSON snapshot; it never compiles a scene from the card. */
async function loadShowcaseScene(reference: ShowcaseFileReference, signal?: AbortSignal): Promise<Scene> {
  if (reference.bytes > MAX_SCENE_JSON_BYTES) rejectOversizedSceneJson()
  const response = await fetch(reference.url, { cache: 'no-store', redirect: 'error', signal })
  if (!response.ok) throw new Error(i18n.t('scene3d:templateErrors.downloadFailed', { status: response.status }))
  if (response.url) {
    const expected = new URL(reference.url, typeof window === 'undefined' ? 'http://localhost' : window.location.origin)
    const actual = new URL(response.url, expected)
    if (actual.origin !== expected.origin || actual.pathname !== expected.pathname || actual.search !== expected.search || actual.hash !== expected.hash) {
      throw new Error(i18n.t('scene3d:templateErrors.responseChanged'))
    }
  }
  const bytes = await readSceneBytes(response)
  if (bytes.byteLength !== reference.bytes) throw new Error(i18n.t('scene3d:templateErrors.byteMismatch', { actual: bytes.byteLength, expected: reference.bytes }))
  const actualHash = await sha256(bytes)
  if (actualHash !== reference.sha256) throw new Error(i18n.t('scene3d:templateErrors.hashMismatch'))
  const scene = parseSceneFile(new TextDecoder().decode(bytes))
  if (reference.sceneName !== scene.name) throw new Error(i18n.t('scene3d:templateErrors.semanticMismatch', { expected: reference.sceneName, actual: scene.name }))
  if (scene.generationPolicy !== 'provided_only') throw new Error(i18n.t('scene3d:templateErrors.missingPolicy'))
  return scene
}

function Preview({ item, failed, onError }: { item: ShowcaseItem; failed: boolean; onError: () => void }) {
  const { t } = useUiTranslation('scene3d')
  if (failed) return <div className="flex h-full items-center justify-center bg-slate-950 px-4 text-center text-xs text-amber-200">{t('templateErrors.previewNotRendered')}</div>
  if (!item.poster) return <div className="flex h-full items-center justify-center bg-slate-950 px-4 text-center text-xs text-text-muted">{t('templateErrors.noPoster')}</div>
  return <img src={item.poster.url} alt={t('templateErrors.posterAlt', { title: item.title })} className="h-full w-full object-cover" onError={onError} />
}

function MediaCard({
  item,
  active,
  posterFailed,
  mediaFailed,
  busy,
  onPlay,
  onPosterError,
  onMediaError,
}: {
  item: ShowcaseItem
  active: boolean
  posterFailed: boolean
  mediaFailed: boolean
  busy: boolean
  onPlay: () => void
  onPosterError: () => void
  onMediaError: () => void
}) {
  const { t } = useUiTranslation('scene3d')
  return <div className="relative aspect-video overflow-hidden rounded-lg border border-border bg-black">
    {active
      ? <video controls preload="metadata" playsInline src={item.video.url} aria-label={t('templateErrors.fullVideoAria', { title: item.title })} onError={onMediaError} className="h-full w-full object-contain" />
      : <button type="button" onClick={onPlay} disabled={busy} className="group relative h-full w-full text-left disabled:cursor-wait disabled:opacity-70" aria-label={t('templateErrors.watchFullVideoAria', { title: item.title })}>
        <Preview item={item} failed={posterFailed} onError={onPosterError} />
        <span className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 whitespace-nowrap rounded-xl bg-cyan-300 px-5 py-4 text-center text-sm font-bold text-slate-950 shadow-xl group-hover:bg-cyan-200">{t('templateErrors.watchFullVideo')}</span>
      </button>}
    {mediaFailed && <p role="alert" className="absolute inset-x-0 bottom-0 bg-black/90 p-2 text-center text-xs text-amber-200">{t('templateErrors.videoNotRendered')}</p>}
  </div>
}

function ShowcaseCard({
  item,
  activeVideoId,
  posterErrors,
  mediaErrors,
  busy,
  expanded,
  onPlay,
  onPosterError,
  onMediaError,
  onOpenScene,
  onToggleShots,
}: {
  item: ShowcaseItem
  activeVideoId: string | null
  posterErrors: Record<string, boolean>
  mediaErrors: Record<string, boolean>
  busy: string | null
  expanded: boolean
  onPlay: () => void
  onPosterError: () => void
  onMediaError: () => void
  onOpenScene: (reference: ShowcaseFileReference, label: string) => void
  onToggleShots: () => void
}) {
  const { t } = useUiTranslation('scene3d')
  const sceneLabel = item.kind === 'music_video' ? t('templateErrors.openSavedScene') : t('templateErrors.openScene')
  return <article data-showcase-id={item.id} className="overflow-hidden rounded-xl border border-border bg-bg-secondary/70 shadow-lg">
    <div className="border-b border-border p-4">
      <div className="flex flex-wrap items-start gap-2">
        <div className="min-w-0 flex-1"><h3 className="text-base font-semibold text-text-primary">{item.title}</h3><p className="mt-1 text-[10px] text-text-muted">{t('templateErrors.cardMeta', { id: item.id, model: item.imageModel })}</p></div>
        <span className="rounded-full border border-amber-300/40 bg-amber-300/10 px-2 py-1 text-[10px] text-amber-100">{t('templateErrors.pending')}</span>
      </div>
      <p className="mt-2 text-xs leading-5 text-text-secondary">{item.description}</p>
    </div>
    <div className="p-3"><MediaCard item={item} active={activeVideoId === item.id} posterFailed={posterErrors[item.id] === true} mediaFailed={mediaErrors[item.id] === true} busy={busy !== null} onPlay={onPlay} onPosterError={onPosterError} onMediaError={onMediaError} /></div>
    <div className="space-y-3 p-4 pt-0">
      <div><p className="text-[10px] font-semibold uppercase tracking-wide text-text-muted">{t('templateErrors.effectsHeading')}</p><ul className="mt-1 space-y-1 text-xs text-text-secondary">{item.effects.map(effect => <li key={effect}>· {effect}</li>)}</ul></div>
      <p className="text-[10px] text-text-muted">{t('templateErrors.mediaNote')}</p>
      {item.sourceAudio && <p className="rounded border border-border bg-bg-primary/40 px-2 py-1.5 text-[10px] text-text-secondary">{t('templateErrors.sourceAudio', { filename: item.sourceAudio.filename, duration: item.sourceAudio.duration.toFixed(1) })}</p>}
      <div className="flex flex-wrap gap-2">
        {item.scene && <button type="button" disabled={busy !== null} onClick={() => onOpenScene(item.scene!, sceneLabel)} className="rounded-lg border border-cyan-300/50 bg-cyan-400/10 px-3 py-2 text-[10px] text-cyan-100 disabled:opacity-50">{busy === `${item.id}:scene` ? t('templateErrors.checkingScene') : sceneLabel}</button>}
        {item.shots && <button type="button" onClick={onToggleShots} className="rounded-lg border border-violet-300/50 px-3 py-2 text-[10px] text-violet-100">{expanded ? t('templateErrors.hideExactShots') : t('templateErrors.showExactShots', { count: item.shots.length })}</button>}
      </div>
      {item.shots && expanded && <div className="space-y-2 rounded border border-border bg-bg-primary/40 p-2"><p className="text-[10px] text-text-muted">{t('templateErrors.shotsSavedNote')}</p>{item.shots.map((shot, index) => <div key={`${item.id}-${shot.title}`} className="flex flex-wrap items-center justify-between gap-2 rounded border border-border/60 px-2 py-1.5"><span className="min-w-0 flex-1 truncate text-xs text-text-secondary">{index + 1}. {shot.title}</span><button type="button" disabled={busy !== null} onClick={() => onOpenScene(shot.scene, t('templateErrors.shotLabel', { n: index + 1 }))} className="rounded border border-border px-2 py-1 text-[10px] text-text-primary disabled:opacity-50">{busy === `${item.id}:shot-${index}` ? t('templateErrors.checking') : t('templateErrors.openShot', { n: index + 1 })}</button></div>)}</div>}
    </div>
  </article>
}

export function SceneShowcaseGallery({ manifest, onOpenScene }: SceneShowcaseGalleryProps) {
  const { t } = useUiTranslation('scene3d')
  const checked = useMemo<ManifestCheck>(() => {
    try { return { manifest: parseShowcaseManifest(manifest), error: '' } } catch (reason) { return { manifest: null, error: errorText(reason) } }
  }, [manifest])
  const [activeVideoId, setActiveVideoId] = useState<string | null>(null)
  const [posterErrors, setPosterErrors] = useState<Record<string, boolean>>({})
  const [mediaErrors, setMediaErrors] = useState<Record<string, boolean>>({})
  const [expandedShots, setExpandedShots] = useState<Record<string, boolean>>({})
  const [busy, setBusy] = useState<string | null>(null)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const request = useRef<AbortController | null>(null)
  useEffect(() => () => request.current?.abort(), [])

  if (!checked.manifest) return <section aria-label={t('templateErrors.showcaseGallery')} className="rounded-xl border border-red-500/30 bg-red-500/10 p-4"><p role="alert" className="text-sm text-red-200">{t('templateErrors.showcaseCannotShow', { error: checked.error })}</p></section>

  const items = checked.manifest.items
  const videos = items.filter(item => item.kind === 'music_video')
  const scenes = items.filter(item => item.kind === 'scene')
  const openScene = async (item: ShowcaseItem, reference: ShowcaseFileReference, label: string, key: string) => {
    request.current?.abort()
    const controller = new AbortController()
    request.current = controller
    setBusy(key)
    setErrors(current => ({ ...current, [item.id]: '' }))
    try {
      const scene = await loadShowcaseScene(reference, controller.signal)
      if (!controller.signal.aborted) onOpenScene(scene)
    } catch (reason) {
      if (!controller.signal.aborted) setErrors(current => ({ ...current, [item.id]: t('templateErrors.openFailedWithLabel', { label, message: errorText(reason) }) }))
    } finally {
      if (!controller.signal.aborted) setBusy(null)
    }
  }
  const card = (item: ShowcaseItem) => <div key={item.id}>
    <ShowcaseCard item={item} activeVideoId={activeVideoId} posterErrors={posterErrors} mediaErrors={mediaErrors} busy={busy} expanded={expandedShots[item.id] === true} onPlay={() => setActiveVideoId(item.id)} onPosterError={() => setPosterErrors(current => ({ ...current, [item.id]: true }))} onMediaError={() => setMediaErrors(current => ({ ...current, [item.id]: true }))} onOpenScene={(reference, label) => void openScene(item, reference, label, reference === item.scene ? `${item.id}:scene` : `${item.id}:shot-${item.shots?.findIndex(shot => shot.scene === reference) ?? 0}`)} onToggleShots={() => setExpandedShots(current => ({ ...current, [item.id]: !current[item.id] }))} />
    {errors[item.id] && <p role="alert" className="mt-2 rounded border border-red-500/30 bg-red-500/10 p-2 text-xs text-red-200">{errors[item.id]}</p>}
  </div>
  return <section aria-label={t('templateErrors.sceneShowcaseGallery')} className="space-y-6 text-text-primary">
    <header className="rounded-xl border border-border bg-bg-secondary/70 p-4"><p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-cyan-300">{t('templateErrors.localShowcase')}</p><h2 className="mt-1 text-xl font-semibold">{checked.manifest.title}</h2><p className="mt-1 text-xs leading-5 text-text-secondary">{checked.manifest.description}</p><p className="mt-2 text-[10px] text-amber-100">{t('templateErrors.localOutputsNote')}</p><p className="mt-2 text-[10px] text-cyan-100">{t('templateErrors.lanPreviewNote')}</p><p className="mt-1 text-[10px] text-text-muted">{t('templateErrors.playbackNoHashNote')}</p></header>
    {videos.length > 0 && <section aria-labelledby="showcase-videos"><h3 id="showcase-videos" className="mb-3 text-lg font-semibold">{t('templateErrors.fullVideoclips')}</h3><div className="grid gap-4 xl:grid-cols-3">{videos.map(card)}</div></section>}
    {scenes.length > 0 && <section aria-labelledby="showcase-scenes"><h3 id="showcase-scenes" className="mb-3 text-lg font-semibold">{t('templateErrors.savedScenes')}</h3><div className="grid gap-4 xl:grid-cols-3">{scenes.map(card)}</div></section>}
  </section>
}
