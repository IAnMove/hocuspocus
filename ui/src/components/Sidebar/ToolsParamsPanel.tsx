import { useFieldIds } from '../common/fieldIds'
import { Mic } from 'lucide-react'
import { useWangpProcessors } from './useWangpProcessors'
import { WangpProcessorOptions } from './WangpProcessorOptions'
import { useStore } from '../../stores/useStore'
import type { ApiOutput } from '../../api/outputs'
import { AssetInput } from '../../features/asset-picker/AssetInput.tsx'
import { useUiTranslation } from '../../i18n'
import type { ToolsPanelTool } from './ToolsSourcePanel'

const upscaleMethods = [
  { value: 'flashvsr2', label: 'FlashVSR 2x' },
  { value: 'flashvsr3', label: 'FlashVSR 3x' },
  { value: 'flashvsr4', label: 'FlashVSR 4x' },
  { value: 'flashvsr2pass2', label: 'FlashVSR Two Pass 2x' },
  { value: 'flashvsr2pass4', label: 'FlashVSR Two Pass 4x' },
  { value: 'lanczos1.5', label: 'Lanczos 1.5x (fast)' },
  { value: 'lanczos2', label: 'Lanczos 2x (fast)' },
]

type VoiceReference = { filename: string; path: string } | null
type ParamsProps = {
  tool: ToolsPanelTool
  method: string
  setMethod: (method: string) => void
  flashvsrOff: boolean
  revoiceMode: 'single' | 'two'
  setRevoiceMode: (mode: 'single' | 'two') => void
  revoiceRefs: VoiceReference[]
  voiceItems: ApiOutput[]
  onChooseVoice: (index: number, item: ApiOutput | null) => void
  removeBackgroundInstruction: string
  setRemoveBackgroundInstruction: (instruction: string) => void
}

export function ToolsParamsPanel(props: ParamsProps) {
  if (props.tool === 'upscale') return <UpscaleParams {...props} />
  if (props.tool === 'revoice') return <RevoiceParams {...props} />
  return <RemoveBackgroundParams {...props} />
}

function UpscaleParams({ method, setMethod, flashvsrOff }: ParamsProps) {
  const fieldIds = useFieldIds()

  const processors = useWangpProcessors()
  const kind = useStore(s => s.toolsSourceKind)
  const { t } = useUiTranslation('studio')
  return (
    <div>
      <label htmlFor={fieldIds('f0')} className="text-[11px] text-text-muted uppercase tracking-wider mb-1.5 block">{t('tools.upscaleMethod')}</label>
      <select aria-label={t('tools.upscaleMethod')} id={fieldIds('f0')}
        value={method}
        onChange={event => setMethod(event.target.value)}
        className="w-full bg-bg-tertiary border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent-blue"
      >
        {upscaleMethods.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
        {processors.filter(option => !kind || option.media.includes(kind)).map(option => <option key={option.value} value={option.value} disabled={!option.enabled}>{option.label}{option.reason ? ` (${option.reason})` : ''}</option>)}
      </select>
      <WangpProcessorOptions processor={processors.find(option => option.value === method)} />
      {flashvsrOff && <p className="text-[10px] text-indicator-warning mt-1.5 leading-snug">{t('tools.flashvsrOff')}</p>}
      <p className="text-[10px] text-text-muted mt-1.5 leading-snug">{t('tools.upscaleHint')}</p>
    </div>
  )
}

function RevoiceParams(props: ParamsProps) {
  const { t } = useUiTranslation('studio')
  const { revoiceMode, setRevoiceMode } = props
  return (
    <div className="space-y-2">
      <label className="text-[11px] text-text-muted uppercase tracking-wider block">{t('tools.replaceVoice')}</label>
      <div className="flex gap-1.5 text-xs">
        {([['single', 'tools.singleVoice'], ['two', 'tools.twoVoices']] as const).map(([value, labelKey]) => (
          <button
            key={value}
            onClick={() => setRevoiceMode(value)}
            className={`flex-1 py-1.5 rounded-md border transition-colors ${revoiceMode === value ? 'bg-accent-blue/10 border-accent-blue text-text-primary' : 'bg-bg-tertiary border-border text-text-secondary hover:text-text-primary'}`}
          >
            {t(labelKey)}
          </button>
        ))}
      </div>
      <p className="text-[10px] text-text-muted leading-snug">{revoiceMode === 'single' ? t('tools.singleHint') : t('tools.twoHint')}</p>
      {[0, ...(revoiceMode === 'two' ? [1] : [])].map(index => <VoiceReferenceInput key={index} index={index} {...props} />)}
    </div>
  )
}

function VoiceReferenceInput({ index, ...props }: ParamsProps & { index: number }) {
  const { t } = useUiTranslation('studio')
  const { revoiceMode, revoiceRefs, voiceItems, onChooseVoice } = props
  const reference = revoiceRefs[index]
  const label = revoiceMode === 'two'
    ? (index === 0 ? t('tools.voiceA') : t('tools.voiceB'))
    : t('tools.referenceVoice')
  const workspaceId = useStore(s => s.activeWorkspace)
  const value = reference?.path
    ? { name: reference.filename, type: 'audio' as const, mode: null, size: 0, created_at: 0, url: '', thumbnail_url: '' }
    : undefined
  return (
    <div>
      <AssetInput
        label={label}
        placeholder={t('tools.uploadSample', { label: label.toLowerCase() })}
        items={voiceItems}
        value={value}
        accept="audio/*,video/*"
        workspaceId={workspaceId}
        optional
        constraints={{ kinds: ['audio', 'video'], maxCount: 1, optional: true }}
        onChoose={item => onChooseVoice(index, item)}
      />
      {reference?.path && (
        <div className="mt-1 flex items-center gap-2 bg-bg-tertiary border border-border rounded-lg px-2 py-1.5">
          <Mic size={12} className="text-accent-blue shrink-0" />
          <span className="flex-1 min-w-0 truncate text-[11px] text-text-primary">{reference.filename}</span>
        </div>
      )}
    </div>
  )
}

function RemoveBackgroundParams({ removeBackgroundInstruction, setRemoveBackgroundInstruction }: ParamsProps) {
  const fieldIds = useFieldIds()

  const { t } = useUiTranslation('studio')
  return (
    <div className="space-y-2">
      <label htmlFor={fieldIds('f0')} className="text-[11px] text-text-muted uppercase tracking-wider block">{t('tools.removeBackgroundInstruction')}</label>
      <textarea aria-label={t('tools.removeBackgroundInstruction')} id={fieldIds('f0')}
        value={removeBackgroundInstruction}
        onChange={event => setRemoveBackgroundInstruction(event.target.value)}
        placeholder={t('tools.removeBackgroundInstructionPlaceholder')}
        rows={3}
        className="w-full resize-y bg-bg-tertiary border border-border rounded-lg px-3 py-2 text-xs text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent-blue"
      />
      <p className="text-[10px] text-text-muted leading-snug">{t('tools.removeBackgroundHint')}</p>
    </div>
  )
}
