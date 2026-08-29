export type AgentStorySection = 'overview' | 'world' | 'characters' | 'relationships' | 'structure' | 'productions'
export type AgentSeriesSection = 'setup' | 'canon' | 'episode' | 'shots' | 'review'

const STORY_SECTION_EVENT = 'hocuspocus:story-section'
const SERIES_SECTION_EVENT = 'hocuspocus:series-section'
let requestedStorySection: AgentStorySection | null = null
let requestedSeriesSection: AgentSeriesSection | null = null

export function openAgentStorySection(section: AgentStorySection): void {
  requestedStorySection = section
  window.dispatchEvent(new CustomEvent(STORY_SECTION_EVENT, { detail: { section } }))
}

export function openAgentSeriesSection(section: AgentSeriesSection): void {
  requestedSeriesSection = section
  window.dispatchEvent(new CustomEvent(SERIES_SECTION_EVENT, { detail: { section } }))
}

export function listenForAgentStorySection(
  listener: (section: AgentStorySection) => void,
): () => void {
  const handler = (event: Event) => {
    const section = (event as CustomEvent<{ section?: AgentStorySection }>).detail?.section
    if (section) listener(section)
  }
  window.addEventListener(STORY_SECTION_EVENT, handler)
  if (requestedStorySection) listener(requestedStorySection)
  return () => window.removeEventListener(STORY_SECTION_EVENT, handler)
}

export function listenForAgentSeriesSection(
  listener: (section: AgentSeriesSection) => void,
): () => void {
  const handler = (event: Event) => {
    const section = (event as CustomEvent<{ section?: AgentSeriesSection }>).detail?.section
    if (section) listener(section)
  }
  window.addEventListener(SERIES_SECTION_EVENT, handler)
  if (requestedSeriesSection) listener(requestedSeriesSection)
  return () => window.removeEventListener(SERIES_SECTION_EVENT, handler)
}
