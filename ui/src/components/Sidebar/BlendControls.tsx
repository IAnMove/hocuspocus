import { useFieldIds } from '../common/fieldIds'
import { controlLabel } from '../../i18n/controlLabel'
import { useState, useCallback, useEffect, useMemo } from 'react'
import { X, ArrowRight } from 'lucide-react'
import { useStore } from '../../stores/useStore'
import { useUiTranslation } from '../../i18n'
import type { ApiOutput } from '../../api/outputs'
import { StudioSourceField } from '../../lib/StudioSourceField.tsx'
import { applyChosenStudioMedia, useWorkspaceOutputs } from '../../lib/studioAssetPick.ts'

function ClipDropZone({ label, file, url, duration, items, workspaceId, onChoose, onClear }: {
  label: string
  file: File | null
  url: string
  duration: number
  items: ApiOutput[]
  workspaceId: string
  onChoose: (item: ApiOutput) => void
  onClear: () => void
}) {
  if (file) {
    return (
      <div className="relative rounded-lg overflow-hidden border border-border flex-1">
        {file.type.startsWith('video/')
          ? <video src={url} className="w-full h-16 object-cover" muted />
          : <img src={url} className="w-full h-16 object-cover" alt="" />
        }
        <button
          onClick={onClear}
          className="absolute top-0.5 right-0.5 p-0.5 rounded-full bg-black/60 text-white hover:bg-red-600 transition-colors"
         title={controlLabel('a11y.removeImage')} aria-label={controlLabel('a11y.removeImage')}>
          <X size={10} />
        </button>
        <div className="absolute bottom-0.5 left-0.5 text-[8px] bg-black/60 text-white px-1 py-0.5 rounded">
          {label}{duration > 0 ? ` ${duration.toFixed(1)}s` : ''}
        </div>
      </div>
    )
  }

  return (
    <div className="flex-1 min-w-0">
      <StudioSourceField
        label={label}
        items={items}
        accept="video/*,image/*"
        kinds={['image', 'video']}
        workspaceId={workspaceId}
        onChoose={onChoose}
      />
    </div>
  )
}

