import { parseArchitectureGraph, type ArchitectureGraph } from './architectureSchema'

const BASE_URL = import.meta.env?.BASE_URL || '/'
export const ARCHITECTURE_GRAPH_URL = `${BASE_URL}dev/architecture/story-director-audio.json`
const MAX_GRAPH_BYTES = 2 * 1024 * 1024

async function readBoundedBody(response: Response): Promise<string> {
  const reader = response.body?.getReader()
  if (!reader) throw new Error('Architecture map has no response body')
  const decoder = new TextDecoder()
  let bytes = 0
  let text = ''
  try {
    while (true) {
      const chunk = await reader.read()
      if (chunk.done) return text + decoder.decode()
      bytes += chunk.value.byteLength
      if (bytes > MAX_GRAPH_BYTES) {
        await reader.cancel()
        throw new Error('Architecture map is too large')
      }
      text += decoder.decode(chunk.value, { stream: true })
    }
  } finally {
    reader.releaseLock()
  }
}

export async function loadArchitectureGraph(fetcher: typeof fetch = fetch): Promise<ArchitectureGraph> {
  const response = await fetcher(ARCHITECTURE_GRAPH_URL, {
    headers: { Accept: 'application/json' },
    cache: 'no-store',
  })
  if (!response.ok) {
    throw new Error(`Architecture map unavailable (${response.status})`)
  }
  const declaredLength = response.headers.get('content-length')
  if (declaredLength && Number(declaredLength) > MAX_GRAPH_BYTES) {
    throw new Error('Architecture map is too large')
  }
  const body = await readBoundedBody(response)
  let payload: unknown
  try {
    payload = JSON.parse(body) as unknown
  } catch {
    throw new Error('Architecture map returned invalid JSON')
  }
  return parseArchitectureGraph(payload)
}
