import { useCallback, useEffect, useRef, useState } from 'react'
import { Pencil, SlidersHorizontal, RefreshCw, Copy, Trash2, Check, Combine, Loader2, Heart, ArrowLeftToLine, Download, FolderInput, Scissors, FastForward, BookMarked, Film, BadgeInfo } from 'lucide-react'
import { editOutputImage, addOutputImageReference } from '../../features/studio/imageInputActions'
import { beginImageSettingsChange } from '../../features/studio/imageSettingsRestore'
import { outputImageUrl } from '../../lib/storedImageFiles'
import { SaveRecipeDialog } from '../Recipes/SaveRecipeDialog'
import { VideoExtraInfoDialog } from './VideoExtraInfoDialog'
import { MediaMoveDialog } from './MediaMoveDialog'
import { useUiTranslation } from '../../i18n'
import { useStore } from '../../stores/useStore'
import { fetchOutputMetadata, getFileUrl, moveOutput, uploadImage, selectPipelineClipVideo } from '../../api/client'
import type { OutputFile } from '../../types'
import {
  readVideoEditorReplacementTarget,
  writeVideoEditorReplacementResult,
} from '../../features/video-editor/replacementHandoff'
import { writeVideoEditorPendingSource } from '../../features/video-editor/editorHandoff'
import {
  readDirectorClipReplacementTarget,
  writeDirectorClipReplacementResult,
} from '../../features/stories/directorClipHandoff'

const CARD_BAR = 'flex h-11 w-full shrink-0 items-center gap-0.5 overflow-x-auto overscroll-x-contain [&>button]:flex [&>button]:items-center [&>button]:justify-center [&>button]:min-h-11 [&>button]:min-w-11 [&>button]:shrink-0 [&>a]:flex [&>a]:items-center [&>a]:justify-center [&>a]:min-h-11 [&>a]:min-w-11 [&>a]:shrink-0'
const DIALOG_BAR = 'flex flex-wrap items-center gap-1 [&>button]:flex [&>button]:items-center [&>button]:justify-center [&>button]:min-h-11 [&>button]:min-w-11 [&>button]:shrink-0'

type Params = Record<string, unknown> | null

/** Generation parameters for an output: the caller's copy when it has one,
 *  otherwise read from the output's sidecar. */
function useOutputParams(name: string, workspace: string, provided: Params | undefined): Params {
  const [loaded, setLoaded] = useState<{ key: string; params: Params } | null>(null)
  const key = `${workspace}:${name}`
  useEffect(() => {
    if (provided !== undefined) return
    const controller = new AbortController()
    fetchOutputMetadata(name, workspace, controller.signal)
      .then(meta => { if (!controller.signal.aborted) setLoaded({ key, params: (meta?.params as Params) ?? null }) })
      .catch(() => { if (!controller.signal.aborted) setLoaded({ key, params: null }) })
    return () => controller.abort()
  }, [name, workspace, key, provided])
  if (provided !== undefined) return provided
  return loaded?.key === key ? loaded.params : null
}

/** State and handlers behind the action bar, shared by its button groups. */
interface OutputActionProps {
  file: OutputFile
  index: number
  /** Sidecar parameters when the caller already loaded them. */
  params?: Params
  /** The player currently showing this video, if any (frame capture, delete). */
  getVideoElement?: () => HTMLVideoElement | null
  /** Seek position picked for this video, used when no player is mounted. */
  getVideoTime?: () => number
  /** Called just before this output leaves the list (deleted or moved). */
  onBeforeRemove?: () => void
}

