import type { AgentAction, AgentGenerateStoryVisualsAction, AgentTurn } from './agentActions'

const normalize = (value: string) => value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase()
const command = /\b(?:genera(?:me|d)?|dibuja(?:me|d)?|lanza(?:d)?|renderiza|generate|draw|render|launch)\b/
const createArtwork = /\b(?:crea(?:me|d)?|create)\s+(?:(?:ahora|now|una?|unas?|unos?|las?|los?|el|a|an|the|some)\s+)*(?:imagen(?:es)?|images?|artwork|visual(?:es|s)?|retratos?|portraits?)\b/
const negative = /\b(?:no|sin|not|never|don't|dont|nunca)\b/
const imageWords = /\b(?:imagen(?:es)?|image(?:s)?|artwork|visual(?:es|s)?|concept(?:os|s)?|personaje(?:s)?|character(?:s)?|localizacion(?:es)?|location(?:s)?|portrait|retrato)\b/
const storyContext = /\b(?:story\s*lab|generate_story_visuals)\b/
export const isComicVisualContext = (request: string) => /\b(?:comics?|vinetas?|comic\s+panels?)\b/.test(normalize(request))
const question = /^(?:[¿\s]*)(?:como|how|donde|where|que\s+(?:modelo|proveedor)|what\s+(?:model|provider))\b/
const allTargets = /\b(?:todos|todas|all|every)\b/
const scopeWords = {
  characters: /\b(?:personajes?|characters?|retratos?|portraits?)\b/,
  locations: /\b(?:localizacion(?:es)?|locations?|fondos?|backgrounds?)\b/,
  world: /\b(?:mundo|world)\b/,
  all: /\b(?:todo|toda|todos|todas|all|every)\b/,
}

const clausesOf = (request: string) => normalize(request)
  .split(/[.!?;\n]+|\b(?:pero|but|excepto|except)\b|\b(?:y|and)\s+(?=no\b|not\b|don't\b)/)
  .map(clause => clause.trim()).filter(Boolean)

function mentions(clause: string, value: string): boolean {
  const words = (text: string) => ` ${normalize(text).replace(/[^a-z0-9]+/g, ' ').trim()} `
  return Boolean(value.trim()) && words(clause).includes(words(value))
}

function negatesAction(clause: string, action: AgentGenerateStoryVisualsAction): boolean {
  // A broad action carries no inventory to subtract a prohibited target from.
  // Require a narrower plan instead of guessing which unnamed targets remain.
  if (!action.targetNames.length) return true
  if (action.targetNames.some(name => mentions(clause, name))) return true
  if (/\b(?:nada|nothing|ningun(?:a)?|ningun(?:as|os))\b/.test(clause)) return true
  if (scopeWords[action.scope].test(clause)) return true
  // A restriction naming another target/domain does not revoke permission for
  // the requested target. Unspecific image prohibitions remain fail-closed.
  const otherScope = Object.values(scopeWords).some(pattern => pattern.test(clause))
  return !otherScope && /\b(?:imagenes|images|artwork|generacion|generation)\b/.test(clause)
}

function explicitlyRequested(action: AgentGenerateStoryVisualsAction, positives: string[]): boolean {
  if (!action.confirm || !positives.length) return false
  if (action.targetNames.length) {
    return action.targetNames.every(name => positives.some(clause => mentions(clause, name)
      || (allTargets.test(clause) && scopeWords[action.scope].test(clause))))
  }
  return positives.some(clause => scopeWords[action.scope].test(clause)
    && (action.scope === 'world' || allTargets.test(clause)))
}

/** Preserve the planned Story target instead of rewriting it as Studio/Flux.
 * This intentionally handles only explicit Story artwork requests. It never
 * invents targets or changes a provider; the saved Story override owns routing.
 */
export function reconcileStoryVisualRequest(request: string, turn: AgentTurn): AgentTurn | undefined {
  const text = normalize(request)
  const planned = turn.actions.filter((action): action is AgentGenerateStoryVisualsAction => action.type === 'generate_story_visuals')
  if (isComicVisualContext(request)) return undefined
  const scopedImageRequest = storyContext.test(text) && imageWords.test(text)
  const remoteImageRequest = clausesOf(request).some(clause => /\bminimax(?:[ -]image)?\b/.test(clause) && !negative.test(clause)) && imageWords.test(text)
  if (!planned.length && !scopedImageRequest && !remoteImageRequest) return undefined
  // Creating/editing a Story inventory is not itself an artwork request.
  if (!planned.length && turn.actions.some(action => !['prepare_image', 'start_generation', 'open_tab'].includes(action.type))) return undefined
  const clauses = clausesOf(request)
  const prohibitions = clauses.filter(clause => negative.test(clause))
  const positives = clauses.filter(clause => !negative.test(clause) && !question.test(clause)
    && (command.test(clause) || createArtwork.test(clause)) && imageWords.test(clause))
  if (!turn.actions.length && !positives.length) return turn
  const visualActions = planned.filter(action => explicitlyRequested(action, positives)
    && !prohibitions.some(clause => negatesAction(clause, action)))
  const actions: AgentAction[] = turn.actions.filter(action => action.type === 'generate_story_visuals'
    ? visualActions.includes(action)
    : ['create_story', 'update_story', 'open_story_section', 'open_tab'].includes(action.type))
  if (!actions.length) {
    return { ...turn, reply: 'I have not launched images. The request needs a Story Lab action with a confirmed scope and names; I won\'t replace it with a local Studio generation.', actions: [] }
  }
  return {
    ...turn,
    reply: 'I\'ll send the requested images to Story Lab with their exact names and the provider saved in that project. The real result will appear after each action runs.',
    actions,
  }
}
