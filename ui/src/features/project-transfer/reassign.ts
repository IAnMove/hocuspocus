import type { ApiOutput } from '../../api/outputs'
import type { PackedAsset, PreflightReport } from './preflight.ts'

export type ReassignEntry = {
  sha256: string
  filename: string
  workspace: string
  url?: string
  assetId?: string
}

export function repairAssets(report: PreflightReport): PackedAsset[] {
  return report.assets.filter(asset => asset.status === 'missing' || asset.status === 'tampered')
}

export function pickerToReassign(sha256: string, item: ApiOutput, workspace: string): ReassignEntry {
  return {
    sha256,
    filename: item.name,
    workspace: item.workspace_id || workspace,
    url: item.url,
    assetId: item.asset_id,
  }
}

export function encodeReassign(entries: ReassignEntry[]): string {
  return JSON.stringify(entries)
}

export function blockingIssue(report: PreflightReport): string | undefined {
  const codes = new Set(['cinema_extension', 'external_link', 'invalid_document', 'template', 'traversal', 'unsupported_kind', 'unsupported_version', 'too_large'])
  return report.issues.find(issue => codes.has(issue.code))?.code
}

export function canImport(report: PreflightReport, reassigned: Iterable<string>): boolean {
  if (blockingIssue(report)) return false
  const done = new Set(reassigned)
  return repairAssets(report).every(asset => done.has(asset.sha256))
}
