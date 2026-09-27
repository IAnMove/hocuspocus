import { useEffect, useRef, useState } from 'react'
import { useUiTranslation } from '../../../i18n'
import { Scene3DSpeechControls, type SpeechControlsProps } from './Scene3DSpeechControls'
import { defaultSpeech, type Scene3DSpeech, type SpeechClip } from './types'
import { parseSpeech } from './track'
import { speechClips } from './timeline'
import { faceSettings, loadFaceProfile, saveFaceProfile } from './profiles'
import { SpeechNumber, speechInput } from './FaceControls'
import { CharacterDefinitionEditor } from '../../characters/CharacterDefinitionEditor'
import { GenerateCharacterLine } from './GenerateCharacterLine'
import { randomUuid } from '../../../lib/uuid'

export function Scene3DSpeakerControls(props: SpeechControlsProps) {
  const { t } = useUiTranslation('scene3dEditor')
  const stored = props.slot.speech ?? { ...defaultSpeech(), enabled: false }
  const [selected, setSelected] = useState(0)
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [childBusy, setChildBusy] = useState(false)
  const [definitionBusy, setDefinitionBusy] = useState(false), [voiceBusy, setVoiceBusy] = useState(false)
  const locks = { profile: busy, controls: childBusy, definition: definitionBusy, voice: voiceBusy }
  const isLocked = (except?: keyof typeof locks) => Boolean(props.disabled) || Object.entries(locks).some(([key, value]) => key !== except && value)
  const locked = isLocked()
  const [profileRevision, setProfileRevision] = useState<{ digest: string; revision: number }>()
  const alive = useRef(true)
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])
  const clips = speechClips(stored), index = Math.min(selected, Math.max(0, clips.length - 1)), clip = clips[index]
  const editing = clip ? { ...stored, ...clip, clips: undefined } : { ...stored, clips: undefined }
  const commit = (next: Scene3DSpeech) => {
    if (!alive.current) return
    try { props.onChange(parseSpeech(next)!); setNotice('') }
    catch (error) { setNotice(error instanceof Error ? error.message : String(error)) }
  }
  const change = (next: Scene3DSpeech) => {
    if (!stored.clips) { commit(next); return }
    const updated: SpeechClip = { ...clip, audio: next.audio, cues: next.cues, driver: next.driver,
      start: next.start, offset: next.offset, end: next.end, gain: next.gain, audible: next.audible }
    commit({ ...stored, ...faceSettings(next), enabled: next.enabled, clips: clips.map((item, i) => i === index ? updated : item) })
  }
  return <div className="space-y-2">
    <Scene3DSpeechControls key={clip?.id ?? 'voice'} {...props} onBusyChange={setChildBusy} disabled={isLocked('controls')} slot={{ ...props.slot, speech: editing }} onChange={change} />
    <details open={stored.clips ? true : undefined} className="space-y-2 rounded-lg border border-border bg-bg-secondary p-3">
      <summary className="cursor-pointer text-xs font-semibold">{t('speech.interventions')}</summary>
      {stored.clips && <select className={speechInput + ' w-full'} aria-label={t('speech.intervention')} value={index}
        disabled={locked} onChange={event => setSelected(Number(event.target.value))}>
        {clips.map((item, i) => <option key={item.id} value={i}>{i + 1} · {item.start.toFixed(2)}–{item.end?.toFixed(2) ?? '…'} s · {item.text || item.audio?.filename || t('speech.voice')}</option>)}
      </select>}
      <button className={speechInput} disabled={locked || clips.length >= 32} onClick={() => {
        const existing = (stored.clips || stored.audio || stored.cues.length) ? clips.map(item => ({ ...item, end: item.end ?? Math.min(600, item.start + Math.max(.1, (item.cues.at(-1)?.end ?? 5) - item.offset)) })) : []
        const start = Math.max(0, ...existing.map(item => item.end))
        if (start >= 600) return
        commit({ ...stored, clips: [...existing, { id: randomUuid(), start, end: Math.min(600, start + 5),
          offset: 0, gain: 1, cues: [], driver: 'imported' }] })
        setSelected(existing.length)
      }}>{t('speech.addIntervention')}</button>
      {stored.clips && clip && <label className="block text-xs">{t('speech.literalText')}<textarea className={speechInput + ' mt-1 w-full'} value={clip.text ?? ''}
        disabled={locked} maxLength={4000} onChange={event => commit({ ...stored, clips: clips.map((item, i) => i === index ? { ...item, text: event.target.value } : item) })} /></label>}
      {stored.clips && clip && <GenerateCharacterLine key={clip.id} clip={clip} voice={props.slot.character?.voice} workspace={props.workspace}
        disabled={isLocked('voice')} onBusyChange={setVoiceBusy}
        onChange={next => { commit({ ...stored, clips: clips.map((item, i) => i === index ? next : item) }); props.onFit(next.end!) }} />}
    </details>

    <fieldset disabled={locked} className="space-y-2 rounded-lg border border-border p-3 text-xs">
      <SpeechNumber label={t('speech.end')} value={interventionEnd(editing)}
        min={editing.start + .01} max={600} step={.1} onChange={end => { if (!locked) change({ ...editing, end }) }} />
      <label className="flex items-center gap-2"><input type="checkbox" disabled={locked} checked={editing.audible !== false}
        onChange={event => change({ ...editing, audible: event.target.checked })} />{t('speech.playVoice')}</label>
      <p className="text-text-muted">{t('speech.playVoiceHint')}</p>
      <button className={speechInput} disabled={locked || !stored.face || !props.slot.sourceUrl} onClick={() => {
        setBusy(true); setNotice('')
        void (async () => {
          const known = profileRevision ?? await loadFaceProfile(props.slot.sourceUrl, props.workspace)
          // An existing profile must be explicitly loaded before overwriting it.
          if (!profileRevision && known.revision > 0) throw new Error(t('speech.loadBeforeSave'))
          const saved = await saveFaceProfile(known.digest, props.workspace, known.revision, stored)
          setProfileRevision({ digest: known.digest, revision: saved.revision }); setNotice(t('speech.profileSaved'))
        })().catch(error => setNotice(error.message)).finally(() => setBusy(false))
      }}>{t('speech.saveProfile')}</button>
      <button className={speechInput} disabled={locked || !props.slot.sourceUrl} onClick={() => {
        setBusy(true)
        void loadFaceProfile(props.slot.sourceUrl, props.workspace).then(profile => {
          setProfileRevision(profile)
          if (profile.settings) { commit({ ...stored, ...profile.settings }); setNotice(t('speech.profileLoaded')) }
          else setNotice(t('speech.profileMissing'))
        }).catch(error => setNotice(error.message)).finally(() => setBusy(false))
      }}>{t('speech.loadProfile')}</button>
      {notice && <p role="status">{notice}</p>}
    </fieldset>
    <details className="rounded border border-border p-2"><summary className="cursor-pointer text-xs">{t('speech.characterLibraryAdvanced')}</summary>
    <CharacterDefinitionEditor workspace={props.workspace} slot={props.slot} disabled={isLocked('definition')}
      onApply={props.onImport} onBusyChange={setDefinitionBusy} />
    </details>
  </div>
}

function interventionEnd(speech: Scene3DSpeech) {
  return speech.end ?? Math.max(speech.start + .1, speech.start + (speech.cues.at(-1)?.end ?? 5) - speech.offset)
}
