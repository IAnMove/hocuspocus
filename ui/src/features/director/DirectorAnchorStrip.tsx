import { useState } from 'react'
import { ImageIcon, Loader2 } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { getFileUrl, setPipelineAnchor } from '../../api/client'
import type {
  DirectorLightingContinuity,
  DirectorReferenceAnchorMode,
  GenerationDetails,
  MusicVideoChorusSet,
  SavedPipelineState,
} from '../../types'

const MODE_KEYS = {
  always: 'services.referenceAnchorAlways',
  no_cast_refs: 'services.referenceAnchorNoCast',
  off: 'services.referenceAnchorOff',
} as const satisfies Record<DirectorReferenceAnchorMode, string>
const LIGHT_KEYS = {
  auto: 'services.lightingAuto',
  reference: 'services.lightingReference',
  per_shot: 'services.lightingPerShot',
} as const satisfies Record<DirectorLightingContinuity, string>
const CHORUS_KEYS = {
  first: 'treatment.chorusFirst',
  rotate: 'treatment.chorusRotate',
  free: 'treatment.chorusFree',
} as const satisfies Record<MusicVideoChorusSet, string>

/** The run's options that used to be hidden house rules, as one line. */
function RunOptions({ details }: { details: GenerationDetails }) {
  const { t } = useUiTranslation('director')
  const { t: tSettings } = useUiTranslation('settings')
  const anchor = details.reference_anchor
  const parts = [
    anchor ? t('dashboard.anchor.setting', { value: tSettings(MODE_KEYS[anchor.mode] || MODE_KEYS.always) }) : '',
    details.lighting_continuity ? t('dashboard.anchor.light', { value: tSettings(LIGHT_KEYS[details.lighting_continuity]) }) : '',
    details.keep_reference_wardrobe === undefined ? '' : t('dashboard.anchor.wardrobe', {
      value: t(details.keep_reference_wardrobe ? 'dashboard.anchor.wardrobeKept' : 'dashboard.anchor.wardrobeFree'),
    }),
    details.chorus_set ? t('dashboard.anchor.choruses', { value: t(CHORUS_KEYS[details.chorus_set]) }) : '',
    details.coverage_cycle === undefined ? '' : details.coverage_cycle.length
      ? t('dashboard.anchor.coverage', { count: details.coverage_cycle.length })
      : t('dashboard.anchor.coverageNone'),
  ].filter(Boolean)
  return <p className="text-[10px] text-text-muted">{parts.join(' · ')}</p>
}

function runImages(pipeline: SavedPipelineState): Array<{ index: number; filename: string }> {
  return pipeline.clips
    .filter(clip => Boolean(clip.start_image_filename))
    .map(clip => ({ index: clip.index, filename: String(clip.start_image_filename) }))
}

function AnchorThumbnail({ filename, source }: { filename?: string; source: string }) {
  const { t } = useUiTranslation('director')
  const [failed, setFailed] = useState(false)
  return (
    <div className="w-16 h-16 shrink-0 rounded overflow-hidden bg-bg-tertiary border border-border flex items-center justify-center">
      {filename && !failed
        ? <img src={getFileUrl(filename, source === 'user' ? '__uploads__' : undefined)} alt={t('dashboard.anchor.title')}
          className="w-full h-full object-cover" onError={() => setFailed(true)} />
        : <ImageIcon size={16} className="text-text-muted" />}
    </div>
  )
}

function AnchorPicker({ images, current, saving, onPick }: {
  images: Array<{ index: number; filename: string }>
  current?: string
  saving: boolean
  onPick: (filename: string) => void
}) {
  const { t } = useUiTranslation('director')
  return (
    <div className="space-y-1">
      <p className="text-[10px] text-text-muted">{t('dashboard.anchor.pickTitle')}</p>
      <div className="flex flex-wrap gap-1.5">
        {images.map(image => (
          <button key={image.filename} type="button" onClick={() => onPick(image.filename)} disabled={saving}
            aria-label={t('dashboard.anchor.pickAria', { n: image.index + 1 })}
            className={`w-14 h-14 rounded overflow-hidden border ${image.filename === current ? 'border-accent-blue' : 'border-border'} disabled:opacity-40`}>
            <img src={getFileUrl(image.filename)} alt="" className="w-full h-full object-cover" loading="lazy" />
          </button>
        ))}
      </div>
    </div>
  )
}

