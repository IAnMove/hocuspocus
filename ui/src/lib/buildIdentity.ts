import type { AboutInfo } from '../api/about'

/** Commit baked into this JavaScript bundle by scripts/build_ui.py (empty for plain npm builds). */
export const BUNDLE_COMMIT: string = String(import.meta.env?.VITE_HOCUS_BUILD_COMMIT ?? '')

export type BuildState = 'in-sync' | 'reload' | 'rebuild' | 'unknown'

export function shortCommit(commit?: string | null): string {
  return commit && /^[0-9a-f]{7,40}$/i.test(commit) ? commit.slice(0, 7) : ''
}

/**
 * - reload: this tab runs an older bundle than the one the server now serves.
 * - rebuild: the served UI was built from a different commit than the running backend.
 */
type Identity = { backend?: { commit?: string }; ui?: { commit?: string } }

export function buildState(about: Pick<AboutInfo, 'backend' | 'ui'> | Identity | null, bundle = BUNDLE_COMMIT): BuildState {
  const backend = about?.backend?.commit
  const ui = about?.ui?.commit
  if (!about || !backend || backend === 'unknown') return 'unknown'
  if (bundle && ui && bundle !== ui) return 'reload'
  if (ui && ui !== backend) return 'rebuild'
  if (bundle && bundle !== backend) return 'reload'
  return ui || bundle ? 'in-sync' : 'unknown'
}

export function commitUrl(repository: string, commit?: string | null): string | null {
  return shortCommit(commit) ? `${repository.replace(/\/$/, '')}/commit/${commit}` : null
}
