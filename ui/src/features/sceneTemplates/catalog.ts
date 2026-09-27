/**
 * Candidate-only scene templates for the Video3D review gallery.
 *
 * This registry is deliberately separate from `sceneNarrative.ts`: adding a
 * candidate here must not add it to the recipe grammar or to the approved
 * narrative-template selector. A candidate can be previewed and opened in
 * the editor while it remains explicitly unapproved.
 */

import { MUSIC_MOTION_TEMPLATES } from './musicMotionCatalog'

export const CATALOG_VERSION = '2026-09-review-1' as const
export const EXPANDED_CATALOG_VERSION = '2026-09-music-motion-1' as const

export type TemplateFamily = 'cinema' | 'music' | 'space'

export type TemplateSlotName = 'hero' | 'plate' | 'prop' | 'foreground' | 'subject_1' | 'subject_2' | 'background' | 'prop_1'

export type SceneTemplateSlot = {
  readonly id: TemplateSlotName
  readonly required: boolean
  readonly kinds: readonly ('image' | 'model3d')[]
  readonly description: string
}

export type SceneTemplateDefinition = {
  readonly id: string
  readonly version: 1
  readonly status: 'candidate'
  readonly family: TemplateFamily
  readonly title: string
  readonly description: string
  readonly slots: readonly SceneTemplateSlot[]
  readonly limits: readonly string[]
  readonly promptExample: string
  readonly defaultDuration: number
  readonly motionIntensity?: 'moderate' | 'high'
  readonly rhythmic?: boolean
}

const IMAGE = ['image'] as const
const IMAGE_OR_MODEL3D = ['image', 'model3d'] as const
const MODEL3D = ['model3d'] as const

const COMMON_LIMITS = [
  'Máximo 2 GLB, sin repeticiones.',
  'Usa únicamente assets proporcionados.',
  'Sin vídeo generado por IA.',
  'Sin diálogo incluido.',
  'El BPM no implica música ni audio real en previews.',
] as const

const CINEMA_LIMITS = [
  'Cine en 2.5D; solo el objeto GLB aporta profundidad.',
  ...COMMON_LIMITS,
] as const

const MUSIC_LIMITS = [
  'Música en 2.5D; solo el objeto GLB aporta profundidad.',
  ...COMMON_LIMITS,
] as const

const SPACE_LIMITS = [
  'Espacio compuesto por capas GLB; sin física, colisiones ni oclusión global.',
  ...COMMON_LIMITS,
] as const

const SPACE_ORBIT_LIMITS = [
  ...SPACE_LIMITS,
  'La órbita es una relación de capas: no crea oclusión global aunque los objetos permanezcan en la misma capa de composición.',
] as const

type PropSlot = {
  required: boolean
  kinds: readonly ('image' | 'model3d')[]
  description: string
}

const makeSlots = (
  hero: string,
  plate: string,
  foreground: string,
  prop?: PropSlot,
  heroKinds: readonly ('image' | 'model3d')[] = IMAGE_OR_MODEL3D,
): readonly SceneTemplateSlot[] => [
  {
    id: 'hero',
    required: true,
    kinds: heroKinds,
    description: hero,
  },
  {
    id: 'plate',
    required: true,
    kinds: IMAGE,
    description: plate,
  },
  ...(prop
    ? [{
        id: 'prop' as const,
        required: prop.required,
        kinds: prop.kinds,
        description: prop.description,
      }]
    : []),
  {
    id: 'foreground',
    required: false,
    kinds: IMAGE,
    description: foreground,
  },
]

const makeTemplate = (
  id: string,
  family: TemplateFamily,
  title: string,
  description: string,
  slots: readonly SceneTemplateSlot[],
  limits: readonly string[],
): SceneTemplateDefinition => ({
  id,
  version: 1,
  status: 'candidate',
  family,
  title,
  description,
  slots,
  limits,
  promptExample: `Usa la plantilla candidata "${id}" para crear un plano cinematográfico editable, respetando sus slots, límites y assets proporcionados.`,
  defaultDuration: 4,
})

const cinemaSlots = (
  hero: string,
  plate: string,
  foreground: string,
  prop?: PropSlot,
) => makeSlots(hero, plate, foreground, prop)