function AnchorActions({ generated, disabled, canReplace, saving, onReplace, onClear }: {
  generated: boolean
  disabled: boolean
  canReplace: boolean
  saving: boolean
  onReplace: () => void
  onClear: () => void
}) {
  const { t } = useUiTranslation('director')
  return (
    <div className="flex shrink-0 flex-col gap-1">
      <button type="button" onClick={onReplace} disabled={disabled || !canReplace}
        className="px-2 py-1 text-[10px] rounded border border-accent-blue/30 bg-accent-blue/10 text-accent-blue hover:bg-accent-blue/20 disabled:opacity-40">
        {t('dashboard.anchor.replace')}
      </button>
      {generated && (
        <button type="button" onClick={onClear} disabled={disabled}
          className="px-2 py-1 text-[10px] rounded border border-border text-text-secondary hover:bg-bg-hover disabled:opacity-40">
          {saving ? <Loader2 size={10} className="inline animate-spin" /> : null} {t('dashboard.anchor.clear')}
        </button>
      )}
    </div>
  )
}

/** The shared reference every start image is drawn from, with Replace and Clear. */
export function DirectorAnchorStrip({ pipeline, workspace, busy = false, onSaved }: {
  pipeline: SavedPipelineState
  workspace: string
  busy?: boolean
  onSaved: (pipeline: SavedPipelineState) => void
}) {
  const { t } = useUiTranslation('director')
  const [picking, setPicking] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const details = pipeline.generation_details
  const anchor = details?.reference_anchor
  if (!details || !anchor) return null

  const save = async (filename: string | null) => {
    setSaving(true)
    setError(null)
    try {
      onSaved(await setPipelineAnchor(pipeline.pipeline_id, workspace, filename))
      setPicking(false)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught))
    } finally {
      setSaving(false)
    }
  }
  const images = runImages(pipeline)

  return (
    <section aria-label={t('dashboard.anchor.title')} className="bg-bg-secondary rounded-lg border border-border p-3 space-y-2">
      <div className="flex items-start gap-3">
        <AnchorThumbnail key={anchor.filename} filename={anchor.filename} source={anchor.source} />
        <div className="min-w-0 flex-1 space-y-1">
          <h3 className="text-[11px] text-text-secondary uppercase tracking-wider font-medium">{t('dashboard.anchor.title')}</h3>
          <p className="text-[11px] text-text-primary">{t(`dashboard.anchor.${anchor.source}`)}</p>
          {anchor.prompt && (
            <p className="text-[10px] text-text-muted line-clamp-2" title={anchor.prompt}>
              {t('dashboard.anchor.prompt', { prompt: anchor.prompt })}
            </p>
          )}
          <RunOptions details={details} />
        </div>
        {anchor.source !== 'user' && (
          <AnchorActions generated={anchor.source === 'generated'} disabled={busy || saving} canReplace={images.length > 0}
            saving={saving} onReplace={() => setPicking(open => !open)} onClear={() => void save(null)} />
        )}
      </div>
      {picking && <AnchorPicker images={images} current={anchor.filename} saving={saving} onPick={filename => void save(filename)} />}
      {error && <p role="alert" className="text-[10px] text-red-400">{t('dashboard.anchor.failed', { error })}</p>}
    </section>
  )
}

/** "The planner returned no shots…" when Director built the plan itself. */
export function PlanFallbackNotice({ pipeline }: { pipeline: SavedPipelineState }) {
  const { t } = useUiTranslation('director')
  if (pipeline.planning_source !== 'deterministic_fallback') return null
  return (
    <p role="status" className="rounded-md border border-amber-500/30 bg-amber-500/10 px-2 py-1.5 text-[11px] text-amber-200">
      {t('dashboard.planFallback')}
    </p>
  )
}

/** The recurring set and coverage the music-video planner gave this shot. */
export function PlannedCoverage({ plan }: { plan?: Record<string, unknown> }) {
  const { t } = useUiTranslation('director')
  const metadata = (plan?.metadata ?? {}) as Record<string, unknown>
  const parts = [
    typeof metadata.recurring_set === 'string' && metadata.recurring_set ? t('treatment.planSet', { value: metadata.recurring_set }) : '',
    typeof metadata.coverage === 'string' && metadata.coverage ? t('treatment.planCoverage', { value: metadata.coverage }) : '',
  ].filter(Boolean)
  if (!parts.length) return null
  return <p className="px-3 pt-1 text-[9px] text-text-muted">{parts.join(' · ')}</p>
}
