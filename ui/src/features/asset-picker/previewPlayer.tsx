import { useEffect, useRef, useState } from 'react'
import { Play } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import type { PickerItem } from './types.ts'
import {
  PREVIEW_BYTE_LIMIT,
  getSharedPreviewPool,
  needsFullPreview,
  type PreviewResourcePool,
  type PreviewSession,
} from './previewResources.ts'

function pauseMedia(element: HTMLMediaElement | null) {
  if (!element) return
  try { element.pause() } catch { /* jsdom does not implement media playback */ }
  element.removeAttribute('src')
  try { element.load() } catch { /* jsdom does not implement media playback */ }
}

function GlbPreview({ url }: { url: string }) {
  const { t } = useUiTranslation('common')
  const [ready, setReady] = useState(false)
  useEffect(() => {
    let cancelled = false
    void import('@google/model-viewer').then(() => {
      if (!cancelled) setReady(true)
    }).catch(() => {
      if (!cancelled) setReady(false)
    })
    return () => { cancelled = true }
  }, [url])
  if (!ready) return <p className="p-2 text-center text-[10px] text-text-muted">{t('explorer.loading')}</p>
  return <model-viewer key={url} src={url} camera-controls className="h-full w-full" data-testid="asset-preview-glb" />
}

export function AssetPreviewPlayer({
  item,
  pool,
}: {
  item: PickerItem
  pool?: PreviewResourcePool
}) {
  return <PreviewPlayerBody key={`${item.ref.workspaceId}:${item.url}`} item={item} pool={pool} />
}

function PreviewPlayerBody({
  item,
  pool,
}: {
  item: PickerItem
  pool?: PreviewResourcePool
}) {
  const { t } = useUiTranslation('common')
  const videoRef = useRef<HTMLVideoElement>(null)
  const audioRef = useRef<HTMLAudioElement>(null)
  const sessionRef = useRef<PreviewSession | null>(null)
  const resources = pool ?? getSharedPreviewPool()
  const [armed, setArmed] = useState(false)
  const [playUrl, setPlayUrl] = useState(item.url)
  const [failed, setFailed] = useState(false)
  const large = item.sizeBytes > PREVIEW_BYTE_LIMIT
  const sourceUrl = item.url
  const workspaceId = item.ref.workspaceId
  const mediaKind = item.kind
  const sizeBytes = item.sizeBytes

  useEffect(() => {
    const session = resources.createSession({ scope: 'picker' })
    sessionRef.current = session
    return () => {
      session.dispose()
      sessionRef.current = null
    }
  }, [resources])

  useEffect(() => {
    const video = videoRef.current
    const audio = audioRef.current
    return () => {
      pauseMedia(video)
      pauseMedia(audio)
    }
  }, [armed, playUrl])

  useEffect(() => {
    const session = sessionRef.current
    if (!session || !needsFullPreview({ kind: mediaKind }, armed)) return
    let cancelled = false
    void session.acquire({
      sourceUrl,
      workspaceId,
      layer: 'full',
      mediaKind,
      sizeBytes,
    }).then(lease => {
      if (cancelled || !lease) return
      setPlayUrl(lease.playUrl)
    })
    return () => {
      cancelled = true
      session.cancelCurrent()
    }
  }, [armed, sourceUrl, workspaceId, mediaKind, sizeBytes, resources])

  if (failed) {
    return <p className="p-2 text-center text-[10px] text-text-muted">{t('explorer.previewFailed')}</p>
  }
  if (item.kind === 'scene') {
    return item.thumbnailUrl
      ? <img src={item.thumbnailUrl} alt={t('explorer.previewAria', { name: item.filename })} className="h-full w-full object-contain" onError={() => setFailed(true)} />
      : <p className="p-2 text-center text-[10px] text-text-muted">{t('explorer.selectHint')}</p>
  }
  if (item.kind === 'image') {
    return <img src={item.url} alt={t('explorer.previewAria', { name: item.filename })} className="h-full w-full object-contain" onError={() => setFailed(true)} />
  }
  if (!armed) {
    return (
      <button
        type="button"
        data-testid="asset-preview-arm"
        aria-label={item.kind === 'model3d' ? t('explorer.view3d') : t('explorer.playPreview')}
        onClick={() => { setFailed(false); setArmed(true); setPlayUrl(item.url) }}
        className="relative flex h-full w-full items-center justify-center"
      >
        {item.thumbnailUrl ? <img src={item.thumbnailUrl} alt="" className="absolute inset-0 h-full w-full object-contain opacity-70" /> : null}
        <span className="relative rounded-full bg-black/70 px-2 py-1 text-[10px] text-white">
          {large ? t('explorer.tooLarge') : item.kind === 'model3d' ? t('explorer.view3d') : t('explorer.playPreview')}
        </span>
        {item.kind !== 'model3d' && <Play size={16} className="relative ml-1 text-white" />}
      </button>
    )
  }
  if (item.kind === 'video') {
    return (
      <video
        ref={videoRef}
        data-testid="asset-preview-video"
        data-preview-src={playUrl}
        src={playUrl}
        controls
        playsInline
        preload="metadata"
        className="h-full w-full object-contain"
        onError={() => setFailed(true)}
      />
    )
  }
  if (item.kind === 'audio') {
    return (
      <div className="flex h-full w-full items-center justify-center px-2">
        <audio
          ref={audioRef}
          data-testid="asset-preview-audio"
          data-preview-src={playUrl}
          src={playUrl}
          controls
          preload="metadata"
          className="w-full"
          onError={() => setFailed(true)}
        />
      </div>
    )
  }
  if (item.kind === 'model3d') {
    return <GlbPreview url={playUrl} />
  }
  return <p className="p-2 text-center text-[10px] text-text-muted">{t('explorer.selectHint')}</p>
}
