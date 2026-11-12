import { useState } from 'react'
import { Bot, ExternalLink } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { agentTargets, isAgentChange, taskOrigin, type AgentTarget } from './agentOrigin'
import type { ActivityTaskLike } from './lineage'
import { openAgentTarget } from './openAgentTarget'

type Translate = (key: string, options?: object) => string

/** "Agent (MCP)" / "Wizard" chip beside a task title. */
export function OriginBadge({ task }: { task: ActivityTaskLike }) {
  const { t } = useUiTranslation('activity')
  const origin = taskOrigin(task)
  if (!origin) return null
  return (
    <span data-origin={origin} title={t(`origin.${origin}Title`)}
      className="inline-flex shrink-0 items-center gap-0.5 rounded border border-fuchsia-400/40 bg-fuchsia-400/10 px-1 py-px text-[8px] font-medium text-fuchsia-200">
      <Bot size={9} aria-hidden="true" /> {t(`origin.${origin}`)}
    </span>
  )
}

const OPENABLE = new Set<AgentTarget['kind']>([
  'world3d_template', 'world3d_scene', 'scene_file', 'character_kit', 'series_episode', 'series', 'story', 'montage',
  'workspace_collection', 'file',
])

function targetLabel(t: Translate, target: AgentTarget): string {
  const name = target.title || target.file || target.id
  return t(`agentTrail.open.${target.kind}`, { name, defaultValue: name })
}

/** What one agent change touched and buttons to open each result in its editor. */
export function AgentChangeDetail({ task, workspace }: { task: ActivityTaskLike; workspace: string }) {
  const { t: tRaw } = useUiTranslation('activity')
  const t = tRaw as unknown as Translate
  const [error, setError] = useState('')
  if (!isAgentChange(task)) return null
  // The task message already lists the tools (``world3d.scene.patch ×3``); this adds what they touched.
  const targets = agentTargets(task)
  const open = (target: AgentTarget) => {
    setError('')
    void openAgentTarget(target, workspace).catch(reason => setError(reason instanceof Error ? reason.message : String(reason)))
  }
  return (
    <div data-testid="agent-change" className="mt-1 space-y-1">
      <div className="flex flex-wrap gap-1">
        {targets.filter(target => OPENABLE.has(target.kind)).map(target => (
          <button key={`${target.kind}:${target.id}`} type="button" data-target-kind={target.kind} onClick={() => open(target)}
            className="inline-flex items-center gap-1 rounded border border-fuchsia-400/30 px-1.5 py-0.5 text-[9px] text-fuchsia-200 hover:bg-fuchsia-400/10">
            <ExternalLink size={9} aria-hidden="true" /> {targetLabel(t, target)}
          </button>
        ))}
      </div>
      {error ? <p role="alert" className="text-[9px] text-red-300">{error}</p> : null}
    </div>
  )
}
