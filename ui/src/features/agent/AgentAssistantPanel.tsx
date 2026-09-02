import { useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent as ReactKeyboardEvent } from 'react'
import { createPortal } from 'react-dom'
import { ArrowUp, Loader2, Maximize2, Minimize2, PanelLeftClose, Sparkles, Trash2 } from 'lucide-react'
import { fetchWizardConversation, generateLlmText, saveWizardConversation, subscribeCanonicalTaskEvents, type CanonicalTask } from '../../api/client'
import { AgentAvatar, type AgentVisualState } from './AgentAvatar'
import { buildAgentTurnPrompt, HOCUSPOCUS_AGENT_SYSTEM_PROMPT, type AgentConversationEntry } from './agentKnowledge'
import {
  buildAgentAppSnapshot,
  executeAgentActions,
  HOCUSPOCUS_AGENT_RESPONSE_SCHEMA,
  humanReply,
  parseAgentTurn,
  protectUserVerbatimSegments,
  reconcileAgentTurnWithRequest,
  type AgentActionResult,
} from './agentActions'
import { applyPollToCard, cardsFromResults, tabForExecutionTarget, type WizardExecutionCard } from './executionCards'
import { applyRemoteWizardConversation, WIZARD_WELCOME_TEXT } from './wizardConversationSync'
import { AgentMarkdown } from './AgentMarkdown'
import { defaultWizardWorkflowRuntime, type WizardWorkflowPendingInput, type WizardWorkflowRecord } from './wizardWorkflowRuntime'
import { ensureRhythmic3dWorkflowRegistered } from './rhythmic3dWorkflow'
import { defaultApplicationAdapters } from './applicationAdapters'
import { useUiTranslation } from '../../i18n'

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
  embedded?: boolean
}

function agentPanelPresentation(embedded: boolean, expanded: boolean) {
  if (embedded && !expanded) {
    return { role: 'region' as const, ariaModal: undefined, autoFocus: false }
  }
  return { role: 'dialog' as const, ariaModal: 'true' as const, autoFocus: !embedded }
}

const ACTIVE = new Set(['created', 'queued', 'waiting_resource', 'running'])
const STORAGE_PREFIX = 'hocuspocus-agent-chat-v2:'

declare global {
  interface Window {
    __HOCUSPOCUS_WIZARD_TRACE__?: Array<Record<string, unknown>>
  }
}

function appendWizardTrace(entry: Record<string, unknown>): void {
  // Ephemeral inspection hook for headed/manual acceptance runs. It is never
  // persisted or sent to the backend; the durable conversation remains the
  // product record. Keep a bounded list so normal sessions cannot grow it.
  const trace = window.__HOCUSPOCUS_WIZARD_TRACE__ || []
  window.__HOCUSPOCUS_WIZARD_TRACE__ = [...trace, entry].slice(-50)
}

