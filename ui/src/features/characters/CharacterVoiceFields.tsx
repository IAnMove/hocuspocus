import { useCallback, useState } from 'react'
import { useUiTranslation } from '../../i18n'
import { CHARACTER_VOICES, isCharacterVoiceReady, type CharacterVoice } from '../../lib/characterVoice'
import type { CharacterKit } from '../../lib/characterKit'
import { CHARACTER_VOICE_PROFILES } from '../../lib/characterVoiceCatalog'
import { CharacterVoiceAudition } from './CharacterVoiceAudition'
import { CustomCharacterVoiceFields } from './CustomCharacterVoiceFields'

export function CharacterVoiceFields({ workspace, value, onChange, disabled, savedKits = [], onBusyChange }: {
  workspace: string; value?: CharacterVoice; onChange: (voice: CharacterVoice | undefined) => void; disabled?: boolean
  savedKits?: CharacterKit[]; onBusyChange?: (busy: boolean) => void
}) {
  const { t } = useUiTranslation('scene3dEditor')
  const [capturing, setCapturing] = useState(false)
  const captureBusy = useCallback((busy: boolean) => { setCapturing(busy); onBusyChange?.(busy) }, [onBusyChange])
  const voiceId = CHARACTER_VOICES.find(id => id === value?.voiceId)
  const profile = voiceId ? CHARACTER_VOICE_PROFILES[voiceId] : undefined
  const custom = value?.model === 'qwen3_tts_base' ? value : undefined
  const saved = savedKits.filter(kit => kit.voice?.model === 'qwen3_tts_base')
  const select = (id: string) => {
    if (id.startsWith('saved:')) { const kit = saved.find(kit => kit.id === id.slice(6)); if (kit?.voice) onChange(kit.voice); return }
    if (id === 'new-reference') {
      onChange({ provider: 'local', model: 'qwen3_tts_base', voiceId: 'reference', name: '', referenceAudio: '', transcript: '', language: 'auto' }); return
    }
    onChange(id ? { provider: 'local', model: 'qwen3_tts_customvoice', voiceId: id,
      instructions: value?.model === 'qwen3_tts_customvoice' ? value.instructions : undefined } : undefined)
  }
  return <fieldset disabled={disabled} className="space-y-2 text-xs">
    <label className="block">{t('speech.libraryVoice')}
      <select data-testid="character-voice" disabled={capturing} className="mt-1 min-h-10 w-full rounded border border-border bg-bg-primary px-2" value={value?.voiceId ?? ''}
        onChange={e => select(e.target.value)}>
        <option value="">{t('speech.noPreferredVoice')}</option>
        {custom && <option value="reference">{custom.name || t('speech.customVoice.selected')}</option>}
        <option value="new-reference">{t('speech.customVoice.add')}</option>
        {saved.length > 0 && <optgroup label={t('speech.customVoice.saved')}>
          {saved.map(kit => <option key={kit.id} value={`saved:${kit.id}`}>{kit.voice?.model === 'qwen3_tts_base' ? kit.voice.name : kit.name} · {kit.name}</option>)}
        </optgroup>}
        {CHARACTER_VOICES.map(id => <option key={id} value={id}>{CHARACTER_VOICE_PROFILES[id].name} · {t(`speech.voiceOrigins.${CHARACTER_VOICE_PROFILES[id].origin}`)}</option>)}
      </select>
    </label>
    {profile && voiceId && <div className="space-y-1">
      <p className="font-medium">{t(`speech.voiceProfiles.${voiceId}`)}</p>
      <p className="text-text-secondary">{t('speech.voiceOrigin', { language: t(`speech.voiceOrigins.${profile.origin}`) })}</p>
    </div>}
    {custom && <CustomCharacterVoiceFields value={custom} onChange={onChange} onBusyChange={captureBusy} />}
    {value?.model === 'qwen3_tts_customvoice' && <label className="block">{t('speech.voiceDirection')}<textarea maxLength={1000} rows={2}
      className="mt-1 w-full rounded border border-border bg-bg-primary p-2" value={value.instructions ?? ''}
      onChange={e => onChange({ ...value, instructions: e.target.value })} /></label>}
    {!custom && <p className="text-text-muted">{t('speech.voiceHint')}</p>}
    {value && !capturing && isCharacterVoiceReady(value) && <CharacterVoiceAudition key={JSON.stringify([workspace, value])} workspace={workspace} voice={value} />}
    {custom && !isCharacterVoiceReady(custom) && <p role="status" className="text-amber-200">{t('speech.customVoice.incomplete')}</p>}
  </fieldset>
}