function useOutputActions({ file, index, params: providedParams, getVideoElement, getVideoTime, onBeforeRemove }: OutputActionProps) {
  const { t } = useUiTranslation('activity')
  const { t: tStudio } = useUiTranslation('studio')
  const setSelectedOutput = useStore(s => s.setSelectedOutput)
  const setMediaFilter = useStore(s => s.setMediaFilter)
  const loadSettingsFromOutput = useStore(s => s.loadSettingsFromOutput)
  const rerollGeneration = useStore(s => s.rerollGeneration)
  const deleteOutput = useStore(s => s.deleteSelectedOutput)
  const rejoinClipGroup = useStore(s => s.rejoinClipGroup)
  const toggleFavorite = useStore(s => s.toggleFavorite)
  const setStartImage = useStore(s => s.setStartImage)
  const addImageRef = useStore(s => s.addImageRef)
  const setContinueVideo = useStore(s => s.setContinueVideo)
  const setParam = useStore(s => s.setParam)
  const openRetakeDialog = useStore(s => s.openRetakeDialog)
  const generationMode = useStore(s => s.generationMode)
  const workspaces = useStore(s => s.workspaces)
  const activeWorkspace = useStore(s => s.activeWorkspace)
  // Virtual Uploads view: browse-only. Move/favorite/delete resolve
  // against the active OUTPUT workspace server-side, so they can't act
  // on upload files — hide them. Download + send-to-input still work
  // (serve_file falls back to the uploads folder).
  const browsingUploads = useStore(s => s.browsingUploads)
  const outputWorkspace = browsingUploads ? '__uploads__' : activeWorkspace
  const saveRecipeFromOutput = useStore(s => s.saveRecipeFromOutput)
  const nsfwMode = useStore(s => !!s.servicesConfig?.nsfw_mode)
  const params = useOutputParams(file.name, outputWorkspace, providedParams)

  const [confirmDelete, setConfirmDelete] = useState(false)
  const [showSaveRecipe, setShowSaveRecipe] = useState(false)
  const [showExtraInfo, setShowExtraInfo] = useState(false)
  const confirmRef = useRef(false)
  const timeoutRef = useRef<ReturnType<typeof setTimeout>>(undefined)
  const [copied, setCopied] = useState(false)
  const [rejoining, setRejoining] = useState(false)
  const [sentToInput, setSentToInput] = useState(false)
  const [showMoveMenu, setShowMoveMenu] = useState(false)
  const [moving, setMoving] = useState(false)
  const [selectingForMontage, setSelectingForMontage] = useState(false)
  const [montageSelectionError, setMontageSelectionError] = useState('')
  const [settingsError, setSettingsError] = useState('')
  const [settingsBusy, setSettingsBusy] = useState(false)
  const settingsPending = useRef(false)
  const editorReplacementTarget = readVideoEditorReplacementTarget()
  const directorReplacementTarget = readDirectorClipReplacementTarget()

  const prompt = (params?._tts_original_prompt as string) || (params?.prompt as string) || ''
  const multiClipInfo = params?.multi_clip_info as { group_id: string; index: number; total: number } | undefined
  const groupId = multiClipInfo?.group_id
  const clipTotal = multiClipInfo?.total

  const handleOutputSettings = useCallback(async (reroll: boolean) => {
    if (settingsPending.current) return
    settingsPending.current = true
    setSettingsBusy(true)
    setSettingsError('')
    setSelectedOutput(index)
    try {
      const action = reroll ? rerollGeneration : loadSettingsFromOutput
      const restored = await action({ name: file.name, workspace: outputWorkspace })
      if (restored === false) setSettingsError(t('settingsUnavailable'))
    } catch (error) {
      setSettingsError(error instanceof Error ? error.message : t('settingsUnavailable'))
    } finally {
      settingsPending.current = false
      setSettingsBusy(false)
    }
  }, [file.name, outputWorkspace, index, setSelectedOutput, loadSettingsFromOutput, rerollGeneration, t])

  const handleUseAsEditorReplacement = useCallback(() => {
    const target = readVideoEditorReplacementTarget()
    if (!target || file.type !== 'video') return
    writeVideoEditorReplacementResult({
      clipId: target.clipId,
      clipIndex: target.clipIndex,
      outputName: file.name,
      source: getFileUrl(file.name),
      selectedAt: Date.now(),
    })
    setMediaFilter('videoeditor')
  }, [file.name, file.type, setMediaFilter])

  const handleOpenInVideoEditor = useCallback(() => {
    if (file.type !== 'video') return
    writeVideoEditorPendingSource({
      name: file.name,
      url: getFileUrl(file.name, outputWorkspace),
    })
    setMediaFilter('videoeditor')
  }, [file.name, file.type, outputWorkspace, setMediaFilter])

  const handleUseAsDirectorReplacement = useCallback(async () => {
    const target = readDirectorClipReplacementTarget()
    if (!target || file.type !== 'video' || selectingForMontage) return
    setSelectingForMontage(true)
    setMontageSelectionError('')
    try {
      await selectPipelineClipVideo(target.pipelineId, target.clipIndex, file.name)
      writeDirectorClipReplacementResult({
        pipelineId: target.pipelineId,
        clipIndex: target.clipIndex,
        filename: file.name,
        selectedAt: Date.now(),
      })
      setMediaFilter('stories')
    } catch (reason) {
      setMontageSelectionError((reason as Error).message)
      setSelectingForMontage(false)
    }
  }, [file.name, file.type, selectingForMontage, setMediaFilter])

  const handleCopyPrompt = () => {
    if (!prompt) return
    // navigator.clipboard requires secure context; fallback to execCommand
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(prompt).then(() => {
        setCopied(true)
        setTimeout(() => setCopied(false), 1500)
      }).catch(() => {
        // Fallback
        const ta = document.createElement('textarea')
        ta.value = prompt
        ta.style.position = 'fixed'
        ta.style.opacity = '0'
        document.body.appendChild(ta)
        ta.select()
        document.execCommand('copy')
        document.body.removeChild(ta)
        setCopied(true)
        setTimeout(() => setCopied(false), 1500)
      })
    } else {
      const ta = document.createElement('textarea')
      ta.value = prompt
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    }
  }

  const handleDelete = async () => {
    if (!confirmRef.current) {
      confirmRef.current = true
      setConfirmDelete(true)
      clearTimeout(timeoutRef.current)
      timeoutRef.current = setTimeout(() => {
        confirmRef.current = false
        setConfirmDelete(false)
      }, 3000)
      return
    }
    clearTimeout(timeoutRef.current)
    confirmRef.current = false
    setConfirmDelete(false)
    // Release video element src to unlock the file on Windows
    const playing = getVideoElement?.()
    if (playing) {
      playing.pause()
      playing.removeAttribute('src')
      playing.load()
    }
    onBeforeRemove?.()
    setSelectedOutput(index)
    // Small delay to let the browser release the file handle
    setTimeout(() => deleteOutput(), 200)
  }

  const handleRejoin = async () => {
    if (!groupId) return
    setRejoining(true)
    try {
      await rejoinClipGroup(groupId)
    } finally {
      setRejoining(false)
    }
  }

  const handleMove = async (targetWs: string) => {
    setMoving(true)
    setShowMoveMenu(false)
    try {
      await moveOutput(file.name, targetWs)
      onBeforeRemove?.()
      // Immediately remove from local state (source may still exist during deferred cleanup)
      const store = useStore.getState()
      const filtered = store.outputs.filter(o => o.name !== file.name)
      useStore.setState({ outputs: filtered, selectedOutput: Math.min(store.selectedOutput, Math.max(0, filtered.length - 1)) })
    } catch (e) {
      console.error('Move failed:', e)
    } finally {
      setMoving(false)
    }
  }

  const handleSendToInput = async () => {
    if (file.type !== 'image') return
    try {
      if (generationMode === 'image') {
        if (!await addOutputImageReference(file.name, outputWorkspace)) return
      } else {
        const change = beginImageSettingsChange(useStore.getState)
        const res = await fetch(outputImageUrl(file.name, outputWorkspace), { signal: change.signal })
        if (!res.ok) throw new Error(`${file.name}: HTTP ${res.status}`)
        const blob = await res.blob()
        if (!change.current()) return
        const imageFile = new File([blob], file.name, { type: blob.type || 'image/png' })
        setStartImage(imageFile)
      }
      setSentToInput(true)
      setTimeout(() => setSentToInput(false), 2000)
    } catch (e) {
      setSettingsError(e instanceof Error ? e.message : String(e))
    }
  }

  const handleEditImage = async () => {
    if (settingsPending.current) return
    settingsPending.current = true
    setSettingsBusy(true)
    setSettingsError('')
    try {
      if (!await editOutputImage(file.name, outputWorkspace)) setSettingsError(t('settingsUnavailable'))
    } catch (error) { setSettingsError(error instanceof Error ? error.message : String(error)) }
    finally { settingsPending.current = false; setSettingsBusy(false) }
  }

  // Capture the frame the video preview is currently SHOWING (canvas grab
  // of the <video> element at its currentTime — same-origin, so no taint)
  // and append it to the Reference tiles. Pairs with SCAIL-2: scrub to the
  // pose you want, one click, it's your character reference.
  const handleSendFrameToRefs = async () => {
    if (file.type !== 'video') return
    let temporaryVideo: HTMLVideoElement | null = null
    const videoTime = getVideoTime?.() ?? 0
    try {
      let video = getVideoElement?.() ?? null
      if (!video || video.videoWidth === 0) {
        // The dialog releases its player on close; recover its selected frame.
        video = document.createElement('video')
        temporaryVideo = video
        video.src = getFileUrl(file.name, outputWorkspace)
        video.muted = true
        await new Promise<void>((resolve, reject) => {
          video!.onloadeddata = () => resolve()
          video!.onerror = () => reject(new Error('video load failed'))
        })
        if (videoTime > 0 && Number.isFinite(video.duration)) {
          await new Promise<void>((resolve, reject) => {
            video!.onseeked = () => resolve()
            video!.onerror = () => reject(new Error('video seek failed'))
            video!.currentTime = Math.min(videoTime, Math.max(0, video!.duration - 0.001))
          })
        }
      }
      const canvas = document.createElement('canvas')
      canvas.width = video.videoWidth
      canvas.height = video.videoHeight
      const ctx = canvas.getContext('2d')
      if (!ctx) throw new Error('canvas unavailable')
      ctx.drawImage(video, 0, 0)
      const blob: Blob = await new Promise((resolve, reject) =>
        canvas.toBlob(b => (b ? resolve(b) : reject(new Error('frame capture failed'))), 'image/png')
      )
      const stem = file.name.replace(/\.[^.]+$/, '')
      const frameFile = new File([blob], `${stem}_t${video.currentTime.toFixed(2)}s.png`, { type: 'image/png' })
      addImageRef(frameFile)
      setSentToInput(true)
      setTimeout(() => setSentToInput(false), 2000)
    } catch (e) {
      console.error('Failed to capture video frame:', e)
    } finally {
      if (temporaryVideo) {
        temporaryVideo.pause()
        temporaryVideo.removeAttribute('src')
        temporaryVideo.load()
      }
    }
  }

  const handleContinueFrom = async () => {
    if (file.type !== 'video') return
    try {
      const res = await fetch(getFileUrl(file.name))
      const blob = await res.blob()
      const videoFile = new File([blob], file.name, { type: blob.type || 'video/mp4' })
      const url = URL.createObjectURL(videoFile)
      const video = document.createElement('video')
      video.src = url
      video.onloadedmetadata = async () => {
        const duration = video.duration && isFinite(video.duration) ? video.duration : 0
        const uploaded = await uploadImage(videoFile)
        // Switch sub-mode FIRST: the switch stashes the current sub-mode's
        // working set and opens Extend's own slate. Setting the source
        // after keeps it from being wiped by that swap.
        setParam('image_mode', 3)
        setContinueVideo(videoFile, uploaded.path, url, duration)
      }
    } catch (e) {
      console.error('Failed to load video for continuation:', e)
    }
  }


  return { activeWorkspace, addImageRef, browsingUploads, clipTotal, confirmDelete, confirmRef, copied, deleteOutput, directorReplacementTarget, editorReplacementTarget, file, generationMode, groupId, handleContinueFrom, handleCopyPrompt, handleDelete, handleEditImage, handleMove, handleOpenInVideoEditor, handleOutputSettings, handleRejoin, handleSendFrameToRefs, handleSendToInput, handleUseAsDirectorReplacement, handleUseAsEditorReplacement, index, loadSettingsFromOutput, montageSelectionError, moving, multiClipInfo, nsfwMode, openRetakeDialog, outputWorkspace, params, prompt, rejoinClipGroup, rejoining, rerollGeneration, saveRecipeFromOutput, selectingForMontage, sentToInput, setConfirmDelete, setContinueVideo, setCopied, setMediaFilter, setMontageSelectionError, setMoving, setParam, setRejoining, setSelectedOutput, setSelectingForMontage, setSentToInput, setSettingsBusy, setSettingsError, setShowExtraInfo, setShowMoveMenu, setShowSaveRecipe, setStartImage, settingsBusy, settingsError, settingsPending, showExtraInfo, showMoveMenu, showSaveRecipe, t, tStudio, timeoutRef, toggleFavorite, workspaces }
}