const newId = () => globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`

function normalizedChoice(value: unknown): string {
  return String(value ?? '').trim().toLocaleLowerCase()
}

// Kept exported for the focused pending-answer contract test.
// eslint-disable-next-line react-refresh/only-export-components
export function resolveWizardPendingAnswer(pending: WizardWorkflowPendingInput, text: string): Record<string, unknown> | null {
  if (pending.fields.length === 1) {
    const field = pending.fields[0]
    const typed = text.trim()
    const option = pending.options.find(item => (
      (!item.field || item.field === field)
      && (normalizedChoice(item.label) === normalizedChoice(typed)
        || normalizedChoice(item.value) === normalizedChoice(typed))
    ))
    if (pending.options.length && !option) return null
    return { [field]: option ? option.value : typed }
  }
  const entries = text.split(/[\n,]+/).flatMap(part => {
    const match = part.match(/^\s*([^:=]+)\s*[:=]\s*(.+?)\s*$/)
    return match ? [[match[1].trim(), match[2].trim()] as const] : []
  })
  const answer = Object.fromEntries(entries)
  return pending.fields.every(field => Object.prototype.hasOwnProperty.call(answer, field)) ? answer : null
}

const welcomeMessage = (): AgentMessage => ({
  id: newId(),
  role: 'assistant',
  text: WIZARD_WELCOME_TEXT,
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

export function AgentAssistantPanel({ workspace, tasks, onClose, embedded = false }: AgentAssistantPanelProps) {
  const { t } = useUiTranslation('wizard')
  const [messages, setMessages] = useState<AgentMessage[]>(() => readMessages(workspace))
  const [conversationWorkspace, setConversationWorkspace] = useState(workspace)
  const [hydratedWorkspace, setHydratedWorkspace] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const [state, setState] = useState<AgentVisualState>('idle')
  const [busy, setBusy] = useState(false)
  const [busyMessage, setBusyMessage] = useState('Consultando el grimorio de HocusPocus…')
  const [expanded, setExpanded] = useState(false)
  const [errorCardId, setErrorCardId] = useState<string | null>(null)
  const [activeWorkflow, setActiveWorkflow] = useState<WizardWorkflowRecord | null>(null)
  const [pendingInput, setPendingInput] = useState<WizardWorkflowPendingInput | null>(null)
  const endRef = useRef<HTMLDivElement>(null)
  const mountedRef = useRef(true)
  const conversationRevisionRef = useRef(0)
  const skipNextConversationSaveRef = useRef(false)
  const conversationWorkspaceRef = useRef(conversationWorkspace)
  conversationWorkspaceRef.current = conversationWorkspace
  const messagesRef = useRef(messages)
  messagesRef.current = messages
  const activeCount = useMemo(() => tasks.filter(task => ACTIVE.has(task.status) && !task.parent_id).length, [tasks])
  const latestTask = useMemo(() => [...tasks].sort((left, right) => right.updated_at - left.updated_at)[0], [tasks])
  const panelPresentation = agentPanelPresentation(embedded, expanded)

  useEffect(() => {
    mountedRef.current = true
    return () => { mountedRef.current = false }
  }, [])

  useEffect(() => {
    let active = true
    ensureRhythmic3dWorkflowRegistered(defaultApplicationAdapters)
    const unsubscribe = defaultWizardWorkflowRuntime.subscribe(({ workflow, card }) => {
      if (!active || workflow.workspace !== workspace) return
      setActiveWorkflow(workflow)
      setPendingInput(workflow.state === 'awaiting_input' ? workflow.pendingInput : null)
      setMessages(current => {
        let found = false
        const updated = current.map(message => {
          if (!message.cards?.some(existing => existing.id === card.id)) return message
          found = true
          return {
            ...message,
            text: workflow.state === 'awaiting_input'
              ? `🪄 **Necesito una decisión para continuar el mismo hechizo.**\n\n${workflow.pendingInput?.reason || 'Falta un dato requerido.'}`
              : `El hechizo duradero **${workflow.type}** está ahora en estado **${workflow.state}**.`,
            cards: message.cards.map(existing => existing.id === card.id ? card : existing),
          }
        })
        if (found) return updated
        return [...updated, {
          id: `wizard-workflow-${workflow.workflowId}`,
          role: 'assistant' as const,
          text: workflow.state === 'awaiting_input'
            ? `🪄 **Necesito una decisión para continuar el mismo hechizo.**\n\n${workflow.pendingInput?.reason || 'Falta un dato requerido.'}`
            : `El hechizo duradero **${workflow.type}** está ahora en estado **${workflow.state}**.`,
          createdAt: Date.now(),
          cards: [card],
        }].slice(-40)
      })
    })
    void defaultWizardWorkflowRuntime.open(workspace).catch(() => {
      // Existing immediate actions remain available if workflow storage is offline.
    })
    const closeEvents = subscribeCanonicalTaskEvents(workspace, event => {
      void defaultWizardWorkflowRuntime.handleTaskEvent(event).catch(() => {
        // The checkpoint stays recoverable; a reconnect replays the same event.
      })
    })
    return () => {
      active = false
      unsubscribe()
      closeEvents()
    }
  }, [workspace])

  useEffect(() => {
    setActiveWorkflow(null)
    setPendingInput(null)
  }, [workspace])

  useEffect(() => {
    writeMessages(conversationWorkspace, messages)
    endRef.current?.scrollIntoView({ block: 'end' })
    if (hydratedWorkspace !== conversationWorkspace) return
    if (skipNextConversationSaveRef.current) {
      skipNextConversationSaveRef.current = false
      return
    }
    const cards = messages.flatMap(message => message.cards || [])
    void saveWizardConversation(conversationWorkspace, {
      version: 1,
      revision: conversationRevisionRef.current,
      messages,
      executions: cards,
    }).then(saved => {
      conversationRevisionRef.current = saved.revision
    }).catch(async () => {
      // A second tab may have advanced the CAS revision. Re-read and merge by
      // message id; the resulting state triggers one save against the current
      // backend revision. Local storage remains the fallback if this fails.
      try {
        const current = await fetchWizardConversation(conversationWorkspace)
        if (!mountedRef.current || conversationWorkspaceRef.current !== conversationWorkspace) return
        const choice = applyRemoteWizardConversation({
          localMessages: messagesRef.current,
          localRevision: conversationRevisionRef.current,
          remoteMessages: current.messages,
          remoteRevision: current.revision || 0,
          remoteExecutions: current.executions,
        })
        conversationRevisionRef.current = choice.revision
        skipNextConversationSaveRef.current = choice.source === 'remote'
        setMessages([...choice.messages] as AgentMessage[])
      } catch {
        // Local storage still holds the turn while the backend is unavailable.
      }
    })
  }, [conversationWorkspace, hydratedWorkspace, messages])

  useEffect(() => {
    let cancelled = false
    void fetchWizardConversation(workspace).then(payload => {
      if (cancelled) return
      const choice = applyRemoteWizardConversation({
        localMessages: messagesRef.current,
        localRevision: conversationRevisionRef.current,
        remoteMessages: payload.messages,
        remoteRevision: payload.revision || 0,
        remoteExecutions: payload.executions,
      })
      conversationRevisionRef.current = choice.revision
      skipNextConversationSaveRef.current = choice.source === 'remote'
      // A local choice may still adopt the backend's newer CAS revision and
      // merge remote-only messages. Use a fresh array so the persistence
      // effect retries the canonical save with that revision.
      setMessages([...choice.messages] as AgentMessage[])
      setHydratedWorkspace(workspace)
    }).catch(() => {
      // Fall back to the local cache already loaded for this workspace.
      if (!cancelled) setHydratedWorkspace(workspace)
    })
    return () => { cancelled = true }
  }, [workspace])

  useEffect(() => {
    if (workspace === conversationWorkspace) return
    conversationRevisionRef.current = 0
    skipNextConversationSaveRef.current = false
    setHydratedWorkspace(null)
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
    const traceStartedAt = new Date().toISOString()
    try {
      if (pendingInput) {
        const answer = resolveWizardPendingAnswer(pendingInput, question)
        if (!answer) {
          const choices = pendingInput.options.map(option => `“${option.label}”`).join(', ')
          throw new Error(choices
            ? `Elige una de estas opciones para continuar el hechizo: ${choices}.`
            : `Responde los campos ${pendingInput.fields.map(field => `${field}=valor`).join(', ')}.`)
        }
        setBusyMessage('Aplicando tu decisión al paso bloqueado…')
        await defaultWizardWorkflowRuntime.answer(pendingInput.workflowId, answer, {
          stepId: pendingInput.stepId,
          version: pendingInput.version,
        })
        if (!mountedRef.current) return
        setState('success')
        return
      }
      const answer = await generateLlmText({
        system_prompt: HOCUSPOCUS_AGENT_SYSTEM_PROMPT,
        prompt: buildAgentTurnPrompt(workspace, nextMessages, tasks, buildAgentAppSnapshot({
          workflow: activeWorkflow,
          pending_question: pendingInput,
        })),
        max_new_tokens: 3_200,
        temperature: .1,
        json_schema: HOCUSPOCUS_AGENT_RESPONSE_SCHEMA,
      })
      if (!mountedRef.current) return
      const proposedTurn = parseAgentTurn(answer)
      const reconciledTurn = await reconcileAgentTurnWithRequest(
        question,
        proposedTurn,
        nextMessages.map(message => ({ role: message.role, text: message.text })),
      )
      const turn = protectUserVerbatimSegments(question, {
        ...reconciledTurn,
        conversationLanguage: reconciledTurn.conversationLanguage || proposedTurn.conversationLanguage,
      })
      let results: AgentActionResult[] = []
      if (turn.actions.length) {
        setState('acting')
        results = await executeAgentActions(turn.actions, message => {
          if (mountedRef.current) setBusyMessage(message)
        })
      }
      appendWizardTrace({
        startedAt: traceStartedAt,
        finishedAt: new Date().toISOString(),
        workspace,
        question,
        llmAnswer: answer,
        turn,
        results,
      })
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
        language: turn.conversationLanguage || undefined,
        cards: cards.length ? cards : undefined,
      }
      setMessages(current => [...current, assistantMessage].slice(-40))
      setState(results.some(result => !result.ok) ? 'error' : 'success')
    } catch (error) {
      if (!mountedRef.current) return
      const message = error instanceof Error ? error.message : String(error)
      appendWizardTrace({
        startedAt: traceStartedAt,
        finishedAt: new Date().toISOString(),
        workspace,
        question,
        error: message,
      })
      const assistantMessage: AgentMessage = {
        id: newId(),
        role: 'assistant',
        text: pendingInput
          ? `No puedo aplicar todavía esa respuesta al paso bloqueado: ${message}`
          : `No he podido consultar el LLM: ${message}. Comprueba Settings → Services y vuelve a intentarlo.`,
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
      role={panelPresentation.role}
      aria-modal={panelPresentation.ariaModal}
      aria-label={t('title')}
      data-expanded={expanded ? 'true' : 'false'}
      className={`hp-agent-panel z-[100] flex flex-col overflow-hidden border border-amber-200/20 bg-[#0d0b13]/95 shadow-2xl backdrop-blur-xl ${expanded
        ? 'hp-agent-panel--expanded fixed inset-0 rounded-none text-sm sm:inset-2 sm:rounded-2xl'
        : embedded
          ? 'relative h-full w-full border-0 text-xs shadow-none'
          : 'fixed bottom-12 left-2 h-[min(34rem,calc(100vh-5rem))] w-[min(25rem,calc(100vw-1rem))] rounded-2xl text-xs'}`}
    >
      <div className="relative overflow-hidden border-b border-white/10 px-3 py-3">
        <div className="hp-agent-panel-glow" aria-hidden="true" />
        <div className="relative flex items-center gap-3">
          <AgentAvatar state={state} size={48} />
          <div className="min-w-0 flex-1">
            <h2 className="hp-wordmark max-w-36 whitespace-normal text-xl font-semibold leading-[1.05] text-amber-50">{t('title')}</h2>
            <p className="truncate text-[10px] text-white/45">Workspace: {workspace}</p>
          </div>
          <button
            type="button"
            onClick={() => setExpanded(current => !current)}
            className="rounded-lg p-1.5 text-white/40 hover:bg-white/5 hover:text-white"
            title={expanded ? 'Restore chat size' : 'Maximize chat'}
            aria-label={expanded ? t('restore') : t('maximize')}
            aria-pressed={expanded}
          >
            {expanded ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
          </button>
          <button type="button" onClick={clearConversation} className="rounded-lg p-1.5 text-white/40 hover:bg-white/5 hover:text-white" title={t('clear')} aria-label={t('clear')}><Trash2 size={13} /></button>
          <button type="button" onClick={onClose} className="rounded-lg p-1.5 text-white/40 hover:bg-white/5 hover:text-white" title={t('close')} aria-label={t('close')}><PanelLeftClose size={15} /></button>
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
            <div lang={message.language || undefined} className={message.role === 'user'
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
                  {card.assetIds?.length ? (
                    <p className="mt-1 truncate text-[9px] text-emerald-200/80">Assets: {card.assetIds.join(', ')}</p>
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

      {pendingInput && (
        <div className="border-t border-amber-200/10 bg-amber-200/[.035] px-3 py-2" role="group" aria-label="Wizard pending question">
          <p className="text-[10px] font-medium text-amber-100">El hechizo está esperando tu elección</p>
          <p className="mt-0.5 text-[9px] text-amber-50/65">{pendingInput.reason}</p>
          {pendingInput.options.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {pendingInput.options.map((option, index) => {
                const field = option.field || pendingInput.fields[0]
                return (
                  <button
                    key={`${field}-${index}`}
                    type="button"
                    disabled={busy}
                    onClick={() => void ask(option.label)}
                    className="rounded-lg border border-amber-200/25 bg-amber-200/10 px-2 py-1 text-[9px] text-amber-50 hover:bg-amber-200/20 disabled:opacity-40"
                    title={option.description}
                  >
                    {option.label}{Object.is(option.value, pendingInput.recommended) ? ' · recomendado' : ''}
                  </button>
                )
              })}
            </div>
          )}
        </div>
      )}

      <form onSubmit={submit} className="border-t border-white/10 p-3">
        <div className="flex items-end gap-2 rounded-xl border border-white/10 bg-black/25 p-2 focus-within:border-amber-200/35">
          <Sparkles size={14} className="mb-1 shrink-0 text-amber-200/55" />
          <textarea
            autoFocus={panelPresentation.autoFocus}
            rows={2}
            value={draft}
            disabled={busy}
            onChange={event => { setDraft(event.target.value); if (!busy) setState(event.target.value ? 'listening' : 'idle') }}
            onKeyDown={handleKeyDown}
            placeholder={t('placeholder')}
            className={`${expanded ? 'max-h-40' : 'max-h-24'} min-h-9 flex-1 resize-none bg-transparent text-[11px] leading-relaxed text-white outline-none placeholder:text-white/30 disabled:opacity-50`}
          />
          <button type="submit" disabled={busy || !draft.trim()} className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-amber-200 text-[#1a1208] transition hover:bg-amber-100 disabled:cursor-not-allowed disabled:opacity-30" aria-label={t('title')}>
            {busy ? <Loader2 size={13} className="animate-spin" /> : <ArrowUp size={14} />}
          </button>
        </div>
        <p className="mt-1.5 text-center text-[8px] text-white/30">Consulta, navega y prepara. Las órdenes explícitas de generación entran en la cola real.</p>
      </form>
    </section>
  )

  if (embedded && !expanded) return panel

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