export function BlendControls() {
  const fieldIds = useFieldIds()

  const { t } = useUiTranslation('studio')
  const blendClipA = useStore(s => s.blendClipA)
  const blendClipAUrl = useStore(s => s.blendClipAUrl)
  const blendClipADuration = useStore(s => s.blendClipADuration)
  const blendClipB = useStore(s => s.blendClipB)
  const blendClipBUrl = useStore(s => s.blendClipBUrl)
  const blendClipBDuration = useStore(s => s.blendClipBDuration)
  const setBlendClipA = useStore(s => s.setBlendClipA)
  const setBlendClipB = useStore(s => s.setBlendClipB)
  const clearBlendClipA = useStore(s => s.clearBlendClipA)
  const clearBlendClipB = useStore(s => s.clearBlendClipB)
  const transitionSec = useStore(s => s.blendTransitionSec)
  const setTransitionSec = useStore(s => s.setBlendTransitionSec)
  const blendMode = useStore(s => s.blendMode)
  const setBlendMode = useStore(s => s.setBlendMode)
  const overlapSec = useStore(s => s.blendOverlapSec)
  const setOverlapSec = useStore(s => s.setBlendOverlapSec)
  const motionPrefixSec = useStore(s => s.blendMotionPrefixSec)
  const setMotionPrefixSec = useStore(s => s.setBlendMotionPrefixSec)
  const motionSuffixSec = useStore(s => s.blendMotionSuffixSec)
  const setMotionSuffixSec = useStore(s => s.setBlendMotionSuffixSec)
  const anchorStrength = useStore(s => s.blendAnchorStrength)
  const setAnchorStrength = useStore(s => s.setBlendAnchorStrength)
  const ensureTransitionLoraForBlend = useStore(s => s.ensureTransitionLoraForBlend)
  const activeWorkspace = useStore(s => s.activeWorkspace)
  const library = useWorkspaceOutputs(activeWorkspace)
  const clipItems = useMemo(
    () => library.filter(item => item.type === 'image' || item.type === 'video'),
    [library],
  )

  // On blend mode mount, make sure the LTX-2.3 transition LoRA is installed
  // and active. Idempotent — fires once per mount; the helper itself no-ops
  // if the LoRA is already installed + activated.
  useEffect(() => {
    void ensureTransitionLoraForBlend()
  }, [ensureTransitionLoraForBlend])

  const [error, setError] = useState<string | null>(null)

  const chooseClip = useCallback((item: ApiOutput, target: 'A' | 'B') => {
    setError(null)
    applyChosenStudioMedia(item, next => {
      if (target === 'A') setBlendClipA(next.file, next.path, next.url, next.duration)
      else setBlendClipB(next.file, next.path, next.url, next.duration)
    })
  }, [setBlendClipA, setBlendClipB])

  const bothLoaded = !!blendClipA && !!blendClipB

  return (
    <div className="space-y-3">
      {/* Overlap / Insert toggle — first choice, above the clip drop zones */}
      <div>
        <div className="flex bg-bg-tertiary rounded-lg p-0.5 border border-border">
          <button
            onClick={() => setBlendMode('overlap')}
            className={`flex-1 text-[10px] py-1.5 rounded-md transition-all ${
              blendMode === 'overlap' ? 'bg-bg-active text-text-primary' : 'text-text-secondary hover:text-text-primary'
            }`}
          >
            {t('blend.overlap')}
          </button>
          <button
            onClick={() => setBlendMode('insert')}
            className={`flex-1 text-[10px] py-1.5 rounded-md transition-all ${
              blendMode === 'insert' ? 'bg-bg-active text-text-primary' : 'text-text-secondary hover:text-text-primary'
            }`}
          >
            {t('blend.insert')}
          </button>
        </div>
        <p className="text-[9px] text-text-muted mt-1">
          {blendMode === 'insert'
            ? t('blend.insertHint')
            : t('blend.overlapHint')}
        </p>
      </div>

      {/* Clip A → Arrow → Clip B */}
      <div className="flex items-center gap-1.5">
        <ClipDropZone
          label={t('blend.clipA')}
          file={blendClipA}
          url={blendClipAUrl}
          duration={blendClipADuration}
          items={clipItems}
          workspaceId={activeWorkspace}
          onChoose={item => chooseClip(item, 'A')}
          onClear={clearBlendClipA}
        />
        <ArrowRight size={16} className="text-text-muted shrink-0" />
        <ClipDropZone
          label={t('blend.clipB')}
          file={blendClipB}
          url={blendClipBUrl}
          duration={blendClipBDuration}
          items={clipItems}
          workspaceId={activeWorkspace}
          onChoose={item => chooseClip(item, 'B')}
          onClear={clearBlendClipB}
        />
      </div>

      {error && <p className="text-[10px] text-red-400">{error}</p>}

      {/* Transition duration (Insert mode) */}
      {blendMode === 'insert' && (
        <div>
          <div className="flex items-center justify-between mb-1">
            <label htmlFor={fieldIds('f0')} className="text-[10px] text-text-muted">{t('blend.transition')}</label>
            <span className="text-[10px] text-text-secondary">{transitionSec}s</span>
          </div>
          <input aria-label={t('blend.transition')} id={fieldIds('f0')}
            type="range"
            min={2} max={10} step={1}
            value={transitionSec}
            onChange={e => setTransitionSec(parseInt(e.target.value))}
            className="w-full"
          />
        </div>
      )}

      {/* Overlap duration (Overlap mode) */}
      {blendMode === 'overlap' && (
        <div>
          <div className="flex items-center justify-between mb-1">
            <label htmlFor={fieldIds('f1')} className="text-[10px] text-text-muted">{t('blend.overlapDuration')}</label>
            <span className="text-[10px] text-text-secondary">{overlapSec}s</span>
          </div>
          <input aria-label={t('blend.overlapDuration')} id={fieldIds('f1')}
            type="range"
            min={1} max={Math.min(8, Math.floor(Math.min(blendClipADuration || 99, blendClipBDuration || 99) / 2))}
            step={1}
            value={overlapSec}
            onChange={e => setOverlapSec(parseInt(e.target.value))}
            className="w-full"
          />
          <p className="text-[9px] text-text-muted mt-0.5">
            {t('blend.overlapTrim', { seconds: overlapSec })}
          </p>
        </div>
      )}

      {/* Motion continuity + anchor strength (Overlap mode only) */}
      {bothLoaded && blendMode === 'overlap' && (
        <div className="space-y-2">
          <div>
            <div className="flex items-center justify-between mb-1">
              <label htmlFor={fieldIds('f2')} className="text-[10px] text-text-muted">{t('blend.motionPrefix')}</label>
              <span className="text-[10px] text-text-secondary">{motionPrefixSec.toFixed(1)}s</span>
            </div>
            <input aria-label={t('blend.motionPrefix')} id={fieldIds('f2')}
              type="range"
              min={0} max={Math.min(3, Math.floor(overlapSec * 0.7))} step={0.5}
              value={motionPrefixSec}
              onChange={e => setMotionPrefixSec(parseFloat(e.target.value))}
              className="w-full"
            />
            <p className="text-[9px] text-text-muted mt-0.5">
              {motionPrefixSec === 0
                ? t('blend.prefixOff')
                : t('blend.prefixOn', { seconds: motionPrefixSec.toFixed(1) })}
            </p>
          </div>
          <div>
            <div className="flex items-center justify-between mb-1">
              <label htmlFor={fieldIds('f3')} className="text-[10px] text-text-muted">{t('blend.motionSuffix')}</label>
              <span className="text-[10px] text-text-secondary">{motionSuffixSec.toFixed(1)}s</span>
            </div>
            <input aria-label={t('blend.motionSuffix')} id={fieldIds('f3')}
              type="range"
              min={0} max={Math.min(3, Math.floor(overlapSec * 0.7))} step={0.5}
              value={motionSuffixSec}
              onChange={e => setMotionSuffixSec(parseFloat(e.target.value))}
              className="w-full"
            />
            <p className="text-[9px] text-text-muted mt-0.5">
              {motionSuffixSec === 0
                ? t('blend.suffixOff')
                : t('blend.suffixOn', { seconds: motionSuffixSec.toFixed(1) })}
            </p>
          </div>
          <div>
            <div className="flex items-center justify-between mb-1">
              <label htmlFor={fieldIds('f4')} className="text-[10px] text-text-muted">{t('blend.anchor')}</label>
              <span className="text-[10px] text-text-secondary">{anchorStrength.toFixed(2)}</span>
            </div>
            <input aria-label={t('blend.anchor')} id={fieldIds('f4')}
              type="range"
              min={0.3} max={1.0} step={0.05}
              value={anchorStrength}
              onChange={e => setAnchorStrength(parseFloat(e.target.value))}
              className="w-full"
            />
            <p className="text-[9px] text-text-muted mt-0.5">
              {t('blend.anchorHint')}
            </p>
          </div>
        </div>
      )}

      {bothLoaded && (
        <div className="text-[10px] text-text-muted text-center bg-bg-tertiary rounded-lg px-2 py-1.5 border border-border/50">
          {blendMode === 'insert'
            ? t('blend.outputInsert', { seconds: transitionSec })
            : t('blend.outputOverlap', { seconds: overlapSec })
          }
        </div>
      )}

      {!bothLoaded && (blendClipA || blendClipB) && (
        <p className="text-[10px] text-indicator-warning text-center">{t('blend.needBoth')}</p>
      )}
    </div>
  )
}
