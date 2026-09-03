import { BASE } from './http'

function storedAssetFilename(pathOrFilename: string): string {
  const normalized = String(pathOrFilename || '').replace(/\\/g, '/')
  const withoutQuery = normalized.split(/[?#]/, 1)[0]
  const encodedName = withoutQuery.split('/').pop() || ''
  try {
    return decodeURIComponent(encodedName)
  } catch {
    return encodedName
  }
}

export interface ApiOutput {
  name: string
  type: 'video' | 'image' | 'audio' | 'model3d' | 'scene' | 'comic'
  mode: string | null
  favorite?: boolean
  size: number
  created_at: number
  /** Time the generated asset was fully published. Older/imported assets
   *  fall back to the media file's modification time. */
  completed_at?: number
  completion_time_source?: 'metadata' | 'file'
  url: string
  /** Small static preview for image/video cards and saved 3D/scene assets. */
  thumbnail_url?: string | null
  /** Edit-mode sub-classification (retake / inpaint / outpaint / restyle /
   *  edit_anything). Field added as a recovery stub after a git
   *  filter-repo reset wiped the original Stream C/D work that
   *  introduced it. Optional so the type compiles even when the
   *  backend hasn't been updated to emit this yet. */
  edit_sub_mode?: string | null
  result_kind?: 'music_video' | 'trailer' | 'series_episode' | 'chapter' | null
}

// --- Move to Workspace ---

export async function moveOutput(name: string, workspace: string): Promise<void> {
  const res = await fetch(`${BASE}/api/v1/outputs/${encodeURIComponent(name)}/move`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Move failed' }))
    throw new Error(err.detail || 'Move failed')
  }
}

// --- Favorites ---

export async function toggleFavorite(name: string): Promise<{ name: string; favorite: boolean }> {
  const res = await fetch(`${BASE}/api/v1/favorites/${encodeURIComponent(name)}`, { method: 'POST' })
  if (!res.ok) throw new Error('Failed to toggle favorite')
  return res.json()
}

// --- Outputs ---

export async function fetchOutputs(limit = 0, offset = 0, opts?: { favoritesOnly?: boolean; multiclipOnly?: boolean; editsOnly?: boolean; search?: string; workspace?: string; mediaType?: ApiOutput['type']; resultKind?: ApiOutput['result_kind']; signal?: AbortSignal }): Promise<{ outputs: ApiOutput[]; total: number }> {
  const params = new URLSearchParams()
  if (limit > 0) params.set('limit', String(limit))
  if (offset > 0) params.set('offset', String(offset))
  if (opts?.favoritesOnly) params.set('favorites_only', 'true')
  if (opts?.multiclipOnly) params.set('multiclip_only', 'true')
  if (opts?.editsOnly) params.set('edits_only', 'true')
  if (opts?.resultKind) params.set('result_kind', opts.resultKind)
  if (opts?.search) params.set('search', opts.search)
  // "__uploads__" browses the uploads folder (virtual Uploads view)
  if (opts?.workspace) params.set('workspace', opts.workspace)
  if (opts?.mediaType) params.set('media_type', opts.mediaType)
  const qs = params.toString()
  const res = await fetch(`${BASE}/api/v1/outputs${qs ? '?' + qs : ''}`, { cache: 'no-store', signal: opts?.signal })
  if (!res.ok) throw new Error('Failed to fetch outputs')
  const data = await res.json()
  return { outputs: data.outputs, total: data.total ?? data.outputs.length }
}

export function getFileUrl(filename: string, workspace?: string): string {
  const query = workspace ? `?workspace=${encodeURIComponent(workspace)}` : ''
  return `${BASE}/api/v1/file/${encodeURIComponent(filename)}${query}`
}

/** Convert persisted media references into a URL the browser can actually play.
 * Older/local generation responses contain an absolute filesystem path. That
 * path is useful to the backend but is not an HTTP route, so use the canonical
 * workspace file endpoint and the separately persisted filename instead.
 */

export function getPlayableFileUrl(source: string, filename: string, workspace?: string): string {
  const value = String(source || '').trim()
  if (/^(?:https?:|blob:|data:)/i.test(value) || value.startsWith('/api/')) return value
  if (!value || value.startsWith('/') || /^[a-zA-Z]:[\\/]/.test(value)) {
    return getFileUrl(filename, workspace)
  }
  return value
}

/** The name the backend can resolve on its own for media it already holds,
 *  or null when the media exists only in the browser (blob:/data:) or on
 *  another host. The mirror of getPlayableFileUrl: that one answers "how does
 *  this play in the page", this one answers "can the server open it itself",
 *  so a caller can hand over a name instead of shipping the bytes to the
 *  browser and straight back. The workspace goes with it, because the server
 *  confines every media path to uploads plus one workspace root.
 */
export function getServerMediaReference(
  source: string,
  filename: string,
  workspace?: string,
): { audio_path: string; workspace?: string } | null {
  const value = String(source || '').trim()
  if (/^(?:https?:|blob:|data:)/i.test(value)) return null
  if (value.startsWith('/api/')) {
    // The two roots the backend resolves a relative name against. An upload
    // keeps its subfolder ("audio/x.wav") because the root is uploads/, not
    // uploads/audio/; a workspace file is a flat name in its folder.
    const upload = /^\/api\/v1\/uploads\/([^?#]+)/.exec(value)
    if (upload) return { audio_path: upload[1].split('/').map(decodeURIComponent).join('/') }
    const stored = /^\/api\/v1\/file\/([^/?#]+)/.exec(value)
    if (!stored) return null
    const query = new URLSearchParams(value.slice(value.indexOf('?') + 1))
    const named = (value.includes('?') && query.get('workspace')) || workspace
    return { audio_path: decodeURIComponent(stored[1]), ...(named ? { workspace: named } : {}) }
  }
  // Empty, absolute POSIX or Windows paths: persisted filesystem locations
  // whose canonical HTTP form is the workspace file endpoint for `filename`.
  if (!value || value.startsWith('/') || /^[a-zA-Z]:[\\/]/.test(value)) {
    if (!filename) return null
    return { audio_path: filename, ...(workspace ? { workspace } : {}) }
  }
  return null
}

export function getOutputThumbnailUrl(filename: string, workspace?: string): string {
  const query = workspace ? `?workspace=${encodeURIComponent(workspace)}` : ''
  return `${BASE}/api/v1/outputs/thumbnail/${encodeURIComponent(filename)}${query}`
}

export function getUploadUrl(filename: string): string {
  return `${BASE}/api/v1/uploads/${encodeURIComponent(filename)}`
}

export function getStoredAssetUrl(pathOrFilename: string): string {
  const normalized = String(pathOrFilename || '').replace(/\\/g, '/')
  const filename = storedAssetFilename(normalized)
  const isUpload = normalized.startsWith('/api/v1/uploads/')
    || /(^|\/)uploads\//i.test(normalized)
  return isUpload ? getUploadUrl(filename) : getFileUrl(filename)
}

/**
 * Fetch a stored asset with a compatibility fallback for old sidecars that
 * persisted only a basename and therefore lost whether it came from uploads
 * or outputs.
 */

export async function fetchStoredAsset(pathOrFilename: string): Promise<Response> {
  const filename = storedAssetFilename(pathOrFilename)
  const primary = getStoredAssetUrl(pathOrFilename)
  const fallback = primary === getFileUrl(filename)
    ? getUploadUrl(filename)
    : getFileUrl(filename)
  const first = await fetch(primary)
  if (first.ok || primary === fallback) return first
  return fetch(fallback)
}

export async function fetchOutputMetadata(
  name: string,
  workspace?: string,
  signal?: AbortSignal,
): Promise<import('../types').OutputMetadata> {
  // Retry with a per-attempt timeout. On a slow/high-latency link (e.g. the user
  // is remote over VPN) the request can stall long enough that a single attempt
  // hangs or is dropped by an intermediary; the old single-shot fetch then left
  // the caller with no metadata and the "Load Settings" button a silent no-op.
  const workspaceQuery = workspace
    ? `?workspace=${encodeURIComponent(workspace)}`
    : ''
  const url = `${BASE}/api/v1/outputs/${encodeURIComponent(name)}/metadata${workspaceQuery}`
  const ATTEMPTS = 3
  const PER_ATTEMPT_MS = 30000  // generous: the server may read embedded video metadata to recover a seed
  let lastErr: unknown = null
  for (let attempt = 0; attempt < ATTEMPTS; attempt++) {
    if (signal?.aborted) throw new DOMException('Metadata request aborted', 'AbortError')
    const controller = new AbortController()
    const abortFromCaller = () => controller.abort()
    signal?.addEventListener('abort', abortFromCaller, { once: true })
    const timer = setTimeout(() => controller.abort(), PER_ATTEMPT_MS)
    try {
      const res = await fetch(url, { signal: controller.signal })
      if (!res.ok) return { source: 'none', params: null }
      return await res.json()
    } catch (e) {
      lastErr = e
      if (signal?.aborted) throw e
      // Diagnostic: AbortError = our per-attempt timeout fired (link too slow);
      // TypeError = network failure / dropped connection. Helps pinpoint a
      // "Load Settings does nothing over VPN" report.
      console.warn(`[LoadSettings] fetchOutputMetadata attempt ${attempt + 1}/${ATTEMPTS} failed:`,
                   (e as { name?: string })?.name || e)
      if (attempt < ATTEMPTS - 1) {
        await new Promise(r => setTimeout(r, 400 * (attempt + 1)))  // brief backoff before retry
      }
    } finally {
      clearTimeout(timer)
      signal?.removeEventListener('abort', abortFromCaller)
    }
  }
  throw lastErr  // all attempts failed — loadOutputMetadata's catch sets meta null
}

export async function fetchVideoExtraInfo(
  name: string,
  language: string,
): Promise<import('../types').VideoExtraInfoStatus> {
  const res = await fetch(
    `${BASE}/api/v1/outputs/${encodeURIComponent(name)}/extra-info?language=${encodeURIComponent(language)}`,
    { cache: 'no-store' },
  )
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Failed to load extra info' }))
    throw new Error(error.detail || 'Failed to load extra info')
  }
  return res.json()
}

export async function generateVideoExtraInfo(
  name: string,
  language: string,
  regenerate = false,
): Promise<{ cached: boolean; data: import('../types').VideoExtraInfo }> {
  const res = await fetch(`${BASE}/api/v1/outputs/${encodeURIComponent(name)}/extra-info`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ language, regenerate }),
  })
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Failed to generate extra info' }))
    throw new Error(error.detail || 'Failed to generate extra info')
  }
  return res.json()
}

export interface AlternativeSong {
  id: string
  audio_name: string
  duration_seconds: number
  created_at: number
  status: 'attached' | 'mounting' | 'mounted' | 'failed' | string
  mounted_output: string | null
  job_id: string | null
  extra_clip_count: number
  planned_clip_count: number
}

export interface AlternativeSongList {
  parent: string
  duration_seconds: number
  source_clip_count: number
  adaptation: 'random_extras' | 'loop_assembled' | string
  songs: AlternativeSong[]
  song?: AlternativeSong
}

export async function fetchAlternativeSongs(name: string, workspace?: string): Promise<AlternativeSongList> {
  const query = workspace ? `?workspace=${encodeURIComponent(workspace)}` : ''
  const res = await fetch(`${BASE}/api/v1/outputs/${encodeURIComponent(name)}/alternative-songs${query}`)
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Could not read alternative songs' }))
    throw new Error(error.detail || 'Could not read alternative songs')
  }
  return res.json()
}

