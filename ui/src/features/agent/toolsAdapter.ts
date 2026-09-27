import { useStore } from '../../stores/useStore'
import * as api from '../../api/client'
import i18n from '../../i18n'
import type { AdapterOutcome, ToolsAdapter } from './applicationAdapters'
import type { AgentRemoveBackgroundAction, AgentUpscaleAction } from './agentActions'
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
  kind?: 'image' | 'video'
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

function fileUrlQueryWorkspace(source: string | undefined): string | undefined {
  const raw = (source || '').trim()
  const path = raw.split(/[?#]/, 1)[0]
  let decoded = path
  try {
    decoded = decodeURIComponent(path)
  } catch {
    decoded = path
  }
  if (!raw || !decoded.startsWith('/api/v1/file/')) return undefined
  try {
    return new URL(raw, 'http://local.invalid').searchParams.get('workspace')?.trim() || undefined
  } catch {
    return undefined
  }
}

function explicitSourceWorkspace(action: { sourceWorkspace?: string; source?: string }): string | undefined {
  return action.sourceWorkspace?.trim() || fileUrlQueryWorkspace(action.source)
}

async function resolveSource(
  action: AgentRemoveBackgroundAction,
  workspace: string,
): Promise<ResolvedSource> {
  const assetId = action.assetId?.trim() || undefined
  const assetSource = await loadAssetSource(assetId, explicitSourceWorkspace(action), workspace)
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
  const sourceWorkspace = explicitSourceWorkspace(action) || assetSource?.sourceWorkspace
  const kind = assetSource?.asset.kind === 'video' || /\.(?:mp4|webm|mov|mkv|avi|m4v|mpeg|mpg|wmv)$/i.test(sourceBasename(source)) ? 'video' : 'image'
  return { source, name, url: sourceUrl(source, sourceWorkspace, workspace), assetId, sourceWorkspace, kind }
}

async function resolveAssetSource(
  assetId: string,
  preferredWorkspace: string | undefined,
  workspace: string,
): Promise<{ asset: api.AssetCatalogItem; source: string; sourceWorkspace: string }> {
  const asset = await api.fetchAsset(assetId)
  if (asset.kind !== 'image' && asset.kind !== 'video') throw new Error(i18n.t('removeBackgroundInvalidAsset', { ns: 'wizard' }))
  const location = asset.locations.find(item => item.workspace_id === preferredWorkspace)
    || asset.locations.find(item => item.workspace_id === workspace)
    || asset.locations[0]
  if (!location) throw new Error(i18n.t('removeBackgroundNoLocation', { ns: 'wizard' }))
  return { asset, source: location.filename, sourceWorkspace: location.workspace_id }
}

function target(taskId: string): AgentExecutionTarget {
  return { kind: 'tool_job', id: taskId, title: i18n.t('removeBackgroundTitle', { ns: 'wizard' }) }
}

function upscaleTarget(taskId: string): AgentExecutionTarget {
  return { kind: 'tool_job', id: taskId, title: i18n.t('upscaleTitle', { ns: 'wizard' }) }
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
    async upscale(action, context?: GenerationSubmissionContext) {
      const workspace = useStore.getState().activeWorkspace || 'default'
      const source = await resolveUpscaleSource(action, workspace)
      assertUpscaleWorkspace(workspace)
      await showUpscaleSource(navigate, source, action, workspace)
      assertUpscaleWorkspace(workspace)
      const state = useStore.getState()
      const { prepareStudioToolsUpscaleSubmission, toolsUpscaleParamsFromState } =
        await import('../studio/toolsCommandSubmission')
      const params = toolsUpscaleParamsFromState(state)
      if (context?.workspaceCollectionId) {
        params.provenance = { workspace_id: context.workspaceCollectionId }
      }
      const submission = await prepareStudioToolsUpscaleSubmission(
        params,
        state,
        () => useStore.getState(),
        context || { actor: 'wizard', capability: 'tools.upscale' },
      )
      const result = await submission.submit()
      const taskId = result.task_id || result.job_id
      const message = i18n.t('upscaleQueued', {
        ns: 'wizard', name: source.name, kind: action.sourceKind,
      })
      const jobTarget = upscaleTarget(taskId)
      const report = executionReport({
        state: 'queued', message, target: jobTarget, taskId, recoverable: true,
        executionKey: executionKey({ workspace, type: action.type, targetId: source.assetId || source.source, params: action }),
      })
      rememberExecution(report)
      return {
        message, target: jobTarget, taskId, report,
        metadata: {
          tool: 'upscale', sourceAssetId: source.assetId || null,
          source: source.source, sourceWorkspace: source.sourceWorkspace || workspace,
          sourceKind: source.kind, method: action.method,
        },
      }
    },
  }
}

function assertUpscaleWorkspace(workspace: string): void {
  const currentWorkspace = useStore.getState().activeWorkspace || 'default'
  if (currentWorkspace !== workspace) {
    throw new Error(i18n.t('upscaleWorkspaceChanged', { ns: 'wizard' }))
  }
}

async function showSource(navigate: Navigate, source: ResolvedSource): Promise<void> {
  await navigate('studio')
  const state = useStore.getState()
  state.setGenerationMode('tools')
  state.setToolsTool('remove_background')
  state.setToolsSource({
    path: source.source, name: source.name, url: source.url,
    assetId: source.assetId || null, workspace: source.sourceWorkspace || null, kind: source.kind || 'image',
  })
}

async function showUpscaleSource(
  navigate: Navigate,
  source: ResolvedSource,
  action: AgentUpscaleAction,
  expectedWorkspace: string,
): Promise<void> {
  await navigate('studio')
  // Navigation can suspend while the user changes workspace. Check before
  // writing any Tools controls so a late adapter result cannot overwrite the
  // newly selected workspace's form.
  assertUpscaleWorkspace(expectedWorkspace)
  const state = useStore.getState()
  state.setGenerationMode('tools')
  state.setToolsTool('upscale')
  state.setToolsUpscaleMethod(action.method)
  state.setParams({
    seed: action.seed ?? -1,
    wangp_processor_settings: action.wangpProcessorSettings ?? undefined,
  })
  state.setToolsSource({
    path: source.assetId || source.source,
    name: source.name,
    url: source.url,
    assetId: source.assetId || null,
    workspace: source.sourceWorkspace || null,
    kind: source.kind || null,
  })
}

type AssetSource = {
  asset: api.AssetCatalogItem
  source: string
  sourceWorkspace: string
  url: string
}

async function resolveUpscaleSource(
  action: AgentUpscaleAction,
  workspace: string,
): Promise<ResolvedSource> {
  const { canonicalToolsSource } = await import('../studio/toolsSource')
  const assetId = action.assetId?.trim() || undefined
  const assetSource = assetId
    ? await resolveUpscaleAssetSource(assetId, action, explicitSourceWorkspace(action), workspace)
    : undefined
  const rawSource = action.source?.trim() || ''
  if (!assetId && !rawSource) throw new Error(i18n.t('upscaleMissingSource', { ns: 'wizard' }))
  const source = assetId || canonicalToolsSource(
    rawSource,
    rawSource.startsWith('/api/') || rawSource.startsWith('asset') ? rawSource : undefined,
    explicitSourceWorkspace(action),
    workspace,
  )
  const sourceUrl = assetSource
    ? canonicalToolsSource(assetSource.source, assetSource.url, assetSource.sourceWorkspace, workspace)
    : source
  return {
    source,
    name: assetSource?.asset.filename || sourceBasename(rawSource || source),
    url: sourceUrl,
    assetId,
    sourceWorkspace: explicitSourceWorkspace(action) || assetSource?.sourceWorkspace,
    kind: action.sourceKind,
  }
}

async function resolveUpscaleAssetSource(
  assetId: string,
  action: AgentUpscaleAction,
  preferredWorkspace: string | undefined,
  workspace: string,
): Promise<AssetSource> {
  const asset = await api.fetchAsset(assetId)
  if (asset.kind !== action.sourceKind) {
    throw new Error(i18n.t('upscaleInvalidAsset', { ns: 'wizard', kind: action.sourceKind }))
  }
  const location = preferredWorkspace
    ? asset.locations.find(item => item.workspace_id === preferredWorkspace)
    : asset.locations.find(item => item.workspace_id === workspace)
  if (preferredWorkspace && !location) {
    throw new Error(i18n.t('upscaleSourceWorkspaceUnavailable', { ns: 'wizard', workspace: preferredWorkspace }))
  }
  if (!preferredWorkspace && !location && asset.locations.length > 1) {
    throw new Error(i18n.t('upscaleSourceWorkspaceRequired', { ns: 'wizard' }))
  }
  const selected = location || asset.locations[0]
  if (!selected) throw new Error(i18n.t('upscaleNoLocation', { ns: 'wizard' }))
  return { asset, source: selected.filename, sourceWorkspace: selected.workspace_id, url: selected.url }
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