const musicSlots = (
  hero: string,
  plate: string,
  foreground: string,
  prop?: PropSlot,
) => makeSlots(hero, plate, foreground, prop)

const spaceSlots = (
  hero: string,
  plate: string,
  foreground: string,
  prop?: PropSlot,
) => makeSlots(hero, plate, foreground, prop, MODEL3D)

export const CANDIDATE_SCENE_TEMPLATES = [
  makeTemplate(
    'cinema-establishing',
    'cinema',
    'Plano de establecimiento',
    'Presenta sujeto y entorno con una entrada de cámara amplia y legible.',
    cinemaSlots(
      'Sujeto principal que fija la escala y el punto de atención del plano.',
      'Placa de entorno que sitúa la acción y admite un desplazamiento 2.5D.',
      'Capa visual opcional para crear profundidad en el primer término.',
    ),
    CINEMA_LIMITS,
  ),
  makeTemplate(
    'cinema-reveal',
    'cinema',
    'Revelado cinematográfico',
    'Descubre progresivamente al sujeto desde una placa con movimiento contenido.',
    cinemaSlots(
      'Sujeto que aparece tarde o queda parcialmente oculto al inicio del revelado.',
      'Placa que sostiene la entrada de cámara y el espacio antes de descubrir al sujeto.',
      'Capa opcional que puede ocultar y revelar el sujeto sin inventar una oclusión 3D.',
    ),
    CINEMA_LIMITS,
  ),
  makeTemplate(
    'cinema-closeup',
    'cinema',
    'Primer plano cinematográfico',
    'Concentra la mirada en un sujeto con escala cercana y movimiento mínimo.',
    cinemaSlots(
      'Sujeto principal preparado para una escala cercana y una lectura de detalle.',
      'Placa de fondo desenfatizada que conserva el contexto sin competir con el rostro u objeto.',
      'Textura o silueta opcional para suavizar el borde del primer plano.',
    ),
    CINEMA_LIMITS,
  ),
  makeTemplate(
    'cinema-two-shot',
    'cinema',
    'Doble plano cinematográfico',
    'Encuadra dos presencias en una composición de conversación o tensión compartida.',
    cinemaSlots(
      'Primer sujeto que ancla el eje y la escala de la conversación.',
      'Placa común que mantiene la continuidad espacial del encuadre.',
      'Elemento opcional de primer término para separar los dos sujetos.',
      {
        required: true,
        kinds: IMAGE_OR_MODEL3D,
        description: 'Segundo sujeto u objeto de interacción; completa el doble plano y acepta imagen o GLB.',
      },
    ),
    CINEMA_LIMITS,
  ),
  makeTemplate(
    'cinema-detail',
    'cinema',
    'Detalle cinematográfico',
    'Aísla una pista visual pequeña para convertirla en un beat narrativo claro.',
    cinemaSlots(
      'Objeto o gesto principal que debe permanecer legible en el detalle.',
      'Placa de apoyo que aporta escala y contraste al inserto.',
      'Borde, sombra o textura opcional que enmarca el detalle.',
    ),
    CINEMA_LIMITS,
  ),
  makeTemplate(
    'cinema-hero',
    'cinema',
    'Entrada de héroe',
    'Da al sujeto una entrada frontal con presencia y dirección cinematográfica.',
    cinemaSlots(
      'Héroe visual que recibe el movimiento de cámara y la mayor prioridad del plano.',
      'Placa que proporciona horizonte, contraste y dirección para la entrada.',
      'Capa opcional de partículas, marco o silueta para reforzar la escala.',
    ),
    CINEMA_LIMITS,
  ),
  makeTemplate(
    'cinema-isolation',
    'cinema',
    'Aislamiento cinematográfico',
    'Separa al sujeto del entorno mediante espacio negativo y un desplazamiento sobrio.',
    cinemaSlots(
      'Sujeto aislado que conserva una silueta clara contra el espacio negativo.',
      'Placa sencilla que deja aire alrededor del sujeto y evita competir con él.',
      'Capa opcional de velo o sombra para ampliar la sensación de aislamiento.',
    ),
    CINEMA_LIMITS,
  ),
  makeTemplate(
    'cinema-tracking',
    'cinema',
    'Seguimiento cinematográfico',
    'Acompaña al sujeto con una deriva lateral estable y una placa en continuidad.',
    cinemaSlots(
      'Sujeto que permanece centrado mientras el encuadre simula un seguimiento lateral.',
      'Placa desplazable que conserva el sentido de viaje sin generar un mundo 3D.',
      'Capa opcional que pasa cerca de cámara para subrayar el desplazamiento.',
    ),
    CINEMA_LIMITS,
  ),
  makeTemplate(
    'music-pulse',
    'music',
    'Pulso musical',
    'Convierte un pulso visual en cambios rítmicos de escala, contraste y desplazamiento.',
    musicSlots(
      'Sujeto principal que recibe pulsos de escala y pequeñas variaciones de energía.',
      'Placa con contraste suficiente para que el pulso sea visible sin audio generado.',
      'Textura o luz opcional que responde visualmente al pulso del plano.',
    ),
    MUSIC_LIMITS,
  ),
  makeTemplate(
    'music-duet',
    'music',
    'Dúo musical',
    'Alterna dos presencias en una composición de videoclip con respuesta visual compartida.',
    musicSlots(
      'Primera presencia que fija el eje y el ritmo base del dúo.',
      'Placa de escenario o entorno que sostiene la alternancia entre las presencias.',
      'Capa opcional de luz, humo gráfico o textura para unir ambas posiciones.',
      {
        required: true,
        kinds: IMAGE_OR_MODEL3D,
        description: 'Segunda presencia del dúo; acepta retrato, objeto o GLB proporcionado.',
      },
    ),
    MUSIC_LIMITS,
  ),
  makeTemplate(
    'music-chorus',
    'music',
    'Coro musical',
    'Amplía un gesto principal con una cadencia de capas y un encuadre de estribillo.',
    musicSlots(
      'Figura o motivo principal que lleva el gesto repetible del coro.',
      'Placa de escenario que admite cambios de escala y paralaje suave.',
      'Capa opcional de formas o luces que multiplica la sensación de coro.',
    ),
    MUSIC_LIMITS,
  ),
  makeTemplate(
    'music-orbit',
    'music',
    'Órbita musical',
    'Hace orbitar un accesorio alrededor del motivo principal mediante una relación de capa 2.5D.',
    musicSlots(
      'Motivo principal que permanece como centro del movimiento orbital de la capa prop.',
      'Placa que ofrece líneas de referencia para leer el giro sin geometría 3D global.',
      'Capa opcional que cruza el borde del cuadro y refuerza el movimiento orbital.',
      {
        required: true,
        kinds: IMAGE_OR_MODEL3D,
        description: 'Accesorio o segundo motivo que orbita al hero mediante keyframes; acepta imagen o GLB.',
      },
    ),
    MUSIC_LIMITS,
  ),
  makeTemplate(
    'music-parallax',
    'music',
    'Paralaje musical',
    'Construye profundidad rítmica mediante desplazamientos diferenciados de capas planas.',
    musicSlots(
      'Motivo principal que marca el ritmo visual sobre las capas de paralaje.',
      'Placa con textura o arquitectura suficiente para hacer visible el desplazamiento.',
      'Capa opcional cercana que amplía la separación entre planos.',
    ),
    MUSIC_LIMITS,
  ),
  makeTemplate(
    'music-stage',
    'music',
    'Escenario musical',
    'Coloca el motivo en un escenario gráfico preparado para una entrada de videoclip.',
    musicSlots(
      'Artista, objeto o motivo que ocupa el centro compositivo del escenario.',
      'Placa de escenario que define fondo, suelo visual y contraste del motivo.',
      'Capa opcional de telón, humo gráfico o luces de borde.',
    ),
    MUSIC_LIMITS,
  ),
  makeTemplate(
    'music-product',
    'music',
    'Producto musical',
    'Presenta un producto u objeto con energía de videoclip y un giro visual controlado.',
    musicSlots(
      'Producto o motivo principal que recibe el foco y el desplazamiento de cámara.',
      'Placa de estudio o escenario que conserva una lectura limpia del producto.',
      'Capa opcional de reflejo, textura o luz gráfica alrededor del objeto.',
      {
        required: false,
        kinds: IMAGE_OR_MODEL3D,
        description: 'Accesorio de marca o segundo objeto opcional; acepta imagen o GLB proporcionado.',
      },
    ),
    MUSIC_LIMITS,
  ),
  makeTemplate(
    'music-finale',
    'music',
    'Final musical',
    'Cierra el videoclip con una composición amplia, legible y de energía sostenida.',
    musicSlots(
      'Motivo principal que sostiene la imagen final y recibe el último acento visual.',
      'Placa de cierre que permite una salida amplia sin necesitar audio real.',
      'Capa opcional de destellos, formas o marco para marcar el final.',
    ),
    MUSIC_LIMITS,
  ),
  makeTemplate(
    'space-cruise',
    'space',
    'Crucero espacial',
    'Acompaña una nave por un campo estelar con sensación de viaje continuo.',
    spaceSlots(
      'Nave principal GLB que define la dirección, escala y lectura del crucero.',
      'Placa de estrellas o espacio profundo que se desplaza como fondo visual.',
      'Capa opcional de estrellas cercanas, polvo o líneas de velocidad en imagen.',
    ),
    SPACE_LIMITS,
  ),
  makeTemplate(
    'space-orbit',
    'space',
    'Órbita espacial',
    'Hace orbitar la nave hero alrededor de un planeta o estación prop mediante keyframes de capa.',
    spaceSlots(
      'Nave principal GLB que orbita el planeta o estación prop; no es una cámara orbital real.',
      'Placa espacial que aporta estrellas, planeta o campo visual de referencia.',
      'Capa opcional de partículas o polvo estelar en primer término.',
      {
        required: true,
        kinds: IMAGE_OR_MODEL3D,
        description: 'Planeta o estación que sirve de centro de la órbita; acepta imagen o GLB sin oclusión global.',
      },
    ),
    SPACE_ORBIT_LIMITS,
  ),
  makeTemplate(
    'space-docking',
    'space',
    'Acoplamiento espacial',
    'Simula un acercamiento de nave a estación mediante capas y movimiento controlado.',
    spaceSlots(
      'Nave GLB que ejecuta el acercamiento y conserva una silueta estable.',
      'Placa de espacio o hangar que fija la dirección del acoplamiento.',
      'Capa opcional de luces, polvo o marco de compuerta en primer término.',
      {
        required: true,
        kinds: IMAGE_OR_MODEL3D,
        description: 'Estación o compuerta de destino; acepta imagen o GLB sin resolver colisiones.',
      },
    ),
    SPACE_LIMITS,
  ),
  makeTemplate(
    'space-chase',
    'space',
    'Persecución espacial',
    'Compone una persecución de naves con desplazamiento paralelo, sin física de colisión.',
    spaceSlots(
      'Nave perseguidora GLB que lleva el movimiento y la dirección de la persecución.',
      'Placa de estrellas o nebulosa que da continuidad al desplazamiento.',
      'Capa opcional de polvo, rayas o luces en primer plano.',
      {
        required: true,
        kinds: MODEL3D,
        description: 'Nave perseguida o escolta GLB; se mueve por keyframes, sin colisiones.',
      },
    ),
    SPACE_LIMITS,
  ),
  makeTemplate(
    'space-broadside',
    'space',
    'Enfrentamiento lateral espacial',
    'Presenta dos perfiles de nave como una confrontación visual por capas.',
    spaceSlots(
      'Nave GLB principal mostrada de perfil para definir el eje del enfrentamiento.',
      'Placa de campo estelar que conserva espacio negativo entre las naves.',
      'Capa opcional de destellos, humo gráfico o partículas en imagen.',
      {
        required: true,
        kinds: MODEL3D,
        description: 'Nave rival GLB para el perfil enfrentado; no hay colisión ni oclusión global.',
      },
    ),
    SPACE_LIMITS,
  ),
  makeTemplate(
    'space-shield',
    'space',
    'Escudo espacial',
    'Visualiza un impacto o escudo como acento gráfico sobre una nave compuesta.',
    spaceSlots(
      'Nave atacante GLB que marca la dirección del impacto y permanece como referencia espacial.',
      'Placa de campo estelar que contrasta con el destello del escudo.',
      'Capa opcional de energía, humo o partículas en imagen.',
      {
        required: true,
        kinds: MODEL3D,
        description: 'Nave GLB objetivo que recibe el escudo; el impacto se anima sin física.',
      },
    ),
    SPACE_LIMITS,
  ),
  makeTemplate(
    'space-explosion',
    'space',
    'Explosión espacial',
    'Representa una explosión gráfica alrededor de una nave mediante capas y keyframes.',
    spaceSlots(
      'Nave atacante GLB que fija el origen visual del ataque.',
      'Placa espacial que da contraste y escala al destello.',
      'Capa opcional de humo, fuego o fragmentos en imagen.',
      {
        required: true,
        kinds: MODEL3D,
        description: 'Nave blanco GLB que desaparece al explotar; no simula fragmentación física.',
      },
    ),
    SPACE_LIMITS,
  ),
  makeTemplate(
    'space-warp',
    'space',
    'Salto espacial',
    'Acelera una nave hacia un salto visual con rayas y capas de profundidad controladas.',
    spaceSlots(
      'Nave GLB que permanece legible durante la aceleración hacia el salto.',
      'Placa de estrellas o túnel espacial que admite un desplazamiento continuo.',
      'Capa opcional de líneas de velocidad, polvo o destellos en imagen.',
    ),
    SPACE_LIMITS,
  ),
] as const satisfies readonly SceneTemplateDefinition[]

