import { useRef, useState } from 'react'
import { Wrench, Upload, X, Film, Mic, Play } from 'lucide-react'
import { useStore } from '../../stores/useStore'
import { useUiTranslation } from '../../i18n'
import * as api from '../../api/client'

// Upscale methods — same set as Post Processing's Spatial Upsampling, minus the
// VAE options (those are tied to the generation pipeline, not a standalone clip).
const upscaleMethods = [
  { value: 'flashvsr2', label: 'FlashVSR 2x' },
  { value: 'flashvsr3', label: 'FlashVSR 3x' },
  { value: 'flashvsr4', label: 'FlashVSR 4x' },
  { value: 'flashvsr2pass2', label: 'FlashVSR Two Pass 2x' },
  { value: 'flashvsr2pass4', label: 'FlashVSR Two Pass 4x' },
  { value: 'lanczos1.5', label: 'Lanczos 1.5x (fast)' },
  { value: 'lanczos2', label: 'Lanczos 2x (fast)' },
]

export function ToolsPanel() {
  const { t } = useUiTranslation('studio')
  const { t: tCommon } = useUiTranslation('common')
  const tool = useStore(s => s.toolsTool)
  const setTool = useStore(s => s.setToolsTool)
  const sourcePath = useStore(s => s.toolsSourcePath)
  const sourceName = useStore(s => s.toolsSourceName)
  const sourceUrl = useStore(s => s.toolsSourceUrl)
  const setSource = useStore(s => s.setToolsSource)
  const method = useStore(s => s.toolsUpscaleMethod)
  const setMethod = useStore(s => s.setToolsUpscaleMethod)
  const revoiceMode = useStore(s => s.toolsRevoiceMode)
  const setRevoiceMode = useStore(s => s.setToolsRevoiceMode)
  const revoiceRefs = useStore(s => s.toolsRevoiceRefs)
  const setRevoiceRef = useStore(s => s.setToolsRevoiceRef)
  const runTool = useStore(s => s.runTool)
  const outputs = useStore(s => s.outputs)
  const selectedOutput = useStore(s => s.selectedOutput)
  const flashvsrMode = useStore(s => s.servicesConfig?.flashvsr_mode ?? 1)
  const current = outputs[selectedOutput]
  const currentIsVideo = !!current && current.type === 'video'

  const fileRef = useRef<HTMLInputElement>(null)
  const vcFileRefs = [useRef<HTMLInputElement>(null), useRef<HTMLInputElement>(null)]
  const [uploading, setUploading] = useState(false)
  const [vcUploading, setVcUploading] = useState<number | null>(null)

  const handleSourceUpload = async (file: File) => {
    setUploading(true)
    try {
      const r = await api.uploadImage(file)  // /api/v1/upload handles video too
      setSource({ path: r.path, name: file.name, url: r.url })
    } catch (e) {
      console.error('Source upload failed:', e)
    } finally {
      setUploading(false)
    }
  }

  const useCurrentClip = () => {
    if (currentIsVideo) setSource({ path: current.name, name: current.name, url: current.url })
  }

  const handleVcUpload = async (index: number, file: File) => {
    setVcUploading(index)
    try {
      const r = await api.uploadAudio(file)
      setRevoiceRef(index, { filename: file.name, path: r.path })
    } catch (e) {
      console.error('Voice ref upload failed:', e)
    } finally {
      setVcUploading(null)
    }
  }

  const hasRefs = revoiceRefs.some(r => r && r.path)
  const canRun = !!sourcePath && (tool === 'upscale' || hasRefs)
  const flashvsrOff = flashvsrMode === 0 && method.startsWith('flashvsr')

  return (
    <div className="flex flex-col gap-4">
      <div>
        <div className="flex items-center gap-1.5 text-[11px] text-text-muted uppercase tracking-wider mb-2">
          <Wrench size={12} /> {t('tools.title')}
        </div>
        {/* Tool selector */}
        <div className="flex bg-bg-tertiary rounded-lg p-0.5 border border-border">
          {([['upscale', 'tools.upscale'], ['revoice', 'tools.revoice']] as const).map(([val, labelKey]) => (
            <button
              key={val}
              onClick={() => setTool(val)}
              className={`flex-1 text-xs py-2 rounded-md transition-all ${
                tool === val ? 'bg-bg-active text-text-primary' : 'text-text-secondary hover:text-text-primary'
              }`}
            >
              {t(labelKey)}
            </button>
          ))}
        </div>
      </div>

      {/* Source clip — upload, or use the clip currently selected in the gallery */}
      <div>
        <label className="text-[11px] text-text-muted uppercase tracking-wider mb-1.5 block">{t('tools.sourceClip')}</label>
        {sourcePath ? (
          <div className="bg-bg-tertiary border border-border rounded-lg p-2 space-y-2">
            {sourceUrl && (
              <video src={sourceUrl} className="w-full rounded-md max-h-44 bg-black" muted controls playsInline />
            )}
            <div className="flex items-center gap-2">
              <Film size={12} className="text-accent-blue shrink-0" />
              <span className="flex-1 min-w-0 truncate text-[11px] text-text-primary">{sourceName}</span>
              <button onClick={() => setSource(null)} className="p-0.5 text-text-muted hover:text-red-400 transition-colors" title={t('chrome.clear')}>
                <X size={12} />
              </button>
            </div>
          </div>
        ) : (
          <div className="space-y-2">
            <div
              onClick={() => fileRef.current?.click()}
              className={`border-2 border-dashed border-border rounded-lg p-3 text-center cursor-pointer hover:border-accent-blue transition-colors ${uploading ? 'opacity-50 pointer-events-none' : ''}`}
            >
              <Upload size={16} className="mx-auto mb-1 text-text-muted" />
              <p className="text-[11px] text-text-secondary">{uploading ? t('chrome.uploading') : t('tools.uploadClip')}</p>
              <input
                ref={fileRef}
                type="file"
                accept="video/*"
                className="hidden"
                onChange={e => { const f = e.target.files?.[0]; if (f) handleSourceUpload(f) }}
              />
            </div>
            <button
              onClick={useCurrentClip}
              disabled={!currentIsVideo}
              className="w-full text-[11px] py-1.5 rounded-md border border-border bg-bg-tertiary text-text-secondary hover:text-text-primary disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              {currentIsVideo ? t('tools.useGallery') : t('tools.selectGallery')}
            </button>
          </div>
        )}
      </div>

      {/* Tool params */}
      {tool === 'upscale' ? (
        <div>
          <label className="text-[11px] text-text-muted uppercase tracking-wider mb-1.5 block">{t('tools.upscaleMethod')}</label>
          <select
            value={method}
            onChange={e => setMethod(e.target.value)}
            className="w-full bg-bg-tertiary border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent-blue"
          >
            {upscaleMethods.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
          {flashvsrOff && (
            <p className="text-[10px] text-indicator-warning mt-1.5 leading-snug">
              {t('tools.flashvsrOff')}
            </p>
          )}
          <p className="text-[10px] text-text-muted mt-1.5 leading-snug">
            {t('tools.upscaleHint')}
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          <label className="text-[11px] text-text-muted uppercase tracking-wider block">{t('tools.replaceVoice')}</label>
          <div className="flex gap-1.5 text-xs">
            {([['single', 'tools.singleVoice'], ['two', 'tools.twoVoices']] as const).map(([val, labelKey]) => (
              <button
                key={val}
                onClick={() => setRevoiceMode(val)}
                className={`flex-1 py-1.5 rounded-md border transition-colors ${
                  revoiceMode === val
                    ? 'bg-accent-blue/10 border-accent-blue text-text-primary'
                    : 'bg-bg-tertiary border-border text-text-secondary hover:text-text-primary'
                }`}
              >
                {t(labelKey)}
              </button>
            ))}
          </div>
          <p className="text-[10px] text-text-muted leading-snug">
            {revoiceMode === 'single'
              ? t('tools.singleHint')
              : t('tools.twoHint')}
          </p>
          {[0, ...(revoiceMode === 'two' ? [1] : [])].map(idx => {
            const ref = revoiceRefs[idx]
            const label = revoiceMode === 'two' ? (idx === 0 ? t('tools.voiceA') : t('tools.voiceB')) : t('tools.referenceVoice')
            return (
              <div key={idx}>
                <label className="text-[10px] text-text-muted uppercase tracking-wider mb-1 block">{label}</label>
                {!ref || !ref.path ? (
                  <div
                    onClick={() => vcFileRefs[idx].current?.click()}
                    className={`border-2 border-dashed border-border rounded-lg p-2 text-center cursor-pointer hover:border-accent-blue transition-colors ${vcUploading === idx ? 'opacity-50 pointer-events-none' : ''}`}
                  >
                    <p className="text-[11px] text-text-secondary">{vcUploading === idx ? t('chrome.uploading') : t('tools.uploadSample', { label: label.toLowerCase() })}</p>
                    <input
                      ref={vcFileRefs[idx]}
                      type="file"
                      accept="audio/*,video/*"
                      className="hidden"
                      onChange={e => { const f = e.target.files?.[0]; if (f) handleVcUpload(idx, f) }}
                    />
                  </div>
                ) : (
                  <div className="flex items-center gap-2 bg-bg-tertiary border border-border rounded-lg px-2 py-1.5">
                    <Mic size={12} className="text-accent-blue shrink-0" />
                    <span className="flex-1 min-w-0 truncate text-[11px] text-text-primary">{ref.filename}</span>
                    <button onClick={() => setRevoiceRef(idx, null)} className="p-0.5 text-text-muted hover:text-red-400 transition-colors" title={tCommon('actions.remove')}>
                      <X size={12} />
                    </button>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* Run */}
      <button
        onClick={() => runTool()}
        disabled={!canRun}
        className={`w-full px-4 py-2.5 rounded-lg flex items-center justify-center gap-1.5 font-medium text-xs transition-all ${
          canRun
            ? 'bg-cta hover:brightness-110 shadow-accent-glow text-white'
            : 'bg-bg-tertiary text-text-muted cursor-not-allowed border border-border'
        }`}
      >
        <Play size={13} fill={canRun ? 'white' : 'currentColor'} />
        {tool === 'upscale' ? t('tools.upscaleClip') : t('tools.replaceVoiceAction')}
      </button>
    </div>
  )
}
