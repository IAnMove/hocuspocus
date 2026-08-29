import { useEffect, useMemo, useRef, useState, type CSSProperties, type FormEvent, type KeyboardEvent as ReactKeyboardEvent } from 'react'
import { ArrowUp, Loader2, Sparkles, Trash2, X } from 'lucide-react'
import { generateLlmText, type CanonicalTask } from '../../api/client'
import { buildAgentTurnPrompt, HOCUSPOCUS_AGENT_SYSTEM_PROMPT, type AgentConversationEntry } from './agentKnowledge'
import {
  buildAgentAppSnapshot,
  executeAgentActions,
  HOCUSPOCUS_AGENT_RESPONSE_SCHEMA,
  parseAgentTurn,
  reconcileAgentTurnWithRequest,
  type AgentActionResult,
} from './agentActions'
import { AgentMarkdown } from './AgentMarkdown'

export type AgentVisualState = 'idle' | 'listening' | 'thinking' | 'acting' | 'success' | 'error'

interface AgentMessage extends AgentConversationEntry {
  id: string
  createdAt: number
}

interface AgentAssistantPanelProps {
  workspace: string
  tasks: CanonicalTask[]
  onClose: () => void
}

interface AgentAvatarProps {
  state?: AgentVisualState
  size?: number
}

const ACTIVE = new Set(['created', 'queued', 'waiting_resource', 'running'])
const STORAGE_PREFIX = 'hocuspocus-agent-chat-v2:'

