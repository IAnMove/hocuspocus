import { ChevronDown, Check, Plus } from 'lucide-react'
import { useState, useRef, useEffect } from 'react'
import type { TFunction } from 'i18next'
import { useStore, getFamiliesForMode, getModelsForFamily } from '../../stores/useStore'
import { useUiTranslation } from '../../i18n'
import { h3CatalogEntry } from '../../lib/h3Catalog'
import { catalogVramGb, resolveModelCatalog } from '../../lib/modelCatalog'
import type { ModelDef } from '../../types'
import { InfoTooltip } from './InfoTooltip'
import { H3ModelName } from './H3ModelInfo'

export function ModelSelector() {
  const { t } = useUiTranslation('studio')
  const models = useStore(s => s.models)
  const families = useStore(s => s.families)
  const enabledModels = useStore(s => s.enabledModels)
  const generationMode = useStore(s => s.generationMode)
  const editSubMode = useStore(s => s.editSubMode)
  const currentModelType = useStore(s => s.params.model_type)
  const selectModel = useStore(s => s.selectModel)
  const openModelVisibility = useStore(s => s.openModelVisibility)
  // Mature Mode gate: models with nsfw_only flag are hidden from the
  // selector unless servicesConfig.nsfw_mode is enabled. Backend always
  // ships the entry (so the toggle can show/hide without a model reload)
  // but the UI clamps visibility here.
  const nsfwMode = useStore(s => s.servicesConfig?.nsfw_mode ?? false)

  const [open, setOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  // Close on click outside
  useEffect(() => {
    if (!open) return
    function handleClick(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [open])

  const audioSubMode = useStore(s => s.audioSubMode)

  const currentModel = models.find(m => m.model_type === currentModelType)
  const effectiveSubMode = generationMode === 'avatar' ? editSubMode : undefined
  const effectiveAudioSubMode = generationMode === 'audio' ? audioSubMode : undefined
  const modeFamilies = getFamiliesForMode(generationMode, families, effectiveSubMode, effectiveAudioSubMode)

  // Build grouped model list, filtered by:
  //   1. enabledModels (Settings → System → Model Visibility),
  //   2. nsfw_only gate (Mature Mode must be on for those to appear).
  const availableForFamily = (familyId: string) => getModelsForFamily(familyId, models, generationMode, effectiveSubMode)
    .filter(m => !m.tool_only)
    .filter(m => effectiveSubMode !== 'recast' || m.model_type !== 'viggle_animate')
    .filter(m => !m.nsfw_only || nsfwMode)
  const groups = modeFamilies.map(family => ({
    family,
    models: availableForFamily(family.id).filter(m => enabledModels.has(m.model_type)),
  })).filter(g => g.models.length > 0)

  // How many models are available for this mode but NOT enabled — powers the
  // "+N" hint that nudges users toward Settings → Enabled Models.
  const disabledCount = modeFamilies.reduce((n, family) => {
    const avail = availableForFamily(family.id)
    return n + avail.filter(m => !enabledModels.has(m.model_type)).length
  }, 0)

  if (effectiveSubMode === 'recast' && currentModelType === 'viggle_animate') {
    return <div data-wizard-anchor="model" className="rounded-lg border border-border bg-bg-tertiary px-2.5 py-2 text-xs">
      {currentModel?.name || 'Viggle-Animate'}
    </div>
  }

  return (
    <div className="relative flex-1 min-w-0" ref={containerRef} data-wizard-anchor="model">
      {/* Trigger button */}
      <button
        onClick={() => setOpen(!open)}
        title={currentModel ? selectorModelHelp(currentModel, t) : undefined}
        className="w-full flex items-center gap-1.5 bg-bg-tertiary border border-border rounded-lg px-2.5 py-2 text-left hover:border-border-light transition-colors"
      >
        <span className="flex-1 min-w-0 truncate text-xs text-text-primary">
          <H3ModelName modelType={currentModelType} fallback={currentModel?.name ?? t('model.select')} />
        </span>
        <ChevronDown size={14} className={`shrink-0 text-text-muted transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      {/* Dropdown (opens upward) */}
      {open && (
        <div className="absolute bottom-full left-0 mb-1 w-[360px] max-w-[90vw] bg-bg-secondary border border-border rounded-lg shadow-xl overflow-hidden z-50">
          {/* Enable-more entry — sits above the enabled model list; opens
              Settings → Enabled Models expanded to this mode. */}
          {disabledCount > 0 && (
            <button
              onClick={() => { openModelVisibility(generationMode); setOpen(false) }}
              className="w-full flex items-center gap-2 px-3 py-2 text-left border-b border-border text-text-secondary hover:bg-bg-hover hover:text-accent-blue transition-colors"
            >
              <Plus size={13} className="shrink-0" />
              <span className="flex-1 text-xs">{t('model.enableMore')}</span>
              <span className="text-[10px] text-text-muted shrink-0">{t('model.available', { count: disabledCount })}</span>
            </button>
          )}
          <div className="max-h-[360px] overflow-y-auto py-1">
            {groups.map(({ family, models: famModels }) => (
              <div key={family.id}>
                {/* Family header */}
                <div className="px-3 pt-2 pb-1 text-[10px] text-text-muted uppercase tracking-wider font-medium">
                  {family.label}
                </div>
                {/* Models in family */}
                {famModels.map(model => {
                  const isSelected = model.model_type === currentModelType
                  const help = selectorModelHelp(model, t)
                  const vramGb = catalogVramGb(model)
                  return (
                    <div
                      key={model.model_type}
                      className={`group w-full flex items-center transition-colors ${
                        isSelected
                          ? 'bg-accent-blue/10 text-text-primary'
                          : 'hover:bg-bg-hover text-text-secondary hover:text-text-primary'
                      }`}
                    >
                      <button
                        onClick={() => {
                          selectModel(model.model_type)
                          setOpen(false)
                        }}
                        className="min-w-0 flex-1 px-3 py-1.5 flex items-center gap-2 text-left"
                      >
                        <span className="flex-1 min-w-0 text-xs truncate"><H3ModelName modelType={model.model_type} fallback={model.name} /></span>
                        {vramGb != null && (
                          <span aria-hidden="true" className="shrink-0 text-[9px] text-text-muted tabular-nums">
                            {t('modelCatalog.vramBadge', { vram: vramGb })}
                          </span>
                        )}
                        <span aria-hidden="true"><ModelBadges model={model} /></span>
                        {isSelected && <Check size={12} className="shrink-0 text-accent-blue" />}
                      </button>
                      {help && (
                        <span className="pr-2">
                          <InfoTooltip
                            text={help}
                            label={t('model.about', { name: model.name })}
                          />
                        </span>
                      )}
                    </div>
                  )
                })}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function selectorModelHelp(model: ModelDef, t: TFunction<'studio'>): string {
  const h3 = h3CatalogEntry(model.model_type)
  if (h3) {
    return [t(`h3Catalog.${h3.variant}Hint`), t('h3Catalog.memory')].join('\n\n')
  }
  const catalog = resolveModelCatalog(model)
  return [
    t(`modelCatalog.${catalog.variant}Hint`),
    t(`modelCatalog.capability.${catalog.capability}`),
    catalog.requirements.vram_gb != null ? t('modelCatalog.vram', { vram: catalog.requirements.vram_gb }) : '',
    catalog.requirements.ram_gb != null ? t('modelCatalog.ram', { ram: catalog.requirements.ram_gb }) : '',
    catalog.requirements.storage_gb != null
      ? t('modelCatalog.storage', { storage: catalog.requirements.storage_gb })
      : '',
    t('modelCatalog.limit'),
  ].filter(Boolean).join('\n\n')
}

function ModelBadges({ model }: {
  model: {
    model_type: string
    is_i2v: boolean
    is_t2v: boolean
    supports_end_frame?: boolean
    supports_audio?: boolean
    supports_audio_input?: boolean
    generates_audio?: boolean
    supports_ref_images?: boolean
    resource_requirements?: { vram_gb?: number }
  }
}) {
  const { t } = useUiTranslation('studio')
  const badges: Array<{ label: string; title: string }> = []
  const workflowIsAlreadyInName = model.model_type.startsWith('minimax_h3')
  if (!workflowIsAlreadyInName && model.is_i2v && model.supports_end_frame) {
    badges.push({ label: t('model.firstLast'), title: t('model.firstLastHint') })
  } else if (!workflowIsAlreadyInName && model.is_i2v) {
    badges.push({ label: t('model.i2v'), title: t('model.i2vHint') })
  }
  if (model.generates_audio) {
    badges.push({ label: t('model.audioOut'), title: t('model.audioOutHint') })
  }
  if (model.supports_audio_input) {
    badges.push({ label: t('model.audioIn'), title: t('model.audioInHint') })
  }
  if (model.supports_ref_images) {
    badges.push({ label: t('model.refs'), title: t('model.refsHint') })
  }
  if (badges.length === 0) return null
  return (
    <span className="flex gap-0.5 shrink-0">
      {badges.map(b => (
        <span
          key={b.label}
          title={b.title}
          className="text-[9px] px-1 py-0.5 rounded bg-bg-tertiary text-text-muted leading-none"
        >
          {b.label}
        </span>
      ))}
    </span>
  )
}
