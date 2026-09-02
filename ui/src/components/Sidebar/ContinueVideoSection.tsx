import { useState, useRef, useCallback } from 'react'
import { X, Film } from 'lucide-react'
import { useStore } from '../../stores/useStore'
import { useUiTranslation } from '../../i18n'
import * as api from '../../api/client'

export function ContinueVideoSection() {
  const { t } = useUiTranslation('studio')
  const continueVideo = useStore(s => s.continueVideo)
  const continueVideoUrl = useStore(s => s.continueVideoUrl)
  const continueVideoDuration = useStore(s => s.continueVideoDuration)
  const setContinueVideo = useStore(s => s.setContinueVideo)
  const clearContinueVideo = useStore(s => s.clearContinueVideo)
  const inputVideoStrength = useStore(s => s.params.input_video_strength ?? 1.0)
  const setParam = useStore(s => s.setParam)

  const [error, setError] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const handleUpload = useCallback(async (file: File) => {
    if (!file.type.startsWith('video/')) {
      setError(t('continue.needVideo'))
      return
    }
    setError(null)
    setUploading(true)
    try {
      const result = await api.uploadImage(file)
      const url = URL.createObjectURL(file)
      const video = document.createElement('video')
      video.src = url
      video.onloadedmetadata = () => {
        const duration = video.duration && isFinite(video.duration) ? video.duration : 0
        setContinueVideo(file, result.path, url, duration)
        setUploading(false)
      }
      video.onerror = () => {
        setError(t('continue.metaFailed'))
        setUploading(false)
      }
    } catch {
      setError(t('continue.uploadFailed'))
      setUploading(false)
    }
  }, [setContinueVideo, t])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    const file = e.dataTransfer.files[0]
    if (file) handleUpload(file)
  }, [handleUpload])

  return (
    <div className="space-y-2">
      <label className="text-[11px] text-text-muted uppercase tracking-wider block">
        {t('continue.title')}
      </label>

      {!continueVideo ? (
        <div
          onDragOver={e => e.preventDefault()}
          onDrop={handleDrop}
          onClick={() => fileRef.current?.click()}
          className={`border-2 border-dashed border-border rounded-lg p-4 text-center cursor-pointer hover:border-accent-blue transition-colors ${
            uploading ? 'opacity-50 pointer-events-none' : ''
          }`}
        >
          <Film size={20} className="mx-auto mb-1.5 text-text-muted" />
          <p className="text-xs text-text-secondary">
            {uploading ? t('chrome.uploading') : t('continue.drop')}
          </p>
          <p className="text-[10px] text-text-muted mt-0.5">{t('chrome.orBrowse')}</p>
          <input
            ref={fileRef}
            type="file"
            accept="video/*"
            className="hidden"
            onChange={e => { const f = e.target.files?.[0]; if (f) handleUpload(f) }}
          />
        </div>
      ) : (
        <div className="relative rounded-lg overflow-hidden border border-border">
          {continueVideoUrl && (
            <video
              src={continueVideoUrl}
              className="w-full h-20 object-cover"
              muted
            />
          )}
          <button
            onClick={clearContinueVideo}
            className="absolute top-1 right-1 p-1 rounded-full bg-black/60 text-white hover:bg-red-600 transition-colors"
          >
            <X size={12} />
          </button>
          <div className="absolute bottom-1 left-1 flex gap-1.5">
            {continueVideoDuration > 0 && (
              <span className="text-[9px] bg-black/60 text-white px-1.5 py-0.5 rounded">
                {continueVideoDuration.toFixed(1)}s
              </span>
            )}
          </div>
        </div>
      )}

      {error && <p className="text-[10px] text-red-400">{error}</p>}

      {/* Source video strength slider */}
      {continueVideo && (
        <div>
          <div className="flex items-center justify-between mb-1">
            <label className="text-[10px] text-text-muted">{t('continue.strength')}</label>
            <span className="text-[10px] text-text-secondary">{(inputVideoStrength as number).toFixed(2)}</span>
          </div>
          <input
            type="range"
            min={0} max={1} step={0.05}
            value={inputVideoStrength as number}
            onChange={e => setParam('input_video_strength', parseFloat(e.target.value))}
            className="w-full"
          />
          <p className="text-[9px] text-text-muted mt-0.5">
            {t('continue.strengthHint')}
          </p>
        </div>
      )}

      {continueVideo && (
        <p className="text-[10px] text-text-muted text-center">
          {t('continue.appended')}
        </p>
      )}
    </div>
  )
}
