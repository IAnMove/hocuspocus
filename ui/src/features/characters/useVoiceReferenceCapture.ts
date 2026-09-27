import { useEffect, useRef, useState } from 'react'
import { useUiTranslation } from '../../i18n'
import { recordMicrophone } from '../scene3d/speech/microphone'
import { uploadVoiceReference } from './characterVoiceReference'

export function useVoiceReferenceCapture(onAudio: (url: string) => void, onBusyChange?: (busy: boolean) => void) {
  const { t } = useUiTranslation('scene3dEditor')
  const [state, setState] = useState<'idle' | 'permission' | 'recording' | 'uploading'>('idle')
  const [error, setError] = useState('')
  const owner = useRef<AbortController | null>(null), stop = useRef<() => void>(() => {})
  useEffect(() => () => owner.current?.abort(), [])
  useEffect(() => { onBusyChange?.(state !== 'idle'); return () => onBusyChange?.(false) }, [state, onBusyChange])
  const cancel = () => { owner.current?.abort(); setState('idle') }
  const fail = (cause: unknown, signal: AbortSignal) => {
    if (signal.aborted) return
    const error = cause as Error
    const known = (['voiceFileSize', 'voiceFileDecode', 'voiceFileDuration'] as const).find(key => key === error.message)
    setError(known ? t(`speech.customVoice.${known}`) : error.name === 'NotAllowedError'
      ? t('speech.microphoneDenied') : error.message || t('speech.recordingFailed'))
    setState('idle')
  }
  const upload = async (blob: Blob, signal: AbortSignal, source: 'import' | 'microphone') => {
    setState('uploading')
    try { const url = await uploadVoiceReference(blob, signal, source); if (!signal.aborted) { onAudio(url); setState('idle') } }
    catch (cause) { fail(cause, signal) }
  }
  const importAudio = (file: File) => {
    owner.current?.abort(); const request = new AbortController(); owner.current = request; setError('')
    void upload(file, request.signal, 'import')
  }
  const record = () => {
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      setError(t('speech.customVoice.microphoneUnavailable')); return
    }
    owner.current?.abort(); const request = new AbortController(); owner.current = request
    setError(''); setState('permission')
    void recordMicrophone(request.signal, {
      onRecording: () => setState('recording'), onComplete: blob => { void upload(blob, request.signal, 'microphone') },
      onError: cause => fail(cause, request.signal),
    }, 30).then(finish => { if (!request.signal.aborted) stop.current = finish }).catch(cause => fail(cause, request.signal))
  }
  return { state, error, cancel, importAudio, record, stop: () => stop.current() }
}