const newId = () => globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`

const welcomeMessage = (): AgentMessage => ({
  id: newId(),
  role: 'assistant',
  text: 'Saludos, creador. Soy el mago de HocusPocus: puedo consultar la cola, explicarte el estudio, llevarte a la sección adecuada y preparar o lanzar un vídeo cuando me lo pidas. Dime qué quieres conjurar. 🪄',
  createdAt: Date.now(),
})

function formatActionResults(results: AgentActionResult[]): string {
  if (!results.length) return ''
  return results.map(result => `${result.ok ? '✦' : '⚠'} ${result.message}`).join('\n')
}

function readMessages(workspace: string): AgentMessage[] {
  try {
    const raw = window.localStorage.getItem(`${STORAGE_PREFIX}${workspace}`)
    const parsed = raw ? JSON.parse(raw) : []
    if (!Array.isArray(parsed)) return [welcomeMessage()]
    const messages = parsed.filter((message): message is AgentMessage => (
      message && typeof message.id === 'string'
      && (message.role === 'user' || message.role === 'assistant')
      && typeof message.text === 'string'
      && typeof message.createdAt === 'number'
    )).slice(-40)
    return messages.length ? messages : [welcomeMessage()]
  } catch {
    return [welcomeMessage()]
  }
}

function writeMessages(workspace: string, messages: AgentMessage[]): void {
  try {
    window.localStorage.setItem(`${STORAGE_PREFIX}${workspace}`, JSON.stringify(messages.slice(-40)))
  } catch {
    // The current conversation remains usable if storage is unavailable.
  }
}

export function AgentAvatar({ state = 'idle', size = 32 }: AgentAvatarProps) {
  return (
    <span
      className="hp-agent-avatar"
      data-state={state}
      style={{ '--hp-agent-size': `${size}px` } as CSSProperties}
      aria-hidden="true"
    >
      <span className="hp-agent-halo" />
      <img src="/hocuspocus-icon.png" alt="" draggable={false} />
      <span className="hp-agent-mote hp-agent-mote-a" />
      <span className="hp-agent-mote hp-agent-mote-b" />
      <span className="hp-agent-mote hp-agent-mote-c" />
    </span>
  )
}

export function AgentAssistantPanel({ workspace, tasks, onClose }: AgentAssistantPanelProps) {
  const [messages, setMessages] = useState<AgentMessage[]>(() => readMessages(workspace))
  const [draft, setDraft] = useState('')
  const [state, setState] = useState<AgentVisualState>('idle')
  const [busy, setBusy] = useState(false)
  const [busyMessage, setBusyMessage] = useState('Consultando el grimorio de HocusPocus…')
  const endRef = useRef<HTMLDivElement>(null)
  const mountedRef = useRef(true)
  const activeCount = useMemo(() => tasks.filter(task => ACTIVE.has(task.status) && !task.parent_id).length, [tasks])
  const latestTask = useMemo(() => [...tasks].sort((left, right) => right.updated_at - left.updated_at)[0], [tasks])

  useEffect(() => {
    mountedRef.current = true
    return () => { mountedRef.current = false }
  }, [])

  useEffect(() => {
    writeMessages(workspace, messages)
    endRef.current?.scrollIntoView({ block: 'end' })
  }, [messages, workspace])

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [onClose])

  const clearConversation = () => {
    const next = [welcomeMessage()]
    setMessages(next)
    setState('idle')
  }

  const ask = async (text: string) => {
    const question = text.trim()
    if (!question || busy) return
    const userMessage: AgentMessage = { id: newId(), role: 'user', text: question, createdAt: Date.now() }
    const nextMessages = [...messages, userMessage].slice(-40)
    setMessages(nextMessages)
    setDraft('')
    setBusy(true)
    setBusyMessage('Consultando el grimorio de HocusPocus…')
    setState('thinking')
    try {
      const answer = await generateLlmText({
        system_prompt: HOCUSPOCUS_AGENT_SYSTEM_PROMPT,
        prompt: buildAgentTurnPrompt(workspace, nextMessages, tasks, buildAgentAppSnapshot()),
        max_new_tokens: 3_200,
        temperature: .1,
        json_schema: HOCUSPOCUS_AGENT_RESPONSE_SCHEMA,
      })
      if (!mountedRef.current) return
      const turn = reconcileAgentTurnWithRequest(question, parseAgentTurn(answer))
      let results: AgentActionResult[] = []
      if (turn.actions.length) {
        setState('acting')
        results = await executeAgentActions(turn.actions, message => {
          if (mountedRef.current) setBusyMessage(message)
        })
      }
      if (!mountedRef.current) return
      const actionReport = formatActionResults(results)
      const assistantMessage: AgentMessage = {
        id: newId(),
        role: 'assistant',
        text: [turn.reply || 'Mi bola de cristal no ha devuelto una respuesta utilizable.', actionReport]
          .filter(Boolean)
          .join('\n\n'),
        createdAt: Date.now(),
      }
      setMessages(current => [...current, assistantMessage].slice(-40))
      setState(results.some(result => !result.ok) ? 'error' : 'success')
    } catch (error) {
      if (!mountedRef.current) return
      const message = error instanceof Error ? error.message : String(error)
      const assistantMessage: AgentMessage = {
        id: newId(),
        role: 'assistant',
        text: `No he podido consultar el LLM: ${message}. Comprueba Settings → Services y vuelve a intentarlo.`,
        createdAt: Date.now(),
      }
      setMessages(current => [...current, assistantMessage].slice(-40))
      setState('error')
    } finally {
      if (mountedRef.current) setBusy(false)
    }
  }

  const submit = (event: FormEvent) => {
    event.preventDefault()
    void ask(draft)
  }

  const handleKeyDown = (event: ReactKeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      void ask(draft)
    }
  }

  return (
    <section
      role="dialog"
      aria-label="Ask to the Wizard"
      className="hp-agent-panel absolute bottom-full left-2 mb-2 flex h-[min(34rem,calc(100vh-5rem))] w-[min(25rem,calc(100vw-1rem))] flex-col overflow-hidden rounded-2xl border border-amber-200/20 bg-[#0d0b13]/95 text-xs shadow-2xl backdrop-blur-xl"
    >
      <div className="relative overflow-hidden border-b border-white/10 px-3 py-3">
        <div className="hp-agent-panel-glow" aria-hidden="true" />
        <div className="relative flex items-center gap-3">
          <AgentAvatar state={state} size={48} />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <h2 className="hp-wordmark text-lg font-semibold text-amber-50">Ask to the Wizard</h2>
              <span className="rounded-full border border-amber-200/20 bg-amber-200/10 px-1.5 py-0.5 text-[8px] uppercase tracking-wider text-amber-100/70">Guía · acciones</span>
            </div>
            <p className="truncate text-[10px] text-white/45">Workspace: {workspace}</p>
          </div>
          <button type="button" onClick={clearConversation} className="rounded-lg p-1.5 text-white/40 hover:bg-white/5 hover:text-white" title="Clear conversation" aria-label="Clear Ask to the Wizard conversation"><Trash2 size={13} /></button>
          <button type="button" onClick={onClose} className="rounded-lg p-1.5 text-white/40 hover:bg-white/5 hover:text-white" title="Close" aria-label="Close Ask to the Wizard"><X size={14} /></button>
        </div>
        <div className="relative mt-2 flex items-center gap-2 text-[9px] text-white/45">
          <span className={`h-1.5 w-1.5 rounded-full ${activeCount ? 'animate-pulse bg-blue-300' : 'bg-emerald-300'}`} />
          <span>{activeCount ? `${activeCount} active ${activeCount === 1 ? 'task' : 'tasks'}` : 'No active tasks'}</span>
          {latestTask && <span className="min-w-0 flex-1 truncate">Latest: {latestTask.title} · {latestTask.status}</span>}
        </div>
      </div>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-3 py-3" aria-live="polite">
        {messages.map(message => (
          <div key={message.id} className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={message.role === 'user'
              ? 'max-w-[88%] whitespace-pre-wrap rounded-2xl rounded-br-sm bg-blue-500/20 px-3 py-2 leading-relaxed text-blue-50'
              : 'max-w-[92%] rounded-2xl rounded-bl-sm border border-amber-200/10 bg-amber-100/[.045] px-3 py-2 leading-relaxed text-amber-50/85'}>
              {message.role === 'assistant' ? <AgentMarkdown text={message.text} /> : message.text}
            </div>
          </div>
        ))}
        {busy && (
          <div className="flex items-center gap-2 text-[10px] text-amber-100/60">
            <AgentAvatar state={state === 'acting' ? 'acting' : 'thinking'} size={24} />
            <Loader2 size={11} className="animate-spin" /> {busyMessage}
          </div>
        )}
        <div ref={endRef} />
      </div>

      {messages.length <= 1 && (
        <div className="flex flex-wrap gap-1.5 border-t border-white/5 px-3 pt-2">
          {['¿Qué hay en cola?', 'Abre 3D Video', 'Prepara un vídeo de ejemplo'].map(suggestion => (
            <button key={suggestion} type="button" disabled={busy} onClick={() => void ask(suggestion)} className="rounded-full border border-amber-200/15 bg-amber-200/5 px-2 py-1 text-[9px] text-amber-100/65 hover:border-amber-200/35 hover:text-amber-50 disabled:opacity-40">{suggestion}</button>
          ))}
        </div>
      )}

      <form onSubmit={submit} className="border-t border-white/10 p-3">
        <div className="flex items-end gap-2 rounded-xl border border-white/10 bg-black/25 p-2 focus-within:border-amber-200/35">
          <Sparkles size={14} className="mb-1 shrink-0 text-amber-200/55" />
          <textarea
            autoFocus
            rows={2}
            value={draft}
            disabled={busy}
            onChange={event => { setDraft(event.target.value); if (!busy) setState(event.target.value ? 'listening' : 'idle') }}
            onKeyDown={handleKeyDown}
            placeholder="Pide un hechizo en HocusPocus…"
            className="max-h-24 min-h-9 flex-1 resize-none bg-transparent text-[11px] leading-relaxed text-white outline-none placeholder:text-white/30 disabled:opacity-50"
          />
          <button type="submit" disabled={busy || !draft.trim()} className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-amber-200 text-[#1a1208] transition hover:bg-amber-100 disabled:cursor-not-allowed disabled:opacity-30" aria-label="Ask to the Wizard">
            {busy ? <Loader2 size={13} className="animate-spin" /> : <ArrowUp size={14} />}
          </button>
        </div>
        <p className="mt-1.5 text-center text-[8px] text-white/30">Consulta, navega y prepara. Las órdenes explícitas de generación entran en la cola real.</p>
      </form>
    </section>
  )
}