type OutputActions = ReturnType<typeof useOutputActions>

function HandoffActions({ a }: { a: OutputActions }) {
  const { directorReplacementTarget, editorReplacementTarget, file, handleOpenInVideoEditor, handleUseAsDirectorReplacement, handleUseAsEditorReplacement, montageSelectionError, selectingForMontage, t } = a
  return (
    <>
        {file.type === 'video' && directorReplacementTarget && (
          <button
            onClick={() => void handleUseAsDirectorReplacement()}
            disabled={selectingForMontage}
            className="flex items-center gap-1 rounded-lg border border-violet-500/40 bg-violet-500/10 px-2 py-1.5 text-[10px] font-medium text-violet-200 transition-colors hover:bg-violet-500/20 disabled:opacity-50"
            title={t('montage.useInAssembly', { n: directorReplacementTarget.clipIndex + 1 })}
          >
            {selectingForMontage ? <Loader2 size={13} className="animate-spin" /> : <FolderInput size={13} />}
            {t('montage.useInAssembly', { n: directorReplacementTarget.clipIndex + 1 })}
          </button>
        )}
        {file.type === 'video' && editorReplacementTarget && (
          <button
            onClick={handleUseAsEditorReplacement}
            className="flex items-center gap-1 rounded-lg border border-emerald-500/35 bg-emerald-500/10 px-2 py-1.5 text-[10px] font-medium text-emerald-300 transition-colors hover:bg-emerald-500/20 hover:text-emerald-200"
            title={t('montage.useInPosition', { n: editorReplacementTarget.clipIndex + 1 })}
          >
            <FolderInput size={13} />
            {t('montage.useInPosition', { n: editorReplacementTarget.clipIndex + 1 })}
          </button>
        )}
        {file.type === 'video' && (
          <button
            onClick={handleOpenInVideoEditor}
            className="p-1.5 rounded-lg hover:bg-bg-hover text-text-secondary hover:text-accent-blue transition-colors"
            title={t('editInVideoEditor')}
            aria-label={t('editInVideoEditor')}
          >
            <Film size={13} />
          </button>
        )}
        {montageSelectionError && <span className="max-w-40 truncate text-[9px] text-red-400" title={montageSelectionError}>{montageSelectionError}</span>}
    </>
  )
}