/** Video2D drafts use their own compiler; they are not layer-compositor templates. */
export const VIDEO2D_SCENE_TEMPLATES = [
  makeTemplate('documentary-history', 'cinema', 'Documental histórico', 'Foto con movimiento lento, rótulo de fecha y acabado de archivo. Candidata, no aprobada.', cinemaSlots('Fotografía o plano de archivo que sostiene el documental.', 'Placa de entorno detrás de la fecha.', 'Polvo o primer término opcional.'), CINEMA_LIMITS),
  makeTemplate('trailer-teaser', 'cinema', 'Teaser de tráiler', 'Golpes de título sobre negro, tarjeta final y bandas anchas. Candidata, no aprobada.', cinemaSlots('Plano corto que golpea el título.', 'Negro o placa de contraste.', 'Capa opcional de destello.'), CINEMA_LIMITS),
  makeTemplate('lyric-vertical', 'music', 'Lyric video vertical', 'Pieza 9:16 con letra en karaoke y pulso. Candidata, no aprobada.', musicSlots('Fondo de movimiento lento.', 'Placa que no compite con la letra.', 'Detalle opcional en los bordes.'), MUSIC_LIMITS),
  makeTemplate('city-postcard', 'music', 'Postal de ciudad', 'Tira de ciudad, banner de papel y gaviotas. Candidata, no aprobada.', musicSlots('Plano de ciudad en tira.', 'Cielo o placa detrás del banner.', 'Gaviotas u otro primer término.'), MUSIC_LIMITS),
] as const satisfies readonly SceneTemplateDefinition[]

/** Original references stay versioned separately: never rewrite their hashes or
 * infer that a new choreography has an approved reference because it compiles. */
export const ALL_SCENE_TEMPLATES: readonly SceneTemplateDefinition[] = [...CANDIDATE_SCENE_TEMPLATES, ...MUSIC_MOTION_TEMPLATES]

// Membership is explicit: the legacy catalogue contains a few `music-*`
// IDs of its own, and a slot name alone must not move one of those templates
// into the expanded review version.
const EXPANDED_TEMPLATE_IDS = new Set(MUSIC_MOTION_TEMPLATES.map(template => template.id))

export function templateCatalogVersion(template: SceneTemplateDefinition): string {
  return EXPANDED_TEMPLATE_IDS.has(template.id) ? EXPANDED_CATALOG_VERSION : CATALOG_VERSION
}

export function getCandidateSceneTemplate(id: string): SceneTemplateDefinition {
  const template = ALL_SCENE_TEMPLATES.find(candidate => candidate.id === id)
  if (!template) {
    throw new Error(`Unknown candidate scene template: ${id}`)
  }
  return template
}
