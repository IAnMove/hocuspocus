import { useEffect, useMemo, useRef, useState } from 'react'
import i18n, { useUiTranslation } from '../../i18n'
import type { Scene } from '../../types'
import { EXPANDED_CATALOG_VERSION as CATALOG_VERSION, ALL_SCENE_TEMPLATES as CANDIDATE_SCENE_TEMPLATES, CANDIDATE_SCENE_TEMPLATES as LEGACY_TEMPLATES, getCandidateSceneTemplate } from './catalog'
import { candidateDemoScene } from './demoScenes'
import { loadRenderedReferenceScene } from './previewSnapshot'
import { loadCatalogReview, saveCatalogReview } from './catalogReview'
import {
  createReviewChoices,
  createReviewExport,
  updateReviewChoice,
  type ReviewChoice,
  type ReviewDecision,
  type ReviewChoicesState,
} from './reviewDecisions'

export interface SceneTemplateGalleryProps {
  onOpenScene: (scene: Scene) => void
  previewBaseUrl?: string
}

type DemoVariant = 'coral' | 'teal'
type Family = 'cinema' | 'music' | 'space'

const FAMILY_LABEL_KEY = {
  cinema: 'candidateGallery.families.cinema',
  music: 'candidateGallery.families.music',
  space: 'candidateGallery.families.space',
} as const
const FAMILY_ORDER: Family[] = ['cinema', 'music', 'space']
const ORIGINAL_REFERENCE_IDS = new Set(LEGACY_TEMPLATES.map(template => template.id))

const templateRefs = () => CANDIDATE_SCENE_TEMPLATES.map(template => ({ id: template.id, version: template.version }))

const initialReview = () => {
  const refs = templateRefs()
  const blank = createReviewChoices(CATALOG_VERSION, refs)
  if (typeof window === 'undefined') return { state: blank }
  try {
    return loadCatalogReview(window.localStorage)
  } catch {
    return { state: blank, warning: i18n.t('scene3d:candidateGallery.storageOpenPending') }
  }
}

const reviewTone: Record<ReviewDecision, string> = {
  pending: 'border-border text-text-muted',
  keep: 'border-emerald-400/50 bg-emerald-400/10 text-emerald-100',
  discard: 'border-rose-400/50 bg-rose-400/10 text-rose-100',
}

const REVIEW_LABEL_KEY = {
  pending: 'candidateGallery.decisions.pending',
  keep: 'candidateGallery.decisions.keep',
  discard: 'candidateGallery.decisions.discard',
} as const

const errorMessage = (reason: unknown) => reason instanceof Error ? reason.message : i18n.t('scene3d:candidateGallery.openSceneFailed')

