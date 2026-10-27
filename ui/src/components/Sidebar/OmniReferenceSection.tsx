import { useFieldIds } from '../common/fieldIds'
import { useMemo, useRef, useState } from 'react'
import { FileAudio, GripVertical, Image as ImageIcon, Info, Loader2, Plus, Video, X } from 'lucide-react'
import * as api from '../../api/client'
import { useStore } from '../../stores/useStore'
import { useUiTranslation } from '../../i18n'
import type { MiniMaxH3AudioIntent, MiniMaxH3Reference, MiniMaxH3ReferenceType } from '../../types'
import type { ApiOutput } from '../../api/outputs'
import { AssetInput } from '../../features/asset-picker/AssetInput.tsx'
import { applyChosenStudioMedia, studioMediaPath, useWorkspaceOutputs } from '../../lib/studioAssetPick.ts'

const IMAGE_RE = /\.(png|jpe?g|webp|bmp|tiff?)$/i
const VIDEO_RE = /\.(mp4|mov|mkv|webm|avi|m4v)$/i
const AUDIO_RE = /\.(wav|mp3|flac|ogg|m4a|aac)$/i

function mediaType(file: File): MiniMaxH3ReferenceType | null {
  if (file.type.startsWith('image/') || IMAGE_RE.test(file.name)) return 'image'
  if (file.type.startsWith('video/') || VIDEO_RE.test(file.name)) return 'video'
  if (file.type.startsWith('audio/') || AUDIO_RE.test(file.name)) return 'audio'
  return null
}

