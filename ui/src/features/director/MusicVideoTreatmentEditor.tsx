import { useState } from 'react'
import { Sparkles } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import type { MusicVideoChorusSet, MusicVideoTreatment } from '../../types'
import { CHORUS_SET_MODES, DEFAULT_COVERAGE_CYCLE, coverageCycle, parseCoverageLines } from './treatmentDefaults'

const INPUT_CLASS = 'w-full rounded-md border border-border bg-bg-secondary px-2 py-1.5 text-[10px] text-text-primary focus:border-accent-blue focus:outline-none'

const CHORUS_LABEL_KEYS = {
  first: 'treatment.chorusFirst',
  rotate: 'treatment.chorusRotate',
  free: 'treatment.chorusFree',
} as const satisfies Record<MusicVideoChorusSet, string>
const MODE_LABEL_KEYS = {
  hybrid: 'treatment.modeHybrid',
  performance: 'treatment.modePerformance',
  narrative: 'treatment.modeNarrative',
  abstract: 'treatment.modeAbstract',
} as const satisfies Record<MusicVideoTreatment['mode'], string>

type Change = (partial: Partial<MusicVideoTreatment>) => void

/** The coverage cycle the planner uses, one line per clip in turn. */
function CoverageField({ treatment, onChange }: { treatment: MusicVideoTreatment; onChange: Change }) {
  const { t } = useUiTranslation('director')
  const cycleText = coverageCycle(treatment).join('\n')
  const [draft, setDraft] = useState(cycleText)
  const [shown, setShown] = useState(cycleText)
  // A reset or a loaded treatment replaces what is typed here.
  if (shown !== cycleText) {
    setShown(cycleText)
    if (parseCoverageLines(draft).join('\n') !== cycleText) setDraft(cycleText)
  }
  return (
    <label className="block text-[9px] text-text-muted">{t('treatment.coverage')}
      <textarea
        value={draft}
        rows={4}
        onChange={event => {
          setDraft(event.target.value)
          onChange({ coverage: parseCoverageLines(event.target.value) })
        }}
        className={`${INPUT_CLASS} mt-1 resize-y`}
        placeholder={DEFAULT_COVERAGE_CYCLE.join('\n')}
      />
      <span className="mt-0.5 block text-[9px] leading-relaxed text-text-muted">{t('treatment.coverageHint')}</span>
    </label>
  )
}

function ChorusSetField({ treatment, onChange }: { treatment: MusicVideoTreatment; onChange: Change }) {
  const { t } = useUiTranslation('director')
  return (
    <label className="block text-[9px] text-text-muted">{t('treatment.chorusSet')}
      <select
        value={treatment.chorus_set || 'first'}
        onChange={event => onChange({ chorus_set: event.target.value as MusicVideoChorusSet })}
        className={`${INPUT_CLASS} mt-1`}
      >
        {CHORUS_SET_MODES.map(mode => <option key={mode} value={mode}>{t(CHORUS_LABEL_KEYS[mode])}</option>)}
      </select>
    </label>
  )
}

function GenerationModeField({ treatment, onChange }: { treatment: MusicVideoTreatment; onChange: Change }) {
  const { t } = useUiTranslation('director')
  return (
    <div className="rounded-lg border border-border bg-bg-tertiary/60 p-2 space-y-2">
      <label className="block text-[9px] text-text-muted">{t('directVideo.generationMode')}
        <select
          value={treatment.generation_mode}
          onChange={event => onChange({ generation_mode: event.target.value as MusicVideoTreatment['generation_mode'] })}
          className={`${INPUT_CLASS} mt-1`}
        >
          <option value="image_guided">{t('directVideo.imageGuided')}</option>
          <option value="direct_video">{t('directVideo.option')}</option>
        </select>
      </label>
      {treatment.generation_mode === 'direct_video' && (
        <div className="space-y-2 rounded-md border border-fuchsia-500/30 bg-fuchsia-500/10 p-2">
          <div>
            <p className="text-[10px] font-medium text-fuchsia-200">{t('directVideo.pure')}</p>
            <p className="mt-0.5 text-[9px] leading-relaxed text-text-muted">
              {t('directVideo.masterHint')}
            </p>
          </div>
          <label className="block text-[9px] text-text-muted">{t('directVideo.masterLabel')}
            <textarea
              value={treatment.direct_video_master_prompt}
              rows={8}
              onChange={event => onChange({ direct_video_master_prompt: event.target.value })}
              className={`${INPUT_CLASS} mt-1 resize-y leading-relaxed`}
              placeholder={t('directVideo.masterPlaceholder')}
            />
          </label>
          <p className="text-[9px] leading-relaxed text-amber-200/80">
            {t('directVideo.ignoreLoaded')}
          </p>
        </div>
      )}
    </div>
  )
}

