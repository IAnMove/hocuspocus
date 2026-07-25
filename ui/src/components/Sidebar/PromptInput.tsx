import { useState, useRef, useEffect } from 'react'
import { Sparkles, Loader2, ChevronUp, Brain, PenLine, History, Save, Trash2 } from 'lucide-react'
import { useStore } from '../../stores/useStore'
import {
  getPromptHistory, PROMPT_HISTORY_EVENT, rememberPrompt, removePromptHistoryEntry,
  type PromptHistoryEntry,
} from '../../lib/promptHistory'

const placeholders: Record<string, string> = {
  image: 'Describe your image...',
  video: 'Describe your video...',
  audio: 'Enter text to speak or describe audio...',
  avatar: 'Describe your avatar animation...',
}

function useEnhanceStatus(isEnhancing: boolean) {
  const [status, setStatus] = useState<{ phase: 'loading' | 'thinking' | 'writing' | 'idle'; chars: number }>({ phase: 'idle', chars: 0 })

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      setStatus(isEnhancing
        ? { phase: 'loading', chars: 0 }
        : { phase: 'idle', chars: 0 })
    })
    if (!isEnhancing) {
      return () => window.cancelAnimationFrame(frame)
    }
    let active = true
    const poll = async () => {
      let streamStarted = false
      while (active) {
        try {
          // Check if LLM is still loading
          if (!streamStarted) {
            const llmRes = await fetch('/api/v1/llm/status')
            if (llmRes.ok && active) {
              const llmData = await llmRes.json()
              if (!llmData.loaded) {
                setStatus({ phase: 'loading', chars: 0 })
                await new Promise(r => setTimeout(r, 800))
                continue
              }
            }
          }
          const res = await fetch('/api/v1/llm/stream-status')
          if (res.ok && active) {
            const data = await res.json()
            const text = (data.text || '') as string
            if (text.length > 0) streamStarted = true
            const hasThinking = text.includes('<think>') || text.includes('<thinking>')
            const thinkingClosed = text.includes('</think>') || text.includes('</thinking>')
            if (hasThinking && !thinkingClosed) {
              setStatus({ phase: 'thinking', chars: text.length })
            } else if (text.length > 0) {
              setStatus({ phase: 'writing', chars: text.length })
            } else if (!streamStarted) {
              setStatus({ phase: 'loading', chars: 0 })
            }
            if (data.done) break
          }
        } catch { /* ignore */ }
        await new Promise(r => setTimeout(r, 800))
      }
    }
    poll()
    return () => {
      active = false
      window.cancelAnimationFrame(frame)
    }
  }, [isEnhancing])

  return status
}