function GenerationActions({ a }: { a: OutputActions }) {
  const { clipTotal, copied, file, groupId, handleContinueFrom, handleCopyPrompt, handleOutputSettings, handleRejoin, openRetakeDialog, params, rejoining, setShowSaveRecipe, settingsBusy, settingsError, tStudio } = a
  return (
    <>
        {params && (
          <>
            <button
              onClick={(e) => { e.stopPropagation(); setShowSaveRecipe(true) }}
              className="p-1.5 rounded-lg hover:bg-bg-hover text-text-secondary hover:text-accent-blue transition-colors"
              title="Save as Recipe — reuse this look with one click"
            >
              <BookMarked size={13} />
            </button>
            <button
              onClick={event => { event.stopPropagation(); void handleOutputSettings(false) }}
              disabled={settingsBusy}
              className="p-1.5 rounded-lg hover:bg-bg-hover text-text-secondary hover:text-text-primary transition-colors"
              title={tStudio('imageActions.loadSettings')}
            >
              <SlidersHorizontal size={13} />
            </button>
            <button
              onClick={event => { event.stopPropagation(); void handleOutputSettings(true) }}
              disabled={settingsBusy}
              className="p-1.5 rounded-lg hover:bg-bg-hover text-text-secondary hover:text-text-primary transition-colors"
              title="Re-generate with same settings"
            >
              <RefreshCw size={13} />
            </button>
            {settingsError && <span role="alert" className="text-xs text-red-400">{settingsError}</span>}
            {file.type === 'video' && (
              <>
                <button
                  onClick={() => openRetakeDialog(file.name)}
                  className="p-1.5 rounded-lg hover:bg-bg-hover text-text-secondary hover:text-indicator-warning transition-colors"
                  title="Retake — regenerate a time region"
                >
                  <Scissors size={13} />
                </button>
                <button
                  onClick={handleContinueFrom}
                  className="p-1.5 rounded-lg hover:bg-bg-hover text-text-secondary hover:text-accent-blue transition-colors"
                  title="Extend this video with new content"
                >
                  <FastForward size={13} />
                </button>
              </>
            )}
            {groupId && (
              <button
                onClick={handleRejoin}
                disabled={rejoining}
                className="p-1.5 rounded-lg hover:bg-bg-hover text-accent-blue hover:text-accent-blue-hover transition-colors disabled:opacity-50"
                title={`Rejoin all ${clipTotal} clips in this group`}
              >
                {rejoining ? <Loader2 size={13} className="animate-spin" /> : <Combine size={13} />}
              </button>
            )}
            <button
              onClick={handleCopyPrompt}
              className="p-1.5 rounded-lg hover:bg-bg-hover text-text-secondary hover:text-text-primary transition-colors"
              title="Copy prompt"
            >
              {copied ? <Check size={13} className="text-accent-green" /> : <Copy size={13} />}
            </button>
          </>
        )}
    </>
  )
}

