import { useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent as ReactKeyboardEvent } from 'react'
import { createPortal } from 'react-dom'
import { ArrowUp, Loader2, Maximize2, Minimize2, Sparkles, Trash2, X } from 'lucide-react'
import { fetchWizardConversation, generateLlmText, saveWizardConversation, type CanonicalTask } from '../../api/client'
import { AgentAvatar, type AgentVisualState } from './AgentAvatar'
import { buildAgentTurnPrompt, HOCUSPOCUS_AGENT_SYSTEM_PROMPT, type AgentConversationEntry } from './agentKnowledge'
import {
  buildAgentAppSnapshot,
  executeAgentActions,
  HOCUSPOCUS_AGENT_RESPONSE_SCHEMA,
  humanReply,
  parseAgentTurn,
  reconcileAgentTurnWithRequest,
  type AgentActionResult,
} from './agentActions'
import { applyPollToCard, cardsFromResults, tabForExecutionTarget, type WizardExecutionCard } from './executionCards'
import { AgentMarkdown } from './AgentMarkdown'

export { AgentAvatar, type AgentVisualState } from './AgentAvatar'

interface AgentMessage extends AgentConversationEntry {
  id: string
  createdAt: number
  cards?: WizardExecutionCard[]
}

interface AgentAssistantPanelProps {
  workspace: string
  tasks: CanonicalTask[]
  onClose: () => void
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
  const lines = results.map(result => `- **${result.ok ? 'Hecho' : 'No se pudo'}.** ${result.message}`)
  return `### Qué he hecho\n${lines.join('\n')}`
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
    )).map(message => ({
      ...message,
      cards: Array.isArray(message.cards) ? message.cards : undefined,
    })).slice(-40)
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