export function PromptInput() {
  const prompt = useStore(s => s.params.prompt)
  const setParam = useStore(s => s.setParam)
  const generationMode = useStore(s => s.generationMode)
  const enhancePrompt = useStore(s => s.enhancePrompt)
  const isEnhancing = useStore(s => s.isEnhancing)
  const durationSeconds = useStore(s => s.durationSeconds)
  const slidingWindowSeconds = useStore(s => s.slidingWindowSeconds)
  const slidingWindowOverlap = useStore(s => s.slidingWindowOverlap)
  const modelOptions = useStore(s => s.modelOptions)
  const imageMode = useStore(s => s.params.image_mode)
  const negativePrompt = useStore(s => s.params.negative_prompt)
  const activeWorkspace = useStore(s => s.activeWorkspace)
  const modelType = useStore(s => s.params.model_type)
  const [ttsMenuOpen, setTtsMenuOpen] = useState(false)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [promptHistory, setPromptHistory] = useState<PromptHistoryEntry[]>([])
  const menuRef = useRef<HTMLDivElement>(null)
  const historyRef = useRef<HTMLDivElement>(null)

  const isAudioOnly = modelOptions?.audio_only
  const voiceCount = useStore(s => s.ttsVoiceCount)
  const isMultiVoice = voiceCount >= 2
  // Does the active TTS model support multi-speaker output? Scenema, Kugel,
  // Qwen3-TTS, Index-TTS2 all do (max_voice_count >= 2 in their handlers).
  // Single-speaker-only engines leave it undefined; default 6 is the legacy
  // "any multi-speaker engine" assumption. Falling back to >1 keeps both
  // dialogue and monologue enhance available unless a model declares itself
  // single-speaker.
  const maxVoiceCount = ((modelOptions as { max_voice_count?: number } | null)?.max_voice_count) ?? 6
  const supportsDialogue = maxVoiceCount > 1
  // Main Sparkles button default: dialogue when the user has actually added
  // 2+ voice slots, monologue otherwise. The dropdown lets the user override
  // either way regardless of voice slot count.
  const defaultMode: 'dialogue' | 'monologue' = isMultiVoice ? 'dialogue' : 'monologue'
  const enhanceStatus = useEnhanceStatus(isEnhancing)
  const fps = modelOptions?.fps ?? 16
  const swDefaults = (modelOptions as Record<string, unknown> | null)?.sliding_window_defaults as Record<string, number> | undefined
  const discardFrames = swDefaults?.discard_last_frames ?? 0
  const overlapSec = slidingWindowOverlap / fps
  const discardSec = discardFrames / fps
  const stride = slidingWindowSeconds - discardSec - overlapSec
  const windowCount = stride > 0 && durationSeconds > slidingWindowSeconds
    ? 1 + Math.ceil((durationSeconds - slidingWindowSeconds + discardSec) / stride)
    : 1
  const usesWindows = generationMode === 'video' && windowCount > 1 && imageMode !== 2

  // Close TTS menu on outside click
  useEffect(() => {
    if (!ttsMenuOpen) return
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setTtsMenuOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [ttsMenuOpen])

  useEffect(() => {
    const refresh = () => setPromptHistory(getPromptHistory(activeWorkspace))
    refresh()
    window.addEventListener(PROMPT_HISTORY_EVENT, refresh)
    return () => window.removeEventListener(PROMPT_HISTORY_EVENT, refresh)
  }, [activeWorkspace])

  useEffect(() => {
    if (!historyOpen) return
    const handler = (event: MouseEvent) => {
      if (historyRef.current && !historyRef.current.contains(event.target as Node)) {
        setHistoryOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [historyOpen])

  const saveCurrentPrompt = () => {
    rememberPrompt({
      prompt,
      negativePrompt,
      mode: generationMode,
      model: modelType,
      workspace: activeWorkspace,
      source: 'manual',
    })
  }

  const restorePrompt = (entry: PromptHistoryEntry) => {
    setParam('prompt', entry.prompt)
    setParam('negative_prompt', entry.negativePrompt)
    setHistoryOpen(false)
  }

  // grow shrink-0: fill spare vertical space when the sidebar is roomy, but
  // never shrink below the textarea's min-height. Dropping the old
  // `flex-1 min-h-0` stops the wrapper from collapsing under the textarea
  // (which made it overflow and overlap the section below).
  return (
    <div className="relative grow shrink-0 flex flex-col">
      <div
        ref={historyRef}
        className={`absolute right-2 z-40 ${isEnhancing ? 'top-8' : 'top-2'}`}
      >
        <button
          type="button"
          onClick={() => setHistoryOpen(value => !value)}
          className={`rounded-md p-1.5 transition-colors ${
            historyOpen
              ? 'bg-accent-blue/15 text-accent-blue'
              : 'bg-bg-secondary/80 text-text-muted hover:bg-bg-hover hover:text-text-primary'
          }`}
          title="Prompt history"
          aria-label="Open prompt history"
        >
          <History size={14} />
        </button>
        {historyOpen && (
          <div className="absolute right-0 top-full mt-1 w-[min(330px,calc(100vw-32px))] overflow-hidden rounded-lg border border-border bg-bg-secondary shadow-2xl">
            <div className="flex items-center justify-between gap-2 border-b border-border px-3 py-2">
              <div>
                <div className="text-xs font-semibold text-text-primary">Prompt history</div>
                <div className="text-[9px] text-text-muted">{activeWorkspace} · newest first</div>
              </div>
              <button
                type="button"
                disabled={!prompt.trim()}
                onClick={saveCurrentPrompt}
                className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-[10px] text-text-secondary hover:bg-bg-hover disabled:opacity-40"
              >
                <Save size={11} /> Save current
              </button>
            </div>
            <div className="max-h-72 overflow-y-auto">
              {promptHistory.length === 0 ? (
                <div className="px-3 py-6 text-center text-[11px] text-text-muted">
                  Submitted and manually saved prompts will appear here.
                </div>
              ) : promptHistory.map(entry => (
                <div key={entry.id} className="group border-b border-border/70 p-2.5 last:border-b-0 hover:bg-bg-hover">
                  <div className="flex items-start gap-2">
                    <button
                      type="button"
                      onClick={() => restorePrompt(entry)}
                      className="min-w-0 flex-1 text-left"
                      title="Restore this prompt"
                    >
                      <span className="line-clamp-3 whitespace-pre-wrap text-[11px] leading-relaxed text-text-primary">
                        {entry.prompt}
                      </span>
                      <span className="mt-1 block truncate text-[9px] text-text-muted">
                        {entry.source === 'manual' ? 'Saved' : 'Generated'}
                        {entry.mode ? ` · ${entry.mode}` : ''}
                        {entry.model ? ` · ${entry.model}` : ''}
                        {' · '}
                        {new Date(entry.createdAt).toLocaleString()}
                      </span>
                    </button>
                    <button
                      type="button"
                      onClick={() => removePromptHistoryEntry(activeWorkspace, entry.id)}
                      className="rounded p-1 text-text-muted opacity-40 hover:bg-red-500/10 hover:text-red-400 group-hover:opacity-100"
                      title="Remove from history"
                      aria-label="Remove prompt from history"
                    >
                      <Trash2 size={11} />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
      {/* Enhance status indicator */}
      {isEnhancing && enhanceStatus.phase !== 'idle' && (
        <div className="flex items-center gap-1.5 px-2 py-1 text-[10px] text-text-muted bg-bg-tertiary/80 rounded-t-lg border border-b-0 border-border">
          {enhanceStatus.phase === 'loading' ? (
            <>
              <Loader2 size={10} className="text-text-muted animate-spin" />
              <span>Loading LLM...</span>
            </>
          ) : enhanceStatus.phase === 'thinking' ? (
            <>
              <Brain size={10} className="text-purple-400 animate-pulse" />
              <span>Thinking...</span>
            </>
          ) : (
            <>
              <PenLine size={10} className="text-accent-blue animate-pulse" />
              <span>Writing...</span>
            </>
          )}
        </div>
      )}
      <textarea
        value={prompt}
        onChange={e => setParam('prompt', e.target.value)}
        placeholder={usesWindows
          ? `Line 1 = window 1, line 2 = window 2... (${windowCount} windows)`
          : (placeholders[generationMode] || 'Describe your content...')}
        className="w-full flex-1 bg-bg-tertiary border border-border rounded-lg px-3 py-2 pr-10 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent-blue transition-colors"
        style={{ resize: 'none', minHeight: 112 }}
      />
      {prompt.trim() && (
        isAudioOnly ? (
          /* TTS: mode-aware split button. Main button uses default mode based
             on voice-slot count; dropdown exposes both Speech and Dialogue
             explicitly so the user can override regardless of voice count.
             Previously the dropdown labels switched with isMultiVoice, leaving
             no way to enhance into dialogue format without first adding voice
             slots — bad UX trap especially with audio_mode_from_voice_count
             models like Scenema where the user may want a generated-voice
             dialogue script as a starting point. */
          <div ref={menuRef} className="absolute right-2 bottom-2">
            <div className="flex items-center">
              <button
                onClick={() => enhancePrompt(defaultMode)}
                disabled={isEnhancing}
                title={isMultiVoice
                  ? `Write ${voiceCount}-person dialogue (use dropdown to switch to speech)`
                  : 'Write a speech (use dropdown to switch to dialogue)'}
                className="p-1.5 rounded-l-md text-text-muted hover:text-accent-blue hover:bg-bg-hover transition-colors disabled:opacity-50"
              >
                {isEnhancing ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
              </button>
              <button
                onClick={() => setTtsMenuOpen(!ttsMenuOpen)}
                disabled={isEnhancing}
                className="p-1.5 rounded-r-md text-text-muted hover:text-accent-blue hover:bg-bg-hover transition-colors disabled:opacity-50 border-l border-border"
              >
                <ChevronUp size={10} />
              </button>
            </div>
            {ttsMenuOpen && (
              <div className="absolute bottom-full right-0 mb-1 bg-bg-secondary border border-border rounded-lg shadow-lg overflow-hidden min-w-[220px] z-50">
                <button
                  onClick={() => { setTtsMenuOpen(false); enhancePrompt('monologue') }}
                  className="w-full text-left px-3 py-2 text-[11px] text-text-secondary hover:bg-bg-hover transition-colors"
                >
                  Write Speech
                  <span className="block text-[9px] text-text-muted">Single speaker, with thinking</span>
                </button>
                <button
                  onClick={() => { setTtsMenuOpen(false); enhancePrompt('monologue_fast') }}
                  className="w-full text-left px-3 py-2 text-[11px] text-text-secondary hover:bg-bg-hover transition-colors border-t border-border"
                >
                  Write Speech
                  <span className="block text-[9px] text-text-muted">Single speaker, faster</span>
                </button>
                {supportsDialogue && (
                  <>
                    <button
                      onClick={() => { setTtsMenuOpen(false); enhancePrompt('dialogue') }}
                      className="w-full text-left px-3 py-2 text-[11px] text-text-secondary hover:bg-bg-hover transition-colors border-t border-border"
                    >
                      {voiceCount >= 2 ? `Write ${voiceCount}-Person Dialogue` : 'Write Dialogue (2 speakers)'}
                      <span className="block text-[9px] text-text-muted">With thinking — more creative</span>
                    </button>
                    <button
                      onClick={() => { setTtsMenuOpen(false); enhancePrompt('dialogue_fast') }}
                      className="w-full text-left px-3 py-2 text-[11px] text-text-secondary hover:bg-bg-hover transition-colors border-t border-border"
                    >
                      {voiceCount >= 2 ? `Write ${voiceCount}-Person Dialogue` : 'Write Dialogue (2 speakers)'}
                      <span className="block text-[9px] text-text-muted">No thinking — faster</span>
                    </button>
                  </>
                )}
              </div>
            )}
          </div>
        ) : (
          <button
            onClick={() => enhancePrompt()}
            disabled={isEnhancing}
            title="Enhance prompt with AI"
            className="absolute right-2 bottom-2 p-1.5 rounded-md text-text-muted hover:text-accent-blue hover:bg-bg-hover transition-colors disabled:opacity-50"
          >
            {isEnhancing ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <Sparkles size={14} />
            )}
          </button>
        )
      )}
    </div>
  )
}
