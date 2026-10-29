import { useEffect, useState } from 'react'
import { useStore } from '../../stores/useStore'
import { useUiTranslation } from '../../i18n'
import { WangpMediaInput } from './WangpMediaInput'
import { inspectViggleFrame, viggleFrameProblem, type ViggleFrameDimensions } from '../../lib/viggleFrame'

export function ViggleControls() {
  const { t } = useUiTranslation('studio')
  const source = useStore(s => s.editVideoPath)
  const restoreError = useStore(s => s.wangpRestoreError)
  const sourceUrl = useStore(s => s.editVideoUrl)
  const reference = useStore(s => s.editRecastMappings[0])
  const setVideo = useStore(s => s.setEditVideo)
  const clearVideo = useStore(s => s.clearEditVideo)
  const setReference = useStore(s => s.setEditRecastRef)
  const editFrame = useStore(s => s.sendFrameToImageMode)
  const audio = useStore(s => s.params.viggle_audio_mode)
  const setParam = useStore(s => s.setParam)
  const resolution = useStore(s => s.editRecastResolutionProfile)
  const setResolution = (value: '480p' | '512p' | '704p') => useStore.setState({ editRecastResolutionProfile: value })
  const [editing, setEditing] = useState(false)
  const videoUrl = sourceUrl || source
  const frameUrl = reference?.refUrl || reference?.refPath || ''
  const [inspection, setInspection] = useState<{
    videoUrl: string; frameUrl: string; dimensions?: ViggleFrameDimensions
  } | null>(null)
  useEffect(() => {
    if (!videoUrl || !frameUrl) return
    const controller = new AbortController()
    void inspectViggleFrame(videoUrl, frameUrl, controller.signal).then(dimensions => {
      if (!controller.signal.aborted) setInspection({ videoUrl, frameUrl, dimensions })
    }).catch(() => {
      if (!controller.signal.aborted) setInspection({ videoUrl, frameUrl })
    })
    return () => controller.abort()
  }, [videoUrl, frameUrl])
  const currentInspection = inspection?.videoUrl === videoUrl && inspection.frameUrl === frameUrl ? inspection : null
  const dimensions = currentInspection?.dimensions
  const frameProblem = dimensions && viggleFrameProblem(dimensions)
  return <section className="space-y-3" aria-label="Viggle-Animate">
    <div className="space-y-1">
      <h3 className="text-xs font-semibold text-text-secondary">{t('wangp.steps.title')}</h3>
      <ol className="list-decimal space-y-1 pl-4 text-xs text-text-secondary">
        <li>{t('wangp.steps.source')}</li>
        <li>{t('wangp.steps.edit')}</li>
        <li>{t('wangp.steps.animate')}</li>
      </ol>
    </div>
    {!!restoreError && <p role="alert" className="text-xs text-red-400">{String(restoreError)} {t('wangp.reselectMedia')}</p>}
    <WangpMediaInput label={t('wangp.controlVideo')} kind="video" path={source} url={sourceUrl} onChoose={item => {
      clearVideo()
      setReference(null, '', '', false)
      if (item) setVideo(null, item.url, item.url, 0, '')
    }} />
    {sourceUrl && <video key={sourceUrl} src={sourceUrl} controls preload="metadata" className="w-full rounded-lg"
      onLoadedMetadata={event => {
        const video = event.currentTarget
        if (Number.isFinite(video.duration)) useStore.setState({ editVideoDuration: video.duration, editVideoResolution: `${video.videoWidth}x${video.videoHeight}` })
      }} />}
    <button type="button" disabled={!source || editing} className="w-full rounded-lg border border-border p-2 text-xs disabled:opacity-40"
      onClick={async () => { setEditing(true); try { await editFrame('recast') } finally { setEditing(false) } }}>
      {t('wangp.editFrame')}
    </button>
    <WangpMediaInput label={t('wangp.editedFrame')} kind="image" path={reference?.refPath} url={reference?.refUrl}
      onChoose={item => setReference(null, item?.url || '', item?.url || '', true)} />
    {reference?.refUrl && <img src={reference.refUrl} alt={t('wangp.editedFrame')} className="w-full rounded-lg" />}
    {!!videoUrl && !!frameUrl && (!currentInspection
      ? <p role="status" className="text-xs text-text-muted">{t('wangp.checkingFrame')}</p>
      : !dimensions
        ? <p role="alert" className="text-xs text-red-400">{t('wangp.mediaUnreadable')}</p>
        : frameProblem
          ? <p role="alert" className="text-xs text-red-400">{t('wangp.aspectMismatch', {
            videoWidth: dimensions.width, videoHeight: dimensions.height,
            imageWidth: dimensions.frameWidth, imageHeight: dimensions.frameHeight,
          })}</p>
          : <p className="text-xs text-text-muted">{dimensions.width} × {dimensions.height} → {dimensions.frameWidth} × {dimensions.frameHeight}</p>)}
    <label className="block text-xs">{t('wangp.resolution')}
      <select aria-label={t('wangp.resolution')} className="w-full bg-bg-tertiary border border-border rounded-lg p-2" value={resolution} onChange={event => setResolution(event.target.value as '480p' | '512p' | '704p')}>
        <option value="480p">480p</option><option value="512p">512p</option><option value="704p">704p</option>
      </select>
    </label>
    <label className="block text-xs">{t('wangp.audio')}
      <select aria-label={t('wangp.audio')} className="w-full bg-bg-tertiary border border-border rounded-lg p-2" value={audio === 'generated' ? 'generated' : 'source'} onChange={event => setParam('viggle_audio_mode', event.target.value === 'generated' ? 'generated' : 'source')}>
        <option value="source">{t('wangp.sourceAudio')}</option><option value="generated">{t('wangp.generatedAudio')}</option>
      </select>
    </label>
    <p className="text-[11px] text-text-muted">{t('wangp.viggleSampling')}</p>
    <p className="text-[11px] text-text-muted">{t('wangp.autoDownload')}</p>
  </section>
}