function InputActions({ a }: { a: OutputActions }) {
  const { file, generationMode, handleEditImage, handleSendFrameToRefs, handleSendToInput, sentToInput, setShowExtraInfo, settingsBusy, t, tStudio } = a
  return (
    <>
        {file.type === 'image' && (
          <button onClick={event => { event.stopPropagation(); void handleEditImage() }} disabled={settingsBusy}
            className="p-1.5 rounded-lg hover:bg-bg-hover text-text-secondary hover:text-accent-blue disabled:opacity-40"
            title={tStudio('imageActions.edit')}><Pencil size={13} /></button>
        )}
        {file.type === 'image' && (
          <button
            onClick={(e) => { e.stopPropagation(); handleSendToInput() }}
            className={`p-1.5 rounded-lg transition-colors ${
              sentToInput
                ? 'text-accent-green'
                : 'hover:bg-bg-hover text-text-secondary hover:text-accent-blue'
            }`}
            title={generationMode === 'image' ? tStudio('imageActions.reference') : 'Use as start frame'}
          >
            {sentToInput ? <Check size={13} /> : <ArrowLeftToLine size={13} />}
          </button>
        )}
        {file.type === 'video' && (
          <>
            <button
              onClick={(e) => { e.stopPropagation(); handleSendFrameToRefs() }}
              className={`p-1.5 rounded-lg transition-colors ${
                sentToInput
                  ? 'text-accent-green'
                  : 'hover:bg-bg-hover text-text-secondary hover:text-accent-blue'
              }`}
              title="Use current frame as reference image"
            >
              {sentToInput ? <Check size={13} /> : <ArrowLeftToLine size={13} />}
            </button>
            <button
              onClick={(e) => { e.stopPropagation(); setShowExtraInfo(true) }}
              className="flex items-center gap-1 rounded-lg px-2 py-1.5 text-[10px] text-text-secondary transition-colors hover:bg-bg-hover hover:text-accent-blue"
              title="Generate descriptions and social copy from saved prompts"
            >
              <BadgeInfo size={13} />
              {t('extraInfo')}
            </button>
          </>
        )}
    </>
  )
}

