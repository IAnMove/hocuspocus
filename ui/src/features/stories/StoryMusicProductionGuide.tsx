import { RefreshCcw } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { button, input, requiredInput } from './storyLabChrome'
import type { StoryProductionsTabProps } from './storyLabProductions'

export function StoryMusicProductionGuide(props: StoryProductionsTabProps) {
  const { t } = useUiTranslation('storyLab')
  const {
    project, patch, directReferenceVideo, directMusicVideo, approvedVisualReferenceCount,
    directReferenceVideoReady, directReferenceVideoSupported, directVideoMasterReady,
  } = props
  return (
    <div className="rounded-lg border border-fuchsia-500/35 bg-fuchsia-500/5 p-2.5 space-y-2.5">
      <div>
        <p className="text-[10px] font-medium text-fuchsia-200">{t('productions.howToGenerate')}</p>
        <p className="mt-0.5 text-[9px] leading-relaxed text-text-muted">{t('productions.howToGenerateHint')}</p>
      </div>
      <div className="grid gap-1.5 md:grid-cols-3">
        <button type="button" onClick={() => patch({ musicVideoGenerationMode: 'image_guided' })}
          className={`${button} flex-col ${project.musicVideoGenerationMode === 'image_guided' ? 'border-pink-500/60 text-pink-300' : ''}`}>
          <span>{t('productions.withImages')}</span>
          <span className="text-[9px] text-text-muted">{t('productions.withImagesHint')}</span>
        </button>
        <button type="button" onClick={() => patch({ musicVideoGenerationMode: 'direct_references' })}
          className={`${button} flex-col ${directReferenceVideo ? 'border-violet-400/70 bg-violet-500/10 text-violet-200' : ''}`}>
          <span>{t('productions.directWithRefs')}</span>
          <span className="text-[9px] text-text-muted">{t('productions.h3NoStart')}</span>
        </button>
        <button type="button" disabled={project.protagonistConsistency} onClick={() => patch({ musicVideoGenerationMode: 'direct_video' })}
          className={`${button} flex-col ${directMusicVideo ? 'border-fuchsia-400/70 bg-fuchsia-500/10 text-fuchsia-200' : ''}`}>
          <span>{t('productions.directVideoNoImages')}</span>
          <span className="text-[9px] text-text-muted">{t('productions.pureT2v')}</span>
        </button>
      </div>
      {project.protagonistConsistency && <p className="text-[9px] text-amber-300">{t('productions.fixedProtagonist')}</p>}
      {directReferenceVideo && (
        <div className={`rounded-md border p-2 text-[9px] leading-relaxed ${directReferenceVideoReady
          ? 'border-emerald-500/35 bg-emerald-500/5 text-emerald-100'
          : 'border-amber-500/40 bg-amber-500/5 text-amber-200'}`}>
          {directReferenceVideoReady
            ? t('productions.refsRouted', { count: approvedVisualReferenceCount })
            : directReferenceVideoSupported
              ? t('productions.approveBeforeGenerate')
              : t('productions.h3OnlyMode')}
        </div>
      )}
      {directMusicVideo && (
        <div className="block text-[10px] text-violet-200">
          <div className="flex flex-wrap items-center gap-1.5">
            <span>{t('productions.masterPrompt')}<span className="ml-1 text-violet-300" title={t('chrome.required')}>●</span></span>
            <span className={`rounded-full border px-1.5 py-0.5 text-[9px] ${project.directVideoMasterPromptMode === 'inherit'
              ? 'border-violet-400/50 bg-violet-500/10 text-violet-200'
              : 'border-sky-400/50 bg-sky-500/10 text-sky-200'}`}>
              {project.directVideoMasterPromptMode === 'inherit' ? t('productions.inheritedStyles') : t('productions.customPrompt')}
            </span>
            {project.directVideoMasterPromptMode === 'custom' && (
              <button type="button" onClick={() => patch({ directVideoMasterPromptMode: 'inherit' })}
                className="ml-auto inline-flex items-center gap-1 rounded border border-violet-400/45 px-1.5 py-0.5 text-[9px] text-violet-200 hover:bg-violet-500/15"
                title={t('productions.useCurrentStylesTitle')}>
                <RefreshCcw size={10} /> {t('productions.useCurrentStyles')}
              </button>
            )}
          </div>
          <textarea className={`${input} ${requiredInput} mt-1 min-h-36 resize-y leading-relaxed`}
            value={project.directVideoMasterPrompt}
            onChange={event => patch({ directVideoMasterPromptMode: 'custom', directVideoMasterPrompt: event.target.value })}
            placeholder={t('productions.masterPlaceholder')} required aria-required="true" />
          <span className={`mt-1 block text-[9px] leading-relaxed ${directVideoMasterReady ? 'text-fuchsia-200/80' : 'text-amber-300'}`}>
            {directVideoMasterReady
              ? project.directVideoMasterPromptMode === 'inherit' ? t('productions.inheritReady') : t('productions.customReady')
              : t('productions.completeMasterOrStyle')}
          </span>
        </div>
      )}
    </div>
  )
}