function PerformanceFields({ treatment, onChange }: { treatment: MusicVideoTreatment; onChange: Change }) {
  const { t } = useUiTranslation('director')
  return (
    <>
      <div className="grid grid-cols-2 gap-2">
        <label className="text-[9px] text-text-muted">{t('treatment.mode')}
          <select value={treatment.mode} onChange={event => onChange({ mode: event.target.value as MusicVideoTreatment['mode'] })} className={`${INPUT_CLASS} mt-1`}>
            {(Object.keys(MODE_LABEL_KEYS) as Array<MusicVideoTreatment['mode']>).map(mode => (
              <option key={mode} value={mode}>{t(MODE_LABEL_KEYS[mode])}</option>
            ))}
          </select>
        </label>
        <label className="text-[9px] text-text-muted">{t('treatment.lipSync')}
          <select value={treatment.lip_sync} onChange={event => onChange({ lip_sync: event.target.value as MusicVideoTreatment['lip_sync'] })} className={`${INPUT_CLASS} mt-1`}>
            <option value="frequent">{t('treatment.lipSyncFrequent')}</option>
            <option value="occasional">{t('treatment.lipSyncOccasional')}</option>
            <option value="none">{t('treatment.lipSyncNone')}</option>
          </select>
        </label>
      </div>

      <label className="block text-[9px] text-text-muted">
        <span className="flex justify-between"><span>{t('treatment.artistOnScreen')}</span><b className="text-text-secondary">{treatment.performer_presence}%</b></span>
        <input type="range" min={0} max={100} step={5} value={treatment.performer_presence}
          onChange={event => onChange({ performer_presence: Number(event.target.value) })}
          className="mt-1 w-full accent-accent-blue" />
      </label>
    </>
  )
}

function LookFields({ treatment, onChange }: { treatment: MusicVideoTreatment; onChange: Change }) {
  const { t } = useUiTranslation('director')
  return (
    <>
      <div className="grid grid-cols-2 gap-2">
        <label className="text-[9px] text-text-muted">{t('treatment.wardrobe')}
          <input value={treatment.wardrobe} onChange={event => onChange({ wardrobe: event.target.value })} className={`${INPUT_CLASS} mt-1`} placeholder={t('treatment.wardrobePlaceholder')} />
        </label>
        <label className="text-[9px] text-text-muted">{t('treatment.palette')}
          <input value={treatment.palette} onChange={event => onChange({ palette: event.target.value })} className={`${INPUT_CLASS} mt-1`} placeholder={t('treatment.palettePlaceholder')} />
        </label>
      </div>

      <label className="block text-[9px] text-text-muted">{t('treatment.cameraLanguage')}
        <input value={treatment.camera_language} onChange={event => onChange({ camera_language: event.target.value })} className={`${INPUT_CLASS} mt-1`} />
      </label>
      <label className="block text-[9px] text-text-muted">{t('treatment.motif')}
        <input value={treatment.recurring_motif} onChange={event => onChange({ recurring_motif: event.target.value })} className={`${INPUT_CLASS} mt-1`} placeholder={t('treatment.motifPlaceholder')} />
      </label>
      <label className="block text-[9px] text-text-muted">{t('treatment.chorusSignature')}
        <textarea value={treatment.chorus_signature} rows={2} onChange={event => onChange({ chorus_signature: event.target.value })} className={`${INPUT_CLASS} mt-1 resize-none`} />
      </label>

      <label className="block text-[9px] text-text-muted">
        <span className="flex justify-between"><span>{t('treatment.surrealism')}</span><b className="text-text-secondary">{treatment.surrealism}%</b></span>
        <input type="range" min={0} max={100} step={5} value={treatment.surrealism}
          onChange={event => onChange({ surrealism: Number(event.target.value) })}
          className="mt-1 w-full accent-purple-400" />
      </label>
      <label className="block text-[9px] text-text-muted">{t('treatment.forbidden')}
        <input value={treatment.forbidden_elements} onChange={event => onChange({ forbidden_elements: event.target.value })} className={`${INPUT_CLASS} mt-1`} placeholder={t('treatment.forbiddenPlaceholder')} />
      </label>
    </>
  )
}

/** The editable music-video treatment shown before shot planning. */
export function MusicVideoTreatmentEditor({ treatment, onChange }: { treatment: MusicVideoTreatment; onChange: Change }) {
  const { t } = useUiTranslation('director')
  return (
    <div className="space-y-3">
      <div>
        <div className="flex items-center gap-1.5 text-xs font-medium text-text-primary">
          <Sparkles size={12} className="text-purple-300" /> {t('treatment.title')}
        </div>
        <p className="mt-1 text-[9px] leading-relaxed text-text-muted">
          {t('treatment.intro')}
        </p>
      </div>

      <GenerationModeField treatment={treatment} onChange={onChange} />
      <PerformanceFields treatment={treatment} onChange={onChange} />

      <label className="block text-[9px] text-text-muted">{t('treatment.recurringSets')}
        <textarea value={treatment.recurring_sets.join('\n')} rows={3}
          onChange={event => onChange({ recurring_sets: event.target.value.split('\n').map(item => item.trim()).filter(Boolean).slice(0, 5) })}
          className={`${INPUT_CLASS} mt-1 resize-none`} placeholder={t('treatment.recurringSetsPlaceholder')} />
      </label>
      <ChorusSetField treatment={treatment} onChange={onChange} />
      <CoverageField treatment={treatment} onChange={onChange} />

      <LookFields treatment={treatment} onChange={onChange} />
    </div>
  )
}

/** One line under the user's bubble: mode, performance share and recurring sets. */
export function TreatmentSummary({ treatment }: { treatment: MusicVideoTreatment }) {
  const { t } = useUiTranslation('director')
  return (
    <>
      {t('treatment.summary', {
        mode: t(MODE_LABEL_KEYS[treatment.mode] || MODE_LABEL_KEYS.hybrid),
        presence: treatment.performer_presence,
        count: treatment.recurring_sets.length,
      })}
    </>
  )
}