function LibraryActions({ a }: { a: OutputActions }) {
  const { activeWorkspace, browsingUploads, confirmDelete, file, handleDelete, handleMove, moving, setShowMoveMenu, showMoveMenu, toggleFavorite, workspaces } = a
  return (
    <>
        <button
          onClick={(e) => {
            e.stopPropagation()
            const link = document.createElement('a')
            link.href = getFileUrl(file.name)
            link.download = file.name
            document.body.appendChild(link)
            link.click()
            document.body.removeChild(link)
          }}
          className="p-1.5 rounded-lg hover:bg-bg-hover text-text-secondary hover:text-text-primary transition-colors"
          title="Download"
        >
          <Download size={13} />
        </button>
        {/* Move to workspace */}
        {!browsingUploads && (
        <div className="relative shrink-0">
          <button
            onClick={(e) => { e.stopPropagation(); setShowMoveMenu(!showMoveMenu) }}
            disabled={moving}
            className={`flex min-h-11 min-w-11 items-center justify-center p-1.5 rounded-lg transition-colors ${
              moving ? 'text-accent-blue animate-pulse' : 'hover:bg-bg-hover text-text-secondary hover:text-text-primary'
            }`}
            title="Move to workspace"
          >
            <FolderInput size={13} />
          </button>
          {showMoveMenu && <MediaMoveDialog workspaces={workspaces.filter(ws => ws.name !== activeWorkspace).map(ws => ws.name)}
            onClose={() => setShowMoveMenu(false)} onMove={name => void handleMove(name)} />}

        </div>
        )}
        {!browsingUploads && (
        <button
          onClick={(e) => { e.stopPropagation(); toggleFavorite(file.name) }}
          className={`p-1.5 rounded-lg transition-colors ${
            file.favorite
              ? 'text-red-400 hover:text-red-300'
              : 'hover:bg-bg-hover text-text-secondary hover:text-red-400'
          }`}
          title={file.favorite ? 'Remove from favorites' : 'Add to favorites'}
        >
          <Heart size={13} fill={file.favorite ? 'currentColor' : 'none'} />
        </button>
        )}
        {!browsingUploads && (
        <button
          onClick={handleDelete}
          className={`p-1.5 rounded-lg transition-colors flex items-center gap-1 ${
            confirmDelete
              ? 'bg-red-500/20 text-red-400 hover:bg-red-500/30'
              : 'hover:bg-bg-hover text-text-secondary hover:text-red-400'
          }`}
          title={confirmDelete ? 'Click again to confirm delete' : 'Delete output'}
        >
          <Trash2 size={13} />
          {confirmDelete && <span className="text-[11px] font-medium">Delete?</span>}
        </button>
        )}
    </>
  )
}

/** Every action an output offers, shared by the one-up card and the details
 *  dialog so all three gallery views expose the same options. */
export function OutputActionBar({ variant = 'card', ...props }: OutputActionProps & { variant?: 'card' | 'dialog' }) {
  const a = useOutputActions(props)
  const { file, nsfwMode, saveRecipeFromOutput, setShowExtraInfo, setShowSaveRecipe, showExtraInfo, showSaveRecipe } = a
  return (
    <>
    <div data-testid="output-actions" className={variant === 'card' ? CARD_BAR : DIALOG_BAR} onClick={e => e.stopPropagation()}>
      <HandoffActions a={a} />
      <GenerationActions a={a} />
      <InputActions a={a} />
      <LibraryActions a={a} />
    </div>
    {showSaveRecipe && (
      <SaveRecipeDialog
        defaultNsfw={nsfwMode}
        onCancel={() => setShowSaveRecipe(false)}
        onSave={async (name, description, nsfw) => {
          await saveRecipeFromOutput(file.name, name, description, nsfw)
          setShowSaveRecipe(false)
        }}
      />
    )}
    {showExtraInfo && (
      <VideoExtraInfoDialog
        name={file.name}
        onClose={() => setShowExtraInfo(false)}
      />
    )}
    </>
  )
}