function newId(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`
}

export function OmniReferenceSection() {
  const fieldIds = useFieldIds()

  const { t } = useUiTranslation('studio')
  const params = useStore(s => s.params)
  const modelOptions = useStore(s => s.modelOptions)
  const setParam = useStore(s => s.setParam)
  const inputRef = useRef<HTMLInputElement>(null)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState('')
  const [dragIndex, setDragIndex] = useState<number | null>(null)
  const activeWorkspace = useStore(s => s.activeWorkspace)
  const imageItems = useWorkspaceOutputs(activeWorkspace, 'image')
  const videoItems = useWorkspaceOutputs(activeWorkspace, 'video')
  const audioItems = useWorkspaceOutputs(activeWorkspace, 'audio')
  const catalogItems = [...imageItems, ...videoItems, ...audioItems]

  const references = useMemo(() => params.minimax_h3_references ?? [], [params.minimax_h3_references])
  const limits = modelOptions?.omni_reference_limits ?? {
    image: 9, video: 3, audio: 3, total: 12,
  }
  const labels = useMemo(() => {
    let pictures = 0
    let videos = 0
    let audios = 0
    return references.map(reference => {
      const parts: string[] = []
      if (reference.type === 'audio' || (reference.type === 'video' && (reference.has_audio || reference.audio_path) && reference.include_audio !== false)) {
        parts.push(t('omni.audioN', { n: ++audios }))
      }
      if (reference.type === 'image') parts.push(t('omni.pictureN', { n: ++pictures }))
      if (reference.type === 'video') parts.push(t('omni.videoN', { n: ++videos }))
      return parts.join(' + ')
    })
  }, [references, t])

  const update = (next: MiniMaxH3Reference[]) => setParam('minimax_h3_references', next)

  const addFiles = async (files: File[]) => {
    if (uploading || files.length === 0) return
    setUploading(true)
    setError('')
    try {
      const next = [...references]
      const counts = {
        image: next.filter(item => item.type === 'image').length,
        video: next.filter(item => item.type === 'video').length,
        audio: next.filter(item => item.type === 'audio').length,
      }
      for (const file of files) {
        const type = mediaType(file)
        if (!type) {
          setError(t('omni.unsupported', { name: file.name }))
          continue
        }
        if (next.length >= limits.total || counts[type] >= limits[type]) {
          setError(t('omni.limit', { image: limits.image, video: limits.video, audio: limits.audio, total: limits.total }))
          break
        }
        const uploaded = type === 'audio'
          ? await api.uploadAudio(file)
          : await api.uploadImage(file)
        next.push({
          id: newId(),
          type,
          path: uploaded.path,
          filename: file.name,
          url: uploaded.url,
          duration_seconds: uploaded.duration_seconds ?? null,
          has_audio: type === 'video' ? Boolean('has_audio' in uploaded && uploaded.has_audio) : type === 'audio',
          include_audio: type === 'video' ? Boolean('has_audio' in uploaded && uploaded.has_audio) : undefined,
          audio_intent: type === 'audio' ? 'voice' : undefined,
          role: '',
        })
        counts[type] += 1
      }
      update(next)
    } catch (uploadError) {
      setError(uploadError instanceof Error ? uploadError.message : t('omni.uploadFailed'))
    } finally {
      setUploading(false)
      if (inputRef.current) inputRef.current.value = ''
    }
  }

  const patchReference = (index: number, patch: Partial<MiniMaxH3Reference>) => {
    update(references.map((reference, itemIndex) => itemIndex === index ? { ...reference, ...patch } : reference))
  }

  const chooseCatalog = (item: ApiOutput | null) => {
    if (!item) return
    const type: MiniMaxH3ReferenceType | null = item.type === 'image' || item.type === 'video' || item.type === 'audio' ? item.type : null
    if (!type) {
      setError(t('omni.unsupported', { name: item.name }))
      return
    }
    const next = [...(useStore.getState().params.minimax_h3_references ?? [])]
    const counts = {
      image: next.filter(entry => entry.type === 'image').length,
      video: next.filter(entry => entry.type === 'video').length,
      audio: next.filter(entry => entry.type === 'audio').length,
    }
    if (next.length >= limits.total || counts[type] >= limits[type]) {
      setError(t('omni.limit', { image: limits.image, video: limits.video, audio: limits.audio, total: limits.total }))
      return
    }
    applyChosenStudioMedia(item, media => {
      const live = [...(useStore.getState().params.minimax_h3_references ?? [])]
      if (live.length >= limits.total || live.filter(entry => entry.type === type).length >= limits[type]) return
      update([...live, {
        id: newId(),
        type,
        path: studioMediaPath(item),
        filename: item.name,
        url: item.url,
        duration_seconds: media.duration > 0 ? media.duration : null,
        has_audio: type === 'audio',
        audio_intent: type === 'audio' ? 'voice' : undefined,
        role: '',
      }])
    })
  }

  const chooseItemAudio = (referenceId: string, item: ApiOutput | null) => {
    if (!item) return
    const current = useStore.getState().params.minimax_h3_references ?? []
    update(current.map(reference => reference.id === referenceId ? {
      ...reference,
      audio_path: studioMediaPath(item),
      audio_filename: item.name,
      audio_duration_seconds: null,
      include_audio: true,
    } : reference))
  }

  const reorder = (from: number, to: number) => {
    if (from === to) return
    const next = [...references]
    const [item] = next.splice(from, 1)
    next.splice(to, 0, item)
    update(next)
  }

  const detail = params.minimax_h3_reference_detail
    ?? modelOptions?.omni_reference_detail_default
    ?? 'match'

  return (
    <section className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5">
          <label htmlFor={fieldIds('f0')} className="text-[11px] text-text-muted uppercase tracking-wider">{t('omni.title')}</label>
          <span
            title={t('omni.orderHint')}
            className="text-text-muted cursor-help"
          >
            <Info size={12} />
          </span>
        </div>
        <span className="text-[9px] text-text-muted">{references.length}/{limits.total}</span>
      </div>

      <div
        className="rounded-lg border border-dashed border-border hover:border-border-light px-3 py-2.5 flex items-center justify-center gap-2 cursor-pointer transition-colors"
        onClick={() => inputRef.current?.click()}
        onDragOver={event => event.preventDefault()}
        onDrop={event => {
          event.preventDefault()
          void addFiles(Array.from(event.dataTransfer.files))
        }}
      >
        {uploading ? <Loader2 size={14} className="animate-spin text-accent-blue" /> : <Plus size={14} className="text-text-muted" />}
        <span className="text-[10px] text-text-secondary">{uploading ? t('omni.uploading') : t('omni.add')}</span>
        <input aria-label={t('omni.title')} id={fieldIds('f0')}
          ref={inputRef}
          type="file"
          accept="image/*,video/*,audio/*,.mkv,.m4v,.flac,.m4a,.aac"
          multiple
          className="hidden"
          onChange={event => void addFiles(Array.from(event.target.files ?? []))}
        />
      </div>
      <AssetInput
        label={t('omni.add')}
        placeholder={t('omni.add')}
        items={catalogItems}
        accept="image/*,video/*,audio/*,.mkv,.m4v,.flac,.m4a,.aac"
        workspaceId={activeWorkspace}
        constraints={{ kinds: ['image', 'video', 'audio'], maxCount: 1, optional: false }}
        onChoose={chooseCatalog}
      />

      {references.length > 0 && (
        <div className="space-y-1.5">
          {references.map((reference, index) => (
            <div
              key={reference.id || `${reference.path}-${index}`}
              draggable
              onDragStart={() => setDragIndex(index)}
              onDragOver={event => event.preventDefault()}
              onDrop={event => {
                event.preventDefault()
                if (dragIndex !== null) reorder(dragIndex, index)
                setDragIndex(null)
              }}
              onDragEnd={() => setDragIndex(null)}
              className={`rounded-lg border bg-bg-tertiary p-2 flex gap-2 transition-colors ${dragIndex === index ? 'border-accent-blue' : 'border-border'}`}
            >
              <GripVertical size={14} className="mt-2 text-text-muted cursor-grab shrink-0" />
              <div className="w-12 h-12 rounded-md border border-border overflow-hidden bg-bg-primary flex items-center justify-center shrink-0">
                {reference.type === 'image' && reference.url ? (
                  <img src={reference.url} alt="" className="w-full h-full object-cover" />
                ) : reference.type === 'video' && reference.url ? (
                  <video src={reference.url} muted preload="metadata" className="w-full h-full object-cover" />
                ) : reference.type === 'audio' ? (
                  <FileAudio size={18} className="text-accent-blue" />
                ) : reference.type === 'video' ? (
                  <Video size={18} className="text-accent-blue" />
                ) : (
                  <ImageIcon size={18} className="text-accent-blue" />
                )}
              </div>
              <div className="min-w-0 flex-1 space-y-1">
                <div className="flex items-center gap-1.5">
                  <span className="text-[10px] font-medium text-text-primary">{labels[index]}</span>
                  <span className="text-[9px] text-text-muted truncate">{reference.filename}</span>
                </div>
                <input aria-label={t('omni.rolePlaceholder')}
                  value={reference.role ?? ''}
                  onChange={event => patchReference(index, { role: event.target.value })}
                  placeholder={t('omni.rolePlaceholder')}
                  className="w-full bg-bg-primary border border-border rounded px-2 py-1 text-[10px] text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent-blue"
                />
                {reference.type === 'audio' && (
                  <select
                    aria-label={t('omni.intentHint')}
                    value={reference.audio_intent ?? 'voice'}
                    onChange={event => patchReference(index, {
                      audio_intent: event.target.value as MiniMaxH3AudioIntent,
                    })}
                    title={t('omni.intentHint')}
                    className="w-full bg-bg-primary border border-border rounded px-2 py-1 text-[10px] text-text-secondary focus:outline-none focus:border-accent-blue"
                  >
                    <option value="voice">{t('omni.voiceRef')}</option>
                    <option value="drive">{t('omni.drive')}</option>
                    <option value="style">{t('omni.style')}</option>
                  </select>
                )}
                {reference.type === 'video' && (
                  <div className="flex items-center gap-1.5 text-[9px] text-text-secondary">
                    <AssetInput
                      label={reference.audio_path ? t('omni.replaceAudio') : t('omni.attachAudio')}
                      placeholder={t('omni.attachAudio')}
                      items={audioItems}
                      accept="audio/*,.flac,.m4a,.aac"
                      workspaceId={activeWorkspace}
                      constraints={{ kinds: ['audio'], maxCount: 1, optional: false }}
                      onChoose={item => { if (item) chooseItemAudio(reference.id, item) }}
                    />
                    {reference.audio_path && (
                      <button
                        type="button"
                        title={t('omni.removeSoundtrack')}
                        onClick={() => patchReference(index, {
                          audio_path: undefined,
                          audio_filename: undefined,
                          audio_duration_seconds: undefined,
                          include_audio: reference.has_audio === true,
                        })}
                        className="truncate text-text-muted hover:text-indicator-error"
                      >
                        × {reference.audio_filename || t('omni.attachedAudio')}
                      </button>
                    )}
                  </div>
                )}
                {reference.type === 'video' && (reference.has_audio || reference.audio_path) && (
                  <label className="flex items-center gap-1.5 text-[9px] text-text-secondary cursor-pointer">
                    <input aria-label={t('omni.includeSoundtrack')}
                      type="checkbox"
                      checked={reference.include_audio !== false}
                      onChange={event => patchReference(index, { include_audio: event.target.checked })}
                      className="w-3 h-3 accent-accent-blue"
                    />
                    {t('omni.includeSoundtrack')}
                  </label>
                )}
              </div>
              <button
                onClick={() => update(references.filter((_, itemIndex) => itemIndex !== index))}
                title={t('omni.removeRef')} aria-label={t('omni.removeRef')}
                className="p-1 self-start text-text-muted hover:text-indicator-error"
              >
                <X size={13} />
              </button>
            </div>
          ))}
        </div>
      )}

      {references.length > 0 && (
        <div className="flex items-center justify-end gap-2">
          <select
            aria-label={t('omni.detailHint')}
            value={detail}
            onChange={event => setParam('minimax_h3_reference_detail', event.target.value as 'match' | 'max')}
            title={t('omni.detailHint')}
            className="bg-bg-tertiary border border-border rounded px-2 py-1 text-[9px] text-text-secondary focus:outline-none focus:border-accent-blue"
          >
            {(modelOptions?.omni_reference_detail_choices ?? [
              [t('omni.match'), 'match'],
              [t('omni.max'), 'max'],
            ]).map(([label, value]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </div>
      )}

      {error && <p className="text-[9px] text-indicator-error">{error}</p>}
    </section>
  )
}