export function SceneTemplateGallery({ onOpenScene, previewBaseUrl = '/scene-template-previews' }: SceneTemplateGalleryProps) {
  const { t } = useUiTranslation('scene3dEditor')
  const { t: tScene } = useUiTranslation('scene3d')
  const [initial] = useState(initialReview)
  const [reviews, setReviews] = useState<ReviewChoicesState>(initial.state)
  const [storageWarning, setStorageWarning] = useState(initial.warning || '')
  const [query, setQuery] = useState('')
  const [family, setFamily] = useState<'all' | Family>('all')
  const [variantById, setVariantById] = useState<Record<string, DemoVariant>>({})
  const [activePreview, setActivePreview] = useState<string | null>(null)
  const [previewErrors, setPreviewErrors] = useState<Record<string, boolean>>({})
  const [copiedId, setCopiedId] = useState<string | null>(null)
  const [actionErrors, setActionErrors] = useState<Record<string, string>>({})
  const referenceRequest = useRef<AbortController | null>(null)
  const [loadingReference, setLoadingReference] = useState<string | null>(null)
  useEffect(() => () => referenceRequest.current?.abort(), [])

  useEffect(() => {
    if (typeof window === 'undefined') return
    try {
      if (saveCatalogReview(window.localStorage, reviews)) return
      setStorageWarning(i18n.t('scene3d:candidateGallery.saveSessionOnly'))
    } catch {
      setStorageWarning(i18n.t('scene3d:candidateGallery.storageSessionOnly'))
    }
  }, [reviews])

  const visibleTemplates = useMemo(() => {
    const search = query.trim().toLocaleLowerCase()
    return CANDIDATE_SCENE_TEMPLATES.filter(template => (family === 'all' || template.family === family)
      && `${template.title} ${template.description} ${template.id}`.toLocaleLowerCase().includes(search))
  }, [family, query])

  const groupedTemplates = useMemo(() => FAMILY_ORDER
    .map(item => ({ family: item, templates: visibleTemplates.filter(template => template.family === item) }))
    .filter(group => group.templates.length > 0), [visibleTemplates])

  const counts = useMemo(() => Object.values(reviews.choices).reduce((result, choice) => {
    result[choice.decision] += 1
    return result
  }, { pending: 0, keep: 0, discard: 0 } as Record<ReviewDecision, number>), [reviews])

  const openScene = (id: string, variant: DemoVariant) => {
    referenceRequest.current?.abort()
    setLoadingReference(null)
    try {
      const template = getCandidateSceneTemplate(id)
      onOpenScene(candidateDemoScene(template.id, variant))
      setActionErrors(current => ({ ...current, [id]: '' }))
    } catch (reason) {
      setActionErrors(current => ({ ...current, [id]: errorMessage(reason) }))
    }
  }

  const openReference = async (id: string) => {
    referenceRequest.current?.abort()
    const request = new AbortController()
    referenceRequest.current = request
    setLoadingReference(id)
    setActionErrors(current => ({ ...current, [id]: '' }))
    try {
      const scene = await loadRenderedReferenceScene(getCandidateSceneTemplate(id), previewBaseUrl, request.signal)
      if (!request.signal.aborted) onOpenScene(scene)
    } catch (reason) {
      if (!request.signal.aborted) setActionErrors(current => ({ ...current, [id]: errorMessage(reason) }))
    } finally {
      if (!request.signal.aborted) setLoadingReference(null)
    }
  }

  const copyPrompt = async (id: string, prompt: string) => {
    try {
      if (!navigator.clipboard) throw new Error('clipboard unavailable')
      await navigator.clipboard.writeText(prompt)
      setCopiedId(id)
      window.setTimeout(() => setCopiedId(current => current === id ? null : current), 1_500)
    } catch {
      setActionErrors(current => ({ ...current, [id]: tScene('candidateGallery.copyPromptFailed') }))
    }
  }

  const exportReviews = () => {
    try {
      const payload = JSON.stringify(createReviewExport(reviews), null, 2)
      const blob = new Blob([payload], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = `scene-template-review-${CATALOG_VERSION}.json`
      anchor.click()
      URL.revokeObjectURL(url)
    } catch {
      setStorageWarning(tScene('candidateGallery.exportFailed'))
    }
  }

  const setDecision = (id: string, decision: ReviewDecision, notes?: string) => {
    setReviews(current => updateReviewChoice(current, id, decision, notes))
  }

  return (
    <section className="space-y-4" aria-label={tScene('candidateGallery.ariaLabel')}>
      <header className="rounded-xl border border-border bg-bg-secondary/70 p-4">
        <div className="flex flex-wrap items-start gap-3">
          <div className="min-w-0 flex-1">
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-violet-300">{tScene('candidateGallery.eyebrow')}</p>
            <h2 className="mt-1 text-lg font-semibold text-text-primary">{tScene('candidateGallery.title')}</h2>
            <p className="mt-1 max-w-3xl text-xs leading-5 text-text-secondary">
              {tScene('candidateGallery.intro', { count: CANDIDATE_SCENE_TEMPLATES.length })}
            </p>
          </div>
          <button type="button" onClick={exportReviews} className="rounded-lg border border-violet-300/40 bg-violet-400/10 px-3 py-2 text-xs font-medium text-violet-100 hover:bg-violet-400/20">
            {tScene('candidateGallery.exportJson')}
          </button>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-text-muted">
          <span className="rounded-full border border-border px-2 py-1">{tScene('candidateGallery.catalogVersion', { version: CATALOG_VERSION })}</span>
          <span>{tScene('candidateGallery.pendingCount', { count: counts.pending })}</span>
          <span>{tScene('candidateGallery.keepCount', { count: counts.keep })}</span>
          <span>{tScene('candidateGallery.discardCount', { count: counts.discard })}</span>
        </div>
        {storageWarning && <p role="status" className="mt-3 rounded-lg border border-amber-400/30 bg-amber-400/10 px-3 py-2 text-xs text-amber-100">{storageWarning}</p>}
      </header>

      <div className="flex flex-wrap gap-2" role="tablist" aria-label={tScene('candidateGallery.filterFamilies')}>
        <button type="button" role="tab" aria-selected={family === 'all'} onClick={() => setFamily('all')} className={`rounded-lg border px-3 py-1.5 text-xs ${family === 'all' ? 'border-violet-300/60 bg-violet-400/15 text-violet-100' : 'border-border text-text-muted hover:bg-bg-hover'}`}>
          {tScene('candidateGallery.allCount', { count: CANDIDATE_SCENE_TEMPLATES.length })}
        </button>
        {FAMILY_ORDER.map(item => {
          const count = CANDIDATE_SCENE_TEMPLATES.filter(template => template.family === item).length
          return <button key={item} type="button" role="tab" aria-selected={family === item} onClick={() => setFamily(item)} className={`rounded-lg border px-3 py-1.5 text-xs ${family === item ? 'border-violet-300/60 bg-violet-400/15 text-violet-100' : 'border-border text-text-muted hover:bg-bg-hover'}`}>{tScene(FAMILY_LABEL_KEY[item])} ({count})</button>
        })}
      </div>

      <label className="flex flex-wrap items-center gap-3 text-sm text-text-secondary">{t('gallerySearch')}
        <input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder={t('galleryPlaceholder')} className="min-h-11 min-w-0 flex-1 rounded-lg border border-border bg-bg-secondary px-3 text-text-primary" />
        <span role="status">{t('galleryCount', { count: visibleTemplates.length })}</span>
      </label>
      <div className="space-y-6">
        {groupedTemplates.map(group => (
          <section key={group.family} aria-labelledby={`scene-template-family-${group.family}`} className="space-y-3">
            <div className="flex items-baseline gap-2">
              <h3 id={`scene-template-family-${group.family}`} className="text-sm font-semibold text-text-primary">{tScene(FAMILY_LABEL_KEY[group.family])}</h3>
              <span className="text-xs text-text-muted">{tScene('candidateGallery.candidateCount', { count: group.templates.length })}</span>
            </div>
            <div className="grid gap-3 xl:grid-cols-2">
              {group.templates.map(template => {
                const choice: ReviewChoice = reviews.choices[template.id] || { id: template.id, templateVersion: template.version, decision: 'pending', notes: '' }
                const selectedVariant = variantById[template.id] || 'coral'
                const previewUrl = `${previewBaseUrl.replace(/\/+$/, '')}/${template.id}.mp4`
                const hasReference = ORIGINAL_REFERENCE_IDS.has(template.id)
                const sampleNote = hasReference ? tScene('candidateGallery.coralSample') : tScene('candidateGallery.candidateOnly')
                const openReferenceLabel = loadingReference === template.id ? tScene('candidateGallery.loadingReference') : tScene('candidateGallery.openReference')
                const copyLabel = copiedId === template.id ? tScene('candidateGallery.copied') : tScene('candidateGallery.copy')
                return (
                  <article key={template.id} data-template-id={template.id} className="overflow-hidden rounded-xl border border-border bg-bg-secondary/60">
                    <div className="flex flex-wrap items-start gap-2 border-b border-border p-3">
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <h4 className="text-sm font-semibold text-text-primary">{template.title}</h4>
                          <span className={`rounded-full border px-2 py-0.5 text-xs ${reviewTone[choice.decision]}`}>{tScene(REVIEW_LABEL_KEY[choice.decision])}</span>
                        </div>
                        <p className="mt-1 text-xs text-text-muted">{tScene('candidateGallery.cardMeta', { id: template.id, version: template.version, duration: template.defaultDuration })}</p>
                      </div>
                      <span className="rounded-full border border-border px-2 py-1 text-xs text-text-muted">{tScene(FAMILY_LABEL_KEY[template.family as Family])}</span>
                    </div>

                    <div className="relative aspect-video overflow-hidden bg-slate-950">
                      {!hasReference ? <p className="flex h-full items-center justify-center p-4 text-center text-xs text-text-muted">{tScene('candidateGallery.noCoralReference')}</p> : activePreview === template.id
                        ? <video className="h-full w-full" controls autoPlay muted playsInline loop preload="none" src={previewUrl} aria-label={tScene('candidateGallery.coralPreviewAria', { title: template.title })} onError={() => setPreviewErrors(current => ({ ...current, [template.id]: true }))} />
                        : <img loading="lazy" src={`${previewBaseUrl}/${template.id}.png`} alt={tScene('candidateGallery.reviewFrameAlt', { title: template.title })} className="h-full w-full object-contain" onError={event => { event.currentTarget.style.visibility = 'hidden'; setPreviewErrors(current => ({ ...current, [template.id]: true })) }} />}
                      {hasReference && activePreview !== template.id && <button type="button" onClick={() => setActivePreview(template.id)} className="absolute inset-0 flex items-center justify-center bg-black/10 text-lg font-semibold text-white hover:bg-black/25"><span className="rounded-xl border border-cyan-100 bg-cyan-300 px-6 py-4 text-base font-bold text-slate-950 shadow-xl">{tScene('candidateGallery.watchScene', { duration: template.defaultDuration })}</span></button>}
                      {previewErrors[template.id] && <p role="alert" className="absolute inset-x-0 bottom-0 bg-black/85 p-3 text-xs text-amber-200">{tScene('candidateGallery.previewNotRendered')}</p>}
                    </div>
                    <div className="space-y-3 p-3">
                      <p className="text-xs leading-5 text-text-secondary">{template.description}</p>
                      <div className="grid gap-3 sm:grid-cols-2">
                        <div>
                          <p className="text-xs font-semibold uppercase tracking-wide text-text-muted">{tScene('candidateGallery.slots')}</p>
                          <ul className="mt-1 space-y-1 text-xs text-text-secondary">
                            {template.slots.map(slot => <li key={slot.id}><span className="font-medium text-text-primary">{slot.id}</span> · {slot.required ? tScene('candidateGallery.slotRequired') : tScene('candidateGallery.slotOptional')} · {slot.kinds.join(', ')}<p className="mt-0.5 text-text-muted">{slot.description}</p></li>)}
                          </ul>
                        </div>
                        <div>
                          <p className="text-xs font-semibold uppercase tracking-wide text-text-muted">{tScene('candidateGallery.limits')}</p>
                          <ul className="mt-1 space-y-1 text-xs text-text-secondary">
                            {template.limits.map(limit => <li key={limit}>• {limit}</li>)}
                          </ul>
                        </div>
                      </div>

                      <div className="rounded-lg border border-border bg-bg-primary/50 p-2">
                        <div className="flex items-center justify-between gap-2">
                          <p className="text-xs font-semibold uppercase tracking-wide text-text-muted">{tScene('candidateGallery.examplePrompt')}</p>
                          <button type="button" onClick={() => void copyPrompt(template.id, template.promptExample)} className="text-xs text-violet-200 hover:text-violet-100">{copyLabel}</button>
                        </div>
                        <p className="mt-1 text-xs leading-4 text-text-secondary">{template.promptExample}</p>
                      </div>

                      <p className="text-xs text-text-muted">{sampleNote}</p>

                      <div className="flex flex-wrap items-center gap-2">
                        <button type="button" data-testid={`open-scene-${template.id}`} disabled={!hasReference || loadingReference === template.id} onClick={() => void openReference(template.id)} className="rounded-lg bg-violet-500 px-3 py-2 text-xs font-semibold text-white hover:bg-violet-400 disabled:opacity-50">{openReferenceLabel}</button>
                        <select aria-label={tScene('candidateGallery.variantAria', { title: template.title })} value={selectedVariant} onChange={event => setVariantById(current => ({ ...current, [template.id]: event.target.value as DemoVariant }))} className="rounded-lg border border-border bg-bg-primary px-2 py-2 text-xs text-text-primary">
                          <option value="coral">{tScene('candidateGallery.coralVariant')}</option>
                          <option value="teal">{tScene('candidateGallery.tealVariant')}</option>
                        </select>
                        <button type="button" data-testid={`open-scene-variant-${template.id}`} onClick={() => openScene(template.id, selectedVariant)} className="rounded-lg border border-violet-300/40 px-3 py-2 text-xs text-violet-100 hover:bg-violet-400/10">{tScene('candidateGallery.createWithTemplate')}</button>
                      </div>
                      <p className="text-xs text-text-muted">{tScene('candidateGallery.openVersusCreate')}</p>
                      {selectedVariant === 'teal' && <p className="text-xs text-teal-200">{tScene('candidateGallery.tealNote')}</p>}
                      {actionErrors[template.id] && <p role="alert" className="text-xs text-rose-200">{actionErrors[template.id]}</p>}

                      <div className="border-t border-border pt-3">
                        <div className="flex flex-wrap gap-2">
                          {(['pending', 'keep', 'discard'] as ReviewDecision[]).map(decision => <button key={decision} type="button" aria-pressed={choice.decision === decision} onClick={() => setDecision(template.id, decision)} className={`rounded border px-2 py-1 text-xs ${choice.decision === decision ? reviewTone[decision] : 'border-border text-text-muted hover:bg-bg-hover'}`}>{tScene(REVIEW_LABEL_KEY[decision])}</button>)}
                        </div>
                        <label className="mt-2 block text-xs text-text-muted">{tScene('candidateGallery.reviewNotes')}
                          <textarea value={choice.notes} maxLength={4_000} onChange={event => setDecision(template.id, choice.decision, event.target.value)} rows={2} className="mt-1 w-full rounded-lg border border-border bg-bg-primary p-2 text-xs text-text-primary outline-none focus:border-violet-300" placeholder={tScene('candidateGallery.notesPlaceholder')} />
                        </label>
                      </div>
                    </div>
                  </article>
                )
              })}
            </div>
          </section>
        ))}
      </div>
    </section>
  )
}