export function AgentAssistantPanel({ workspace, tasks, onClose }: AgentAssistantPanelProps) {
  const [messages, setMessages] = useState<AgentMessage[]>(() => readMessages(workspace))
  const [conversationWorkspace, setConversationWorkspace] = useState(workspace)
  const [draft, setDraft] = useState('')
  const [state, setState] = useState<AgentVisualState>('idle')
  const [busy, setBusy] = useState(false)
  const [busyMessage, setBusyMessage] = useState('Consultando el grimorio de HocusPocus…')
  const [expanded, setExpanded] = useState(false)
  const [errorCardId, setErrorCardId] = useState<string | null>(null)
  const [conversationRevision, setConversationRevision] = useState(0)
  const endRef = useRef<HTMLDivElement>(null)
  const mountedRef = useRef(true)
  const conversationRevisionRef = useRef(0)
  const activeCount = useMemo(() => tasks.filter(task => ACTIVE.has(task.status) && !task.parent_id).length, [tasks])
  const latestTask = useMemo(() => [...tasks].sort((left, right) => right.updated_at - left.updated_at)[0], [tasks])

  useEffect(() => {
    mountedRef.current = true
    return () => { mountedRef.current = false }
  }, [])

  useEffect(() => {
    writeMessages(conversationWorkspace, messages)
    endRef.current?.scrollIntoView({ block: 'end' })
    const cards = messages.flatMap(message => message.cards || [])
    void saveWizardConversation(conversationWorkspace, {
      version: 1,
      revision: conversationRevisionRef.current,
      messages,
      executions: cards,
    }).then(saved => {
      conversationRevisionRef.current = saved.revision
      if (mountedRef.current) setConversationRevision(saved.revision)
    }).catch(() => {
      // Local storage still holds the turn if the workspace file cannot be written.
    })
  }, [conversationWorkspace, messages])

  useEffect(() => {
    let cancelled = false
    void fetchWizardConversation(workspace).then(payload => {
      if (cancelled || busy) return
      const remote = Array.isArray(payload.messages) ? payload.messages : []
      const restored = remote.filter((message): message is AgentMessage => (
        Boolean(message)
        && typeof message.id === 'string'
        && (message.role === 'user' || message.role === 'assistant')
        && typeof message.text === 'string'
      )).map(message => ({
        ...message,
        createdAt: typeof message.createdAt === 'number' ? message.createdAt : Date.now(),
        cards: Array.isArray(message.cards) && message.cards.length
          ? message.cards
          : undefined,
      }))
      if (!restored.length && payload.executions?.length) {
        restored.push({
          ...welcomeMessage(),
          cards: payload.executions as AgentMessage['cards'],
        })
      }
      if (restored.length) {
        setMessages(restored.slice(-40))
        conversationRevisionRef.current = payload.revision || 0
        setConversationRevision(payload.revision || 0)
      }
    }).catch(() => {
      // Fall back to the local cache already loaded for this workspace.
    })
    return () => { cancelled = true }
  }, [workspace, busy])

  useEffect(() => {
    if (workspace === conversationWorkspace) return
    if (busy) {
      // A Wizard action changed workspace while this turn was executing.
      // Keep the visible turn alive and persist it in the destination so its
      // real action result is not lost when the footer updates.
      setConversationWorkspace(workspace)
      return
    }
    setMessages(readMessages(workspace))
    setConversationWorkspace(workspace)
    setState('idle')
  }, [busy, conversationWorkspace, workspace])

  useEffect(() => {
    setMessages(current => current.map(message => {
      if (!message.cards?.length) return message
      let changed = false
      const cards = message.cards.map(card => {
        const task = tasks.find(item => (
          (card.taskId && (item.id === card.taskId || item.root_id === card.taskId || item.backend_job_id === card.taskId))
          || (card.pipelineId && item.pipeline_id === card.pipelineId)
        ))
        if (!task) return card
        const state = task.status === 'completed' ? 'completed'
          : task.status === 'failed' || task.status === 'cancelled' ? 'failed'
            : task.status === 'queued' || task.status === 'waiting_resource' ? 'queued'
              : 'running'
        const outputNames = task.result_refs?.length ? task.result_refs : card.outputNames
        if (state === card.state && (task.message || card.message) === card.message && outputNames === card.outputNames) {
          return card
        }
        changed = true
        return applyPollToCard(card, {
          state,
          message: task.message || card.message,
          outputNames,
          taskId: task.id || card.taskId,
          recoverable: state === 'failed' || card.recoverable,
        })
      })
      return changed ? { ...message, cards } : message
    }))
  }, [tasks])

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      if (expanded) {
        event.preventDefault()
        setExpanded(false)
        return
      }
      onClose()
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [expanded, onClose])

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
      const turn = await reconcileAgentTurnWithRequest(
        question,
        parseAgentTurn(answer),
        nextMessages.map(message => ({ role: message.role, text: message.text })),
      )
      let results: AgentActionResult[] = []
      if (turn.actions.length) {
        setState('acting')
        results = await executeAgentActions(turn.actions, message => {
          if (mountedRef.current) setBusyMessage(message)
        })
      }
      if (!mountedRef.current) return
      const cards = cardsFromResults(results)
      const actionReport = formatActionResults(results)
      const assistantMessage: AgentMessage = {
        id: newId(),
        role: 'assistant',
        text: [humanReply(turn.reply || '') || 'Mi bola de cristal no ha devuelto una respuesta utilizable.', actionReport]
          .filter(Boolean)
          .join('\n\n'),
        createdAt: Date.now(),
        cards: cards.length ? cards : undefined,
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

  const panel = (
    <section
      role="dialog"
      aria-modal="true"
      aria-label="Ask to the Wizard"
      data-expanded={expanded ? 'true' : 'false'}
      className={`hp-agent-panel z-[100] flex flex-col overflow-hidden border border-amber-200/20 bg-[#0d0b13]/95 shadow-2xl backdrop-blur-xl ${expanded
        ? 'hp-agent-panel--expanded fixed inset-0 rounded-none text-sm sm:inset-2 sm:rounded-2xl'
        : 'fixed bottom-12 left-2 h-[min(34rem,calc(100vh-5rem))] w-[min(25rem,calc(100vw-1rem))] rounded-2xl text-xs'}`}
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
          <button
            type="button"
            onClick={() => setExpanded(current => !current)}
            className="rounded-lg p-1.5 text-white/40 hover:bg-white/5 hover:text-white"
            title={expanded ? 'Restore chat size' : 'Maximize chat'}
            aria-label={expanded ? 'Restore Ask to the Wizard size' : 'Maximize Ask to the Wizard'}
            aria-pressed={expanded}
          >
            {expanded ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
          </button>
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
              ? `${expanded ? 'max-w-[min(42rem,70%)]' : 'max-w-[88%]'} whitespace-pre-wrap rounded-2xl rounded-br-sm bg-blue-500/20 px-3 py-2 leading-relaxed text-blue-50`
              : `${expanded ? 'max-w-[min(56rem,86%)]' : 'max-w-[92%]'} rounded-2xl rounded-bl-sm border border-amber-200/10 bg-amber-100/[.045] px-3 py-2 leading-relaxed text-amber-50/85`}>
              {message.role === 'assistant' ? <AgentMarkdown text={message.text} /> : message.text}
              {message.cards?.map(card => (
                <div key={card.id} className="mt-2 rounded-xl border border-amber-200/15 bg-black/20 p-2">
                  <div className="flex items-center justify-between gap-2 text-[10px]">
                    <span className="font-medium uppercase tracking-wide text-amber-100/80">{card.state}</span>
                    {card.target?.title && <span className="min-w-0 truncate text-white/50">{card.target.title}</span>}
                  </div>
                  <p className="mt-1 text-[10px] leading-relaxed text-amber-50/80">{card.message}</p>
                  {card.outputNames?.length ? (
                    <p className="mt-1 truncate text-[9px] text-emerald-200/80">Outputs: {card.outputNames.join(', ')}</p>
                  ) : null}
                  {errorCardId === card.id && card.controls.viewErrors && (
                    <p className="mt-1 text-[9px] text-rose-200/80">{card.message}</p>
                  )}
                  <div className="mt-2 flex flex-wrap gap-1">
                    {card.controls.open && (
                      <button type="button" className="rounded border border-white/10 px-1.5 py-0.5 text-[9px] text-white/70 hover:bg-white/5" onClick={() => void executeAgentActions([{ type: 'open_tab', tab: tabForExecutionTarget(card.target?.kind) }])}>Abrir destino</button>
                    )}
                    {card.controls.cancel && (
                      <button type="button" className="rounded border border-white/10 px-1.5 py-0.5 text-[9px] text-white/70 hover:bg-white/5" onClick={() => void executeAgentActions([{ type: 'cancel_task', taskId: card.taskId || 'latest', confirm: true }])}>Cancelar</button>
                    )}
                    {card.controls.resume && (
                      <button type="button" className="rounded border border-white/10 px-1.5 py-0.5 text-[9px] text-white/70 hover:bg-white/5" onClick={() => void executeAgentActions([{ type: 'resume_task', taskId: card.taskId || 'latest', confirm: true }])}>Reanudar</button>
                    )}
                    {card.controls.viewErrors && (
                      <button type="button" className="rounded border border-white/10 px-1.5 py-0.5 text-[9px] text-white/70 hover:bg-white/5" onClick={() => setErrorCardId(card.id)}>Ver errores</button>
                    )}
                    {card.controls.retryPending && (
                      <button type="button" className="rounded border border-white/10 px-1.5 py-0.5 text-[9px] text-white/70 hover:bg-white/5" onClick={() => void executeAgentActions([{ type: 'retry_task', taskId: card.taskId || 'latest', confirm: true }])}>Reintentar pendientes</button>
                    )}
                  </div>
                </div>
              ))}
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
          {['¿Qué hay en cola?', 'Abre 3D Video', 'Hazme un cómic de ejemplo'].map(suggestion => (
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
            className={`${expanded ? 'max-h-40' : 'max-h-24'} min-h-9 flex-1 resize-none bg-transparent text-[11px] leading-relaxed text-white outline-none placeholder:text-white/30 disabled:opacity-50`}
          />
          <button type="submit" disabled={busy || !draft.trim()} className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-amber-200 text-[#1a1208] transition hover:bg-amber-100 disabled:cursor-not-allowed disabled:opacity-30" aria-label="Ask to the Wizard">
            {busy ? <Loader2 size={13} className="animate-spin" /> : <ArrowUp size={14} />}
          </button>
        </div>
        <p className="mt-1.5 text-center text-[8px] text-white/30">Consulta, navega y prepara. Las órdenes explícitas de generación entran en la cola real.</p>
      </form>
    </section>
  )

  return createPortal(
    <>
      {expanded && (
        <div
          className="fixed inset-0 z-[99] bg-black/70"
          onClick={() => setExpanded(false)}
          aria-hidden="true"
        />
      )}
      {panel}
    </>,
    document.body,
  )
}
