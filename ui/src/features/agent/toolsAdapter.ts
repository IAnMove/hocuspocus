import { useStore } from '../../stores/useStore'
import * as api from '../../api/client'
import i18n from '../../i18n'
import type { AdapterOutcome, ToolsAdapter } from './applicationAdapters'
import type { AgentRemoveBackgroundAction } from './agentActions'
import type { AgentTab } from './capabilityRegistry'
import type { GenerationSubmissionContext } from '../studio/generationProvenance'
import {
  executionKey,
  executionReport,
  rememberExecution,
  type AgentExecutionTarget,
} from './agentContract'

type Navigate = (tab: AgentTab) => Promise<AdapterOutcome>
type ResolvedSource = {
  source: string
  name: string
  url: string
  assetId?: string
  sourceWorkspace?: string
}

function sourceBasename(source: string): string {
  const path = source.trim().split(/[?#]/, 1)[0]
  const name = path.split(/[/\\]/).pop() || path
  try {
    return decodeURIComponent(name)
  } catch {
    return name
  }
}

function sourceUrl(source: string, sourceWorkspace: string | undefined, workspace: string): string {
  const raw = source.trim()
  if (raw.startsWith('/api/')) return raw
  const filename = sourceBasename(raw)
  if (sourceWorkspace === '__uploads__') return `/api/v1/uploads/${encodeURIComponent(filename)}`
  return `/api/v1/file/${encodeURIComponent(filename)}?workspace=${encodeURIComponent(sourceWorkspace || workspace)}`
}

async function resolveSource(
  action: AgentRemoveBackgroundAction,
  workspace: string,
): Promise<ResolvedSource> {
  const assetId = action.assetId?.trim() || undefined
  const assetSource = await loadAssetSource(assetId, action.sourceWorkspace, workspace)
  return finishSource(action, workspace, assetId, assetSource)
}

async function loadAssetSource(
  assetId: string | undefined,
  preferredWorkspace: string | undefined,
  workspace: string,
): Promise<{ asset: api.AssetCatalogItem; source: string; sourceWorkspace: string } | undefined> {
  if (!assetId) return undefined
  return resolveAssetSource(assetId, preferredWorkspace, workspace)
}

function finishSource(
  action: AgentRemoveBackgroundAction,
  workspace: string,
  assetId: string | undefined,
  assetSource: { asset: api.AssetCatalogItem; source: string; sourceWorkspace: string } | undefined,
): ResolvedSource {
  const rawSource = action.source?.trim() || ''
  const source = assetSource
    ? (rawSource ? sourceBasename(rawSource) : assetSource.source)
    : rawSource
  if (!source) throw new Error(i18n.t('removeBackgroundMissingSource', { ns: 'wizard' }))
  const fallbackName = sourceBasename(source)
  const name = assetSource?.asset.filename || fallbackName
  const sourceWorkspace = action.sourceWorkspace?.trim() || assetSource?.sourceWorkspace
  return { source, name, url: sourceUrl(source, sourceWorkspace, workspace), assetId, sourceWorkspace }
}

async function resolveAssetSource(
  assetId: string,
  preferredWorkspace: string | undefined,
  workspace: string,
): Promise<{ asset: api.AssetCatalogItem; source: string; sourceWorkspace: string }> {
  const asset = await api.fetchAsset(assetId)
  if (asset.kind !== 'image') throw new Error(i18n.t('removeBackgroundInvalidAsset', { ns: 'wizard' }))
  const location = asset.locations.find(item => item.workspace_id === preferredWorkspace)
    || asset.locations.find(item => item.workspace_id === workspace)
    || asset.locations[0]
  if (!location) throw new Error(i18n.t('removeBackgroundNoLocation', { ns: 'wizard' }))
  return { asset, source: location.filename, sourceWorkspace: location.workspace_id }
}

function target(taskId: string): AgentExecutionTarget {
  return { kind: 'tool_job', id: taskId, title: i18n.t('removeBackgroundTitle', { ns: 'wizard' }) }
}

export function createToolsAdapter(navigate: Navigate): ToolsAdapter {
  return {
    async removeBackground(action, context?: GenerationSubmissionContext) {
      const workspace = useStore.getState().activeWorkspace || 'default'
      const source = await resolveSource(action, workspace)
      await showSource(navigate, source)
      const result = await api.submitToolRemoveBackground(buildRequest(action, context, source, workspace))
      const taskId = result.task_id || result.job_id
      const message = i18n.t('removeBackgroundQueued', { ns: 'wizard', name: source.name })
      const jobTarget = target(taskId)
      const report = executionReport({
        state: 'queued', message, target: jobTarget, taskId, recoverable: true,
        executionKey: executionKey({ workspace, type: action.type, targetId: source.assetId || source.source, params: action }),
      })
      rememberExecution(report)
      return {
        message, target: jobTarget, taskId, report,
        metadata: {
          tool: 'remove_background', sourceAssetId: source.assetId || null,
          source: source.source, sourceWorkspace: source.sourceWorkspace || workspace,
          model: 'rembg-u2net',
        },
      }
    },
  }
}

async function showSource(navigate: Navigate, source: ResolvedSource): Promise<void> {
  await navigate('studio')
  const state = useStore.getState()
  state.setGenerationMode('tools')
  state.setToolsTool('remove_background')
  state.setToolsSource({
    path: source.source, name: source.name, url: source.url,
    assetId: source.assetId || null, workspace: source.sourceWorkspace || null, kind: 'image',
  })
}

function buildRequest(
  action: AgentRemoveBackgroundAction,
  context: GenerationSubmissionContext | undefined,
  source: ResolvedSource,
  workspace: string,
) {
  return {
    asset_id: source.assetId,
    source: source.source,
    source_workspace: source.sourceWorkspace,
    workspace,
    instruction: action.instruction || '',
    provenance: requestProvenance(context),
  }
}

function requestProvenance(context: GenerationSubmissionContext | undefined) {
  return {
    actor: context?.actor || 'wizard',
    capability: context?.capability || 'remove_background',
    workspace_id: context?.workspaceCollectionId,
    command: {
      ...(context?.commandId ? { command_id: context.commandId } : {}),
      ...(context?.workflowId ? { workflow_id: context.workflowId } : {}),
      ...(context?.runId ? { run_id: context.runId } : {}),
    },
  }
}
