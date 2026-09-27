import { BASE } from './http'

export interface SourceIdentity {
  commit?: string
  branch?: string
  dirty?: boolean | null
}

export interface AboutInfo {
  name: string
  version: string
  repository: string
  author: { x_handle: string; x_url: string }
  backend: SourceIdentity & { version: string; started_at: string }
  ui: SourceIdentity & { build_id?: string; built_at?: string }
  in_sync: boolean
  credits: Array<{ name: string; role: string }>
}

export async function fetchAbout(): Promise<AboutInfo> {
  const res = await fetch(`${BASE}/api/v1/about`)
  if (!res.ok) throw new Error('about failed')
  return res.json()
}