export async function attachAlternativeSong(
  name: string,
  audioName: string,
  workspace?: string,
): Promise<AlternativeSongList> {
  const res = await fetch(`${BASE}/api/v1/outputs/${encodeURIComponent(name)}/alternative-songs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ audio_name: audioName, workspace }),
  })
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Could not attach the song' }))
    throw new Error(error.detail || 'Could not attach the song')
  }
  return res.json()
}

export async function deleteAlternativeSong(name: string, songId: string, workspace?: string): Promise<void> {
  const query = workspace ? `?workspace=${encodeURIComponent(workspace)}` : ''
  const res = await fetch(
    `${BASE}/api/v1/outputs/${encodeURIComponent(name)}/alternative-songs/${encodeURIComponent(songId)}${query}`,
    { method: 'DELETE' },
  )
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Could not remove the song' }))
    throw new Error(error.detail || 'Could not remove the song')
  }
}

export async function mountAlternativeSong(
  name: string,
  songId: string,
  details?: { audioName?: string; workspace?: string; seed?: number },
): Promise<{ job_id: string; task_id?: string; status: string; song: AlternativeSong; output_name: string }> {
  const res = await fetch(
    `${BASE}/api/v1/outputs/${encodeURIComponent(name)}/alternative-songs/${encodeURIComponent(songId)}/mount`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        audio_name: details?.audioName,
        workspace: details?.workspace,
        seed: details?.seed,
      }),
    },
  )
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Could not remount the videoclip' }))
    throw new Error(error.detail || 'Could not remount the videoclip')
  }
  return res.json()
}

export async function deleteOutput(name: string): Promise<void> {
  const res = await fetch(`${BASE}/api/v1/outputs/${encodeURIComponent(name)}`, { method: 'DELETE' })
  if (!res.ok) throw new Error('Failed to delete output')
}

export async function rejoinClips(groupId: string, audioFile?: string): Promise<{ filename: string; clip_count: number }> {
  const res = await fetch(`${BASE}/api/v1/outputs/rejoin`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ group_id: groupId, audio_file: audioFile }),
  })
  if (!res.ok) throw new Error('Failed to rejoin clips')
  return res.json()
}

export async function fetchGroupClips(groupId: string): Promise<{ group_id: string; clips: Array<{ filename: string; index: number; total: number; prompt: string }> }> {
  const res = await fetch(`${BASE}/api/v1/outputs/group/${encodeURIComponent(groupId)}`)
  if (!res.ok) throw new Error('Failed to fetch group clips')
  return res.json()
}
