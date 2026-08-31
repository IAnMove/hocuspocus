import type { AgentAction, AgentTab, AgentTurn } from './agentActions'

export type ExampleKind = 'video' | 'image' | 'audio' | 'sfx' | '3d' | 'story' | 'series' | 'comic'

export interface ExampleConversation {
  role: 'user' | 'assistant'
  text: string
}

function hashSalt(salt: string): number {
  let hash = 2166136261
  for (let index = 0; index < salt.length; index += 1) {
    hash ^= salt.charCodeAt(index)
    hash = Math.imul(hash, 16777619)
  }
  return Math.abs(hash)
}

export function pickExample<T>(items: T[], salt: string, skip: (item: T) => boolean = () => false): T {
  const available = items.filter(item => !skip(item))
  const pool = available.length ? available : items
  return pool[hashSalt(salt) % pool.length]
}

const KIND_PATTERNS: Array<{ kind: ExampleKind; pattern: RegExp }> = [
  { kind: 'comic', pattern: /\b(?:c[oó]mics?|tebeo|vi[nñ]etas?|tira\s+c[oó]mica)\b/i },
  { kind: 'series', pattern: /\b(?:episodio|cap[ií]tulo|series?\s+lab|sitcom|chapter)\b/i },
  { kind: 'story', pattern: /\b(?:historias?|cuentos?|story(?:\s+lab)?|gui[oó]n)\b/i },
  { kind: 'sfx', pattern: /\b(?:efectos?(?:\s+de\s+sonido)?|sfx|sonidos?|sound\s*effects?)\b/i },
  { kind: 'audio', pattern: /\b(?:m[uú]sica|canci[oó]n|audio|tts|music|song|speech|voz)\b/i },
  { kind: '3d', pattern: /\b(?:modelo\s*3d|objeto\s*3d|hunyuan(?:3d)?|3d(?:\s+model)?)\b/i },
  { kind: 'image', pattern: /\b(?:im[aá]genes?|fotos?|retrato|ilustraci[oó]n|images?|pictures?|photos?|portrait)\b/i },
  { kind: 'video', pattern: /\b(?:v[ií]deos?|clips?)\b/i },
]

export function detectExampleKind(text: string): ExampleKind | null {
  for (const entry of KIND_PATTERNS) {
    if (entry.pattern.test(text)) return entry.kind
  }
  return null
}

export function inferExampleKind(request: string, history: ExampleConversation[]): ExampleKind | null {
  const fromRequest = detectExampleKind(request)
  if (fromRequest) return fromRequest
  for (let index = history.length - 1; index >= 0; index -= 1) {
    if (history[index].role !== 'user') continue
    const kind = detectExampleKind(history[index].text)
    if (kind) return kind
  }
  for (let index = history.length - 1; index >= 0; index -= 1) {
    const kind = detectExampleKind(history[index].text)
    if (kind) return kind
  }
  return null
}

export function isExampleRequest(text: string): boolean {
  return /\b(?:ejemplo|example|inventa(?:lo|me)?|uno\s+de\s+(?:ejemplo|muestra)|demo|sorpr[eé]ndeme|surprise\s+me)\b/i.test(text)
}

export function isBareCreateRequest(text: string, kind: ExampleKind): boolean {
  const stripped = text
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[¿?¡!.,:;]/g, ' ')
    .replace(/\b(?:por favor|please|hazme|hacedme|haz|haced|generame|genera|creame|crea|lanza|make|create|generate|un|una|el|la|de|del|a|an|the|of|me|uno|example|ejemplo|inventa|inventame)\b/g, ' ')
    .replace(KIND_PATTERNS.find(entry => entry.kind === kind)?.pattern ?? /$^/g, ' ')
    .replace(/\s+/g, '')
  return stripped.length < 6
}

const SECTION_TAB: Record<ExampleKind, AgentTab> = {
  video: 'studio',
  image: 'studio',
  audio: 'studio',
  sfx: 'studio',
  '3d': 'studio',
  story: 'story_lab',
  series: 'series_lab',
  comic: 'comics',
}

const BARE_ASK: Record<ExampleKind, string> = {
  video: 'Claro. ¿De qué quieres el vídeo? Si no tienes tema, dime **hazme uno de ejemplo** y lo invento y lo encolo.',
  image: 'Claro. ¿Qué imagen quieres? Si no tienes tema, dime **hazme una de ejemplo** y la invento y la encolo.',
  audio: 'Claro. ¿Qué música o voz quieres? Si no tienes tema, dime **hazme una de ejemplo** y la invento (ACE-Step, sin vídeo).',
  sfx: 'Claro. ¿Qué efectos de sonido? Si no tienes tema, dime **hazme unos de ejemplo** y encolo un pack corto.',
  '3d': 'Claro. ¿Qué objeto 3D quieres? Si no tienes tema, dime **hazme uno de ejemplo** y lo invento en Hunyuan3D.',
  story: 'Claro. ¿De qué quieres la historia? Si no tienes tema, dime **hazme una de ejemplo** y relleno Story Lab entero.',
  series: 'Claro. ¿De qué serie o episodio? Si no tienes tema, dime **hazme uno de ejemplo** y relleno Series Lab.',
  comic: 'Claro. ¿De qué quieres el cómic? Si no tienes tema, dime **hazme uno de ejemplo** y relleno viñetas y globos.',
}

const VIDEO_EXAMPLES = [
  'A curious raccoon in a yellow raincoat dashes across a moonlit Tokyo crosswalk; neon reflections ripple in puddles as the camera tracks low, 16:9 cinematic.',
  'An old tram climbs a foggy hillside orchard at dawn; steam, wet rails, and a single lantern swing in the foreground, slow crane up.',
  'Two paper boats race down a rain gutter in a coastal town; kids chase them, handheld, warm late-afternoon light.',
  'A desert radio telescope turns toward a green comet; dust devils, long shadows, IMAX-wide establishing shot.',
  'A street magician folds a city map into a bird that actually takes off; dusk, practical sparks, medium close-up.',
  'A baker taps a baguette like a microphone and the whole shop starts a tiny parade; golden hour through flour dust.',
  'Underwater library: a diver shelves glowing bottles; shafts of light, slow push-in, quiet bubbles.',
  'A night bus stops in the middle of a sunflower field; passengers step out as if it were a station, 16:9.',
]

const IMAGE_EXAMPLES = [
  'Portrait of a brass diving helmet filled with potted ferns, studio lighting, sharp details, 1:1.',
  'Overhead still life of a midnight snack on a rooftop: thermos, star map, orange peel, cinematic moonlight.',
  'A tiny lighthouse built into a teacup, stormy sea in miniature, tilt-shift, 16:9.',
  'Street-level photo of a blue bicycle buried in cherry blossoms, wet pavement reflections.',
  'Cutaway diagram of a pocket watch inhabited by miniature librarians, engraving style, 1:1.',
  'A red umbrella hovering over an empty plaza at noon, hard shadows, photoreal, 4:3.',
  'Portrait of a fox wearing a station-master cap, painterly, warm wool textures, 1:1.',
  'Kitchen window at 6am: kettle steam, fogged glass, one yellow mug, documentary photo.',
]

const AUDIO_EXAMPLES = [
  { prompt: 'Lo-fi kitchen radio jazz, brushed drums, warm bass, rainy window, 20 seconds, instrumental.', durationSeconds: 20 },
  { prompt: 'Playful accordion waltz for a harbour market, claps, no vocals, 18 seconds.', durationSeconds: 18 },
  { prompt: 'Dreamy synth lullaby with music-box motif, slow, instrumental, 16 seconds.', durationSeconds: 16 },
  { prompt: 'Upbeat retro game overworld loop, bright chiptune-adjacent but modern mix, 12 seconds.', durationSeconds: 12 },
  { prompt: 'Dusty desert guitar and hand percussion, sunset, no vocals, 22 seconds.', durationSeconds: 20 },
  { prompt: 'Library-quiet piano and soft vinyl crackle, late night study, instrumental, 18 seconds.', durationSeconds: 18 },
  { prompt: 'Carnival calliope skipping a beat then recovering, cheerful, no vocals, 14 seconds.', durationSeconds: 14 },
  { prompt: 'Foggy harbour horns arranged as a slow melody, distant gulls, instrumental, 16 seconds.', durationSeconds: 16 },
]

const SFX_PACKS = [
  [
    { name: 'ui_click', prompt: 'tiny wooden UI click, clean one-shot, no music', durationSeconds: 1 },
    { name: 'ui_error', prompt: 'short muted error blip, retro terminal, no music', durationSeconds: 1 },
    { name: 'door_wood', prompt: 'old kitchen door close, wood thud, no music', durationSeconds: 1 },
  ],
  [
    { name: 'space_beep', prompt: 'short sci-fi console beep, clean, no music', durationSeconds: 1 },
    { name: 'airlock_hiss', prompt: 'airlock pressure hiss, short, no music', durationSeconds: 2 },
    { name: 'thruster_blip', prompt: 'tiny thruster puff, one-shot, no music', durationSeconds: 1 },
  ],
  [
    { name: 'coin_pickup', prompt: 'bright metallic coin pickup sparkle, arcade, no music', durationSeconds: 1 },
    { name: 'chest_open', prompt: 'wooden chest lid open with small gold rattle, no music', durationSeconds: 2 },
    { name: 'level_up', prompt: 'short triumphant power-up jingle, arcade, no music', durationSeconds: 2 },
  ],
  [
    { name: 'cat_meow', prompt: 'short cartoon cat meow, one-shot, no music', durationSeconds: 1 },
    { name: 'milk_pour', prompt: 'pouring milk into a bowl, short, no music', durationSeconds: 2 },
    { name: 'purr_loop', prompt: 'tiny cat purr blip, cute, no music', durationSeconds: 1 },
  ],
  [
    { name: 'typewriter', prompt: 'single typewriter key clack, close mic, no music', durationSeconds: 1 },
    { name: 'paper_rip', prompt: 'short paper tear, one-shot, no music', durationSeconds: 1 },
    { name: 'stamp_thud', prompt: 'rubber stamp thud on paper, no music', durationSeconds: 1 },
  ],
]

const MODEL3D_EXAMPLES = [
  'A small brass garlic-shaped lantern with punched star holes, single object, studio turntable.',
  'A chipped enamel camping mug with a dented handle, photoreal, single object.',
  'A toy wooden robot with blocky joints and a painted smile, single object.',
  'A folded paper boat with wet edges, single object, studio lighting.',
  'A ceramic teapot shaped like a sleeping cat, single object, matte glaze.',
  'A pocket compass with a cracked glass lid, brass, single object.',
  'A slice of toast with a tiny padlock instead of a bite, single object.',
  'A vintage bicycle bell, chrome and brass, single object, studio lighting.',
]

const STORY_EXAMPLES = [
  {
    title: 'La linterna de la orilla',
    premise: 'Una farera jubilada encuentra una linterna que muestra puertos que aún no existen.',
    logline: 'Para salvar su pueblo de la niebla, debe decidir qué futuro iluminar.',
    synopsis: 'Marta descubre que la linterna adelanta mareas. Cada uso acerca un puerto imposible y aleja a su nieto del presente.',
    theme: 'Elegir un futuro tiene coste en el presente.',
    ending: 'Apaga la linterna y enseña al nieto a leer las estrellas de verdad.',
    genre: 'Drama fantástico',
    tone: 'Cálido y nocturno',
    visualStyle: 'Costumbrismo costero, lámparas de aceite, niebla azul.',
    characters: [
      { name: 'Marta', role: 'Protagonista', personality: 'Práctica', desire: 'Proteger el faro', flaw: 'No pide ayuda', appearance: 'Abrigo de lana, pelo blanco corto', voice: 'Baja y clara' },
      { name: 'Nil', role: 'Nieto', personality: 'Curioso', desire: 'Ver el puerto del futuro', flaw: 'Impaciente', appearance: 'Chaqueta amarilla', voice: 'Rápida' },
    ],
    locations: [{ name: 'Faro', purpose: 'Conflicto', description: 'Torre blanca sobre acantilado húmedo' }],
    outlineBeats: ['Marta encuentra la linterna', 'Nil ve un puerto imposible', 'Apagan la linterna juntos'],
  },
  {
    title: 'El tranvía de los martes',
    premise: 'Un músico descubre que el tranvía de las 7:12 detiene el tiempo solo para él.',
    logline: 'Tiene una canción que terminar antes de que el tiempo vuelva a moverse.',
    synopsis: 'Oriol usa el tranvía congelado para ensayar. Un día otra pasajera también está despierta.',
    theme: 'El arte no se guarda en una pausa eterna.',
    ending: 'Toca la canción en movimiento y deja el tranvía seguir.',
    genre: 'Comedia mágica',
    tone: 'Ligero y bittersweet',
    visualStyle: 'Barcelona lluviosa, amarillos de tranvía, grano suave.',
    characters: [
      { name: 'Oriol', role: 'Protagonista', personality: 'Tímido', desire: 'Terminar la canción', flaw: 'Evita al público', appearance: 'Jersey verde, funda de guitarra', voice: 'Suave' },
      { name: 'Laia', role: 'Pasajera', personality: 'Directa', desire: 'Llegar a tiempo a un adiós', flaw: 'Impaciencia', appearance: 'Chubasquero rojo', voice: 'Seca y amable' },
    ],
    locations: [{ name: 'Tranvía 7:12', purpose: 'Burbuja temporal', description: 'Interior de madera, ventanas empañadas' }],
    outlineBeats: ['El tiempo se detiene', 'Laia está despierta', 'Tocan en movimiento'],
  },
  {
    title: 'Recetas a contrarreloj',
    premise: 'Una pastelería hereda un horno que cocina el recuerdo que más duele al cliente.',
    logline: 'Para salvar el negocio tienen que servir verdades que nadie pidió.',
    synopsis: 'Núria y su hermano aprenden que cada encargo saca un secreto. El pueblo se acerca y se aleja a la vez.',
    theme: 'El dulce no borra lo que hay que decir.',
    ending: 'Dejan el horno en frío y cuecen a mano el pedido más difícil.',
    genre: 'Drama costumbrista',
    tone: 'Tierno con ironía',
    visualStyle: 'Vitrinas al amanecer, azúcar glass, azulejos verdes.',
    characters: [
      { name: 'Núria', role: 'Protagonista', personality: 'Organizada', desire: 'Mantener la pastelería', flaw: 'Controla demasiado', appearance: 'Delantal manchado de cacao', voice: 'Rápida' },
      { name: 'Ivo', role: 'Hermano', personality: 'Caótico', desire: 'Que la gente vuelva', flaw: 'Habla de más', appearance: 'Gorra y harina en el pelo', voice: 'Cálida' },
    ],
    locations: [{ name: 'Obrador', purpose: 'Motor mágico', description: 'Horno de piedra, reloj parado a las 6:05' }],
    outlineBeats: ['El horno cuece un recuerdo', 'Un encargo rompe un secreto', 'Cocinan sin magia'],
  },
  {
    title: 'El mapa del ascensor',
    premise: 'Un conserje descubre que el ascensor abre pisos que el edificio no tiene.',
    logline: 'Cada botón extra pide una disculpa que nunca se dio.',
    synopsis: 'Fermín sube a un piso 13½ donde viven versiones de los vecinos. Para volver, tiene que entregar mensajes atrasados.',
    theme: 'Lo no dicho también ocupa espacio.',
    ending: 'Deja el botón extra sin pulsar y sube las escaleras de verdad.',
    genre: 'Fantasía urbana',
    tone: 'Quieto y extraño',
    visualStyle: 'Recepción de mármol gastado, luces de neón débil, medianoche.',
    characters: [
      { name: 'Fermín', role: 'Protagonista', personality: 'Discreto', desire: 'Que el edificio duerma', flaw: 'Evita conflictos', appearance: 'Chaqueta de conserje, llaves enormes', voice: 'Baja' },
      { name: 'Alba', role: 'Vecina', personality: 'Insomne', desire: 'Encontrar a su gato', flaw: 'No cree en rarezas', appearance: 'Bata y linterna de móvil', voice: 'Seca' },
    ],
    locations: [{ name: 'Ascensor 3', purpose: 'Umbral', description: 'Cabina de madera, espejo que llega un segundo tarde' }],
    outlineBeats: ['Aparece un botón de más', 'El piso imposible', 'Entregan las disculpas'],
  },
]

const SERIES_EXAMPLES = [
  {
    seriesTitle: 'Turno de madrugada',
    seriesPremise: 'Tres trabajadores de una gasolinera de montaña resuelven misterios minúsculos.',
    episodeTitle: 'El café que no enfría',
    episodePremise: 'Una jarra de café permanece caliente hasta que alguien dice la verdad.',
    episodeLogline: 'Para cerrar el turno tienen que confesar una tontería cada uno.',
    characters: [
      { name: 'Vera', role: 'Encargada', personality: 'Seca', desire: 'Cerrar a tiempo', flaw: 'Control', appearance: 'Gorra y forro polar', voice: 'Cansada' },
      { name: 'Pol', role: 'Novato', personality: 'Hiperactivo', desire: 'Caer bien', flaw: 'Habla de más', appearance: 'Chaleco naranja', voice: 'Rápida' },
      { name: 'Núria', role: 'Mecánica', personality: 'Callada', desire: 'Paz', flaw: 'Guarda rencor', appearance: 'Mono manchado', voice: 'Baja' },
    ],
    locations: [{ name: 'Gasolinera Coll', purpose: 'Set principal', description: 'Isla de surtidores, niebla, neón débil' }],
    outlineBeats: ['El café no enfría', 'Confiesan mentiras tontas', 'El café humea normal'],
  },
  {
    seriesTitle: 'Archivo de techos',
    seriesPremise: 'Una archivista cataloga sueños que se cuelan por las claraboyas de la ciudad.',
    episodeTitle: 'El gato del quinto',
    episodePremise: 'Un gato entrega sueños ajenos en el buzón equivocado.',
    episodeLogline: 'Para devolver cada sueño hay que subir sin ascensor.',
    characters: [
      { name: 'Iris', role: 'Archivista', personality: 'Meticulosa', desire: 'Orden', flaw: 'No improvisa', appearance: 'Gabardina gris', voice: 'Precisa' },
      { name: 'Teo', role: 'Portero', personality: 'Chistoso', desire: 'Que no pasen rarezas', flaw: 'Niegan lo extraño', appearance: 'Llaves enormes', voice: 'Cálida' },
      { name: 'Mim', role: 'Gato', personality: 'Opaco', desire: 'Atún', flaw: 'Caos', appearance: 'Naranja con chaleco', voice: 'Miau narrado' },
    ],
    locations: [{ name: 'Azotea archivo', purpose: 'Oficina', description: 'Claraboyas, cajas de cartón, viento' }],
    outlineBeats: ['Sueños en el buzón', 'Suben planta a planta', 'El gato elige el atún'],
  },
  {
    seriesTitle: 'Radio Faro',
    seriesPremise: 'Una emisora local emite avisos que ocurren cinco minutos después.',
    episodeTitle: 'El parte del gato',
    episodePremise: 'El boletín anuncia un gato perdido que todavía está en el estudio.',
    episodeLogline: 'Tienen que perder el gato a propósito para que el parte sea verdad.',
    characters: [
      { name: 'Rita', role: 'Locutora', personality: 'Dulce', desire: 'No mentir en antena', flaw: 'Se atasca', appearance: 'Auriculares enormes', voice: 'Radio cálida' },
      { name: 'Grau', role: 'Técnico', personality: 'Cínico', desire: 'Que no se rompa nada', flaw: 'Nieva lo extraño', appearance: 'Mono y cinta americana', voice: 'Seca' },
      { name: 'Pipa', role: 'Gato mascota', personality: 'Diva', desire: 'Atención', flaw: 'Se esconde mal', appearance: 'Blanco con mancha en un ojo', voice: 'Silencio elocuente' },
    ],
    locations: [{ name: 'Cabina Radio Faro', purpose: 'Set', description: 'Mesa de mezclas, ventana al puerto, neón rojo' }],
    outlineBeats: ['El parte se adelanta', 'Intentan perder el gato', 'El gato vuelve al aire'],
  },
  {
    seriesTitle: 'Museo de las 8:03',
    seriesPremise: 'Los vigilantes nocturnos de un museo pequeño negocian con las obras cuando nadie mira.',
    episodeTitle: 'La silla que se sienta',
    episodePremise: 'Una silla de diseño se niega a volver al pedestal hasta que alguien la use bien.',
    episodeLogline: 'El turno acaba si consiguen que un humano se siente sin romper el protocolo.',
    characters: [
      { name: 'Dani', role: 'Vigilante', personality: 'Ansioso', desire: 'Turno tranquilo', flaw: 'Sigue las normas al milímetro', appearance: 'Uniforme arrugado', voice: 'Susurro' },
      { name: 'Ona', role: 'Restauradora', personality: 'Valiente', desire: 'Entender las piezas', flaw: 'Toca de más', appearance: 'Guantes y linterna frontal', voice: 'Firme' },
      { name: 'Silla 14', role: 'Obra', personality: 'Ofendida', desire: 'Ser útil', flaw: 'Dramática', appearance: 'Madera clara, patas largas', voice: 'Chirrido elegante' },
    ],
    locations: [{ name: 'Sala de diseño', purpose: 'Conflicto', description: 'Pedestales, sensores rojos, suelo de parquet' }],
    outlineBeats: ['La silla se baja', 'Negocian un asiento', 'Vuelve al pedestal'],
  },
]

const COMIC_EXAMPLES = [
  {
    title: 'Sopa de antena',
    synopsis: 'Dos vecinos discuten si la antena del tejado cocina mejor que ellos.',
    styleName: 'Tira cómica de prensa, tinta clara, 4 viñetas',
    characters: [
      { name: 'Rosa', role: 'Vecina', description: 'Bata a lunares, cuchara de palo' },
      { name: 'Quim', role: 'Vecino', description: 'Gorra, binocular de juguete' },
    ],
    panels: [
      { caption: 'Martes, tejado.', dialogue: 'La sopa está rara.', sfx: '' },
      { caption: '', dialogue: 'Es que la antena tiene receta propia.', sfx: 'BEEP' },
      { caption: '', dialogue: '¿Le ponemos pan?', sfx: '' },
      { caption: 'Fin.', dialogue: 'Mejor pedimos pizza.', sfx: 'DING' },
    ],
  },
  {
    title: 'El timbre congelado',
    synopsis: 'El recreo no acaba porque el timbre se ha hecho un muñeco de nieve.',
    styleName: 'Cómic infantil, colores planos, 4 viñetas',
    characters: [
      { name: 'Mar', role: 'Alumna', description: 'Bufanda enorme, mochila rana' },
      { name: 'Timbre', role: 'Antagonista blando', description: 'Campana con brazos de nieve' },
    ],
    panels: [
      { caption: 'Patio.', dialogue: '¿Nadie oye el timbre?', sfx: '' },
      { caption: '', dialogue: 'Estoy de vacaciones.', sfx: 'BRRR' },
      { caption: '', dialogue: 'Te ponemos un gorro.', sfx: '' },
      { caption: 'El recreo gana.', dialogue: 'Cinco minutos más.', sfx: 'DING' },
    ],
  },
  {
    title: 'Farol y marea',
    synopsis: 'Un farero discute con la marea porque le mueve las sillas.',
    styleName: 'Novela gráfica corta, acuarela, 4 viñetas',
    characters: [
      { name: 'Leo', role: 'Farero', description: 'Impermeable, bigote de sal' },
      { name: 'Marea', role: 'Mar personificado', description: 'Ola con sombrero' },
    ],
    panels: [
      { caption: 'Muelle.', dialogue: 'Devuélveme la silla.', sfx: '' },
      { caption: '', dialogue: 'Es mía en pleamar.', sfx: 'SPLASH' },
      { caption: '', dialogue: 'Entonces te presto el faro.', sfx: '' },
      { caption: 'Trato.', dialogue: 'Hasta el bajamar.', sfx: 'FOG' },
    ],
  },
  {
    title: 'Gato en la impresora',
    synopsis: 'El gato de la oficina se convierte en el tóner oficial.',
    styleName: 'Webcómic de oficina, línea limpia, 4 viñetas',
    characters: [
      { name: 'Beto', role: 'Becario', description: 'Camisa de cuadros, café eterno' },
      { name: 'Pixel', role: 'Gato', description: 'Gris, se sienta en todo' },
    ],
    panels: [
      { caption: 'Lunes.', dialogue: 'La impresora pide tóner.', sfx: '' },
      { caption: '', dialogue: 'Yo soy el tóner.', sfx: 'Prrr' },
      { caption: '', dialogue: '¿Imprimes el informe?', sfx: '' },
      { caption: 'Entregado.', dialogue: 'Sale cubierto de pelo.', sfx: 'CLUNK' },
    ],
  },
  {
    title: 'El semáforo tímido',
    synopsis: 'Un semáforo no se pone en verde porque le da vergüenza el cruce.',
    styleName: 'Tira urbana, pastel, 4 viñetas',
    characters: [
      { name: 'Luz', role: 'Semáforo', description: 'Poste delgado, gafas imaginarias' },
      { name: 'Eva', role: 'Ciclista', description: 'Casco amarillo, cesta con pan' },
    ],
    panels: [
      { caption: 'Cruce.', dialogue: '¿Vas a ponerte verde?', sfx: '' },
      { caption: '', dialogue: 'Hay gente mirando.', sfx: 'TICK' },
      { caption: '', dialogue: 'Cierro los ojos.', sfx: '' },
      { caption: 'Pasan.', dialogue: 'Verde tímido.', sfx: 'DING' },
    ],
  },
  {
    title: 'Biblioteca de nubes',
    synopsis: 'Una bibliotecaria multa a una nube por devolver la lluvia tarde.',
    styleName: 'Infantil poético, acuarela suave, 4 viñetas',
    characters: [
      { name: 'Vera', role: 'Bibliotecaria', description: 'Jersey de lana, sello enorme' },
      { name: 'Nube 7', role: 'Lectora', description: 'Nube con gafas de lectura' },
    ],
    panels: [
      { caption: 'Sala infantil.', dialogue: 'Este chubasco vence hoy.', sfx: '' },
      { caption: '', dialogue: 'Se me ha nublado el calendario.', sfx: 'PITTER' },
      { caption: '', dialogue: 'Multa: un arcoíris.', sfx: '' },
      { caption: 'Devuelto.', dialogue: 'Con marcador de sol.', sfx: 'SHHH' },
    ],
  },
]

function historyBlob(history: ExampleConversation[]): string {
  return history.map(entry => entry.text).join('\n')
}

function usedInHistory(history: ExampleConversation[], value: string): boolean {
  if (!value.trim()) return false
  return historyBlob(history).includes(value.trim())
}

export function exampleSalt(kind: ExampleKind, request: string, history: ExampleConversation[]): string {
  return [kind, request, String(history.length), historyBlob(history)].join('|')
}

export function exampleActionsFor(
  kind: ExampleKind,
  salt: string,
  history: ExampleConversation[] = [],
): { reply: string; actions: AgentAction[] } {
  if (kind === 'video') {
    const prompt = pickExample(VIDEO_EXAMPLES, salt, item => usedInHistory(history, item))
    return {
      reply: `Inventaré un vídeo de ejemplo distinto y lo enviaré a la cola.\n\n**Prompt:** ${prompt}`,
      actions: [
        { type: 'prepare_video', prompt, durationSeconds: 5, resolutionPreset: '720p', aspectRatio: '16:9', seed: -1, outputCount: 1 },
        { type: 'start_generation', confirm: true },
      ],
    }
  }
  if (kind === 'image') {
    const prompt = pickExample(IMAGE_EXAMPLES, salt, item => usedInHistory(history, item))
    return {
      reply: `Inventaré una imagen de ejemplo y la enviaré a la cola.\n\n**Prompt:** ${prompt}`,
      actions: [
        { type: 'prepare_image', prompt, resolutionPreset: 'auto', aspectRatio: 'auto', seed: -1, outputCount: 1 },
        { type: 'start_generation', confirm: true },
      ],
    }
  }
  if (kind === 'audio') {
    const example = pickExample(AUDIO_EXAMPLES, salt, item => usedInHistory(history, item.prompt))
    return {
      reply: `Inventaré una pieza de audio de ejemplo en Studio → Audio → Music (ACE-Step, **sin vídeo**).\n\n**Prompt:** ${example.prompt}`,
      actions: [
        { type: 'prepare_audio', subMode: 'music', prompt: example.prompt, durationSeconds: example.durationSeconds },
        { type: 'start_generation', confirm: true },
      ],
    }
  }
  if (kind === 'sfx') {
    const clips = pickExample(SFX_PACKS, salt, pack => pack.some(clip => usedInHistory(history, clip.name)))
    return {
      reply: 'Inventaré un pack corto de SFX de ejemplo y lo encolaré. Recuerda: MMAudio todavía fabrica un vídeo LTX por cada clip; no es un generador de audio-only.',
      actions: [{ type: 'queue_sfx_pack', style: 'example pack', clips, confirm: true }],
    }
  }
  if (kind === '3d') {
    const prompt = pickExample(MODEL3D_EXAMPLES, salt, item => usedInHistory(history, item))
    return {
      reply: `Inventaré un objeto 3D de ejemplo en Hunyuan3D y lo enviaré a generar.\n\n**Prompt:** ${prompt}`,
      actions: [
        { type: 'prepare_3d', prompt, preset: 'balanced', seed: hashSalt(salt) % 10_000 },
        { type: 'start_generation', confirm: true },
      ],
    }
  }
  if (kind === 'story') {
    const story = pickExample(STORY_EXAMPLES, salt, item => usedInHistory(history, item.title))
    return {
      reply: `Inventaré y guardaré una historia de ejemplo en Story Lab: **${story.title}**.`,
      actions: [{
        type: 'create_story',
        title: story.title,
        projectType: 'full_story',
        creativeBrief: story.premise,
        premise: story.premise,
        logline: story.logline,
        synopsis: story.synopsis,
        theme: story.theme,
        ending: story.ending,
        genre: story.genre,
        tone: story.tone,
        visualStyle: story.visualStyle,
        worldSummary: story.synopsis,
        language: 'Español',
        characters: story.characters,
        locations: story.locations,
        outlineBeats: story.outlineBeats,
      }],
    }
  }
  if (kind === 'series') {
    const episode = pickExample(SERIES_EXAMPLES, salt, item => usedInHistory(history, item.episodeTitle))
    return {
      reply: `Inventaré y guardaré un episodio de ejemplo en Series Lab: **${episode.seriesTitle} / ${episode.episodeTitle}**.`,
      actions: [{
        type: 'create_series_episode',
        seriesTitle: episode.seriesTitle,
        seriesPremise: episode.seriesPremise,
        seriesLogline: episode.episodeLogline,
        episodeTitle: episode.episodeTitle,
        episodePremise: episode.episodePremise,
        episodeLogline: episode.episodeLogline,
        genre: 'Comedia',
        tone: 'Cálido',
        visualStyle: 'Sitcom cinematográfica sencilla',
        worldSummary: episode.seriesPremise,
        theme: 'Turnos y secretos pequeños',
        ending: episode.outlineBeats[episode.outlineBeats.length - 1],
        language: 'Español',
        characters: episode.characters,
        locations: episode.locations,
        outlineBeats: episode.outlineBeats,
        createIfMissing: true,
        knownUniverse: false,
      }],
    }
  }
  const comic = pickExample(COMIC_EXAMPLES, salt, item => usedInHistory(history, item.title))
  return {
    reply: `Inventaré un cómic de ejemplo distinto y rellenaré viñetas y globos: **${comic.title}**. No dibujo todavía las viñetas: dime **lánzalo** o pulsa **Generate all images** en Comic Director.`,
    actions: [{
      type: 'create_comic',
      title: comic.title,
      synopsis: comic.synopsis,
      language: 'Español',
      styleName: comic.styleName,
      characters: comic.characters.map(character => ({
        name: character.name,
        role: character.role,
        personality: '',
        desire: '',
        flaw: '',
        appearance: character.description,
        voice: '',
      })),
      panels: comic.panels,
      pages: [],
      imageProvider: 'profile',
      imageModel: '',
      factualBiography: false,
    }],
  }
}

export function exampleTurnIsUseful(kind: ExampleKind, actions: AgentAction[]): boolean {
  if (kind === 'video') return actions.some(action => action.type === 'prepare_video' && action.prompt.trim().length > 40)
  if (kind === 'image') return actions.some(action => action.type === 'prepare_image' && action.prompt.trim().length > 20)
  if (kind === 'audio') return actions.some(action => action.type === 'prepare_audio' && action.prompt.trim().length > 20)
  if (kind === 'sfx') return actions.some(action => action.type === 'queue_sfx_pack' && action.clips.length > 0)
  if (kind === '3d') return actions.some(action => action.type === 'prepare_3d' && action.prompt.trim().length > 20)
  if (kind === 'story') return actions.some(action => action.type === 'create_story' && action.title.trim().length > 3)
  if (kind === 'series') return actions.some(action => action.type === 'create_series_episode' && action.episodeTitle.trim().length > 3)
  return actions.some(action => action.type === 'create_comic' && action.title.trim().length > 3)
}

export function maybeExampleTurn(
  request: string,
  turn: AgentTurn,
  history: ExampleConversation[],
): AgentTurn | null {
  const kind = inferExampleKind(request, history)
  if (isExampleRequest(request)) {
    if (!kind) {
      return {
        reply: 'Claro, invento un ejemplo. ¿De qué sección: vídeo, imagen, audio, SFX, 3D, historia, serie o cómic?',
        actions: [],
      }
    }
    const salt = exampleSalt(kind, request, history)
    const example = exampleActionsFor(kind, salt, history)
    if (exampleTurnIsUseful(kind, turn.actions) && !usedInHistory(history, exampleLabel(turn.actions))) {
      return ensureExampleExecutes(kind, turn)
    }
    return example
  }
  if (kind && isBareCreateRequest(request, kind)) {
    return {
      reply: BARE_ASK[kind],
      actions: [{ type: 'open_tab', tab: SECTION_TAB[kind] }],
    }
  }
  return null
}

function exampleLabel(actions: AgentAction[]): string {
  for (const action of actions) {
    if (action.type === 'prepare_video' || action.type === 'prepare_image' || action.type === 'prepare_audio' || action.type === 'prepare_3d') {
      return action.prompt.slice(0, 80)
    }
    if (action.type === 'create_story') return action.title
    if (action.type === 'create_series_episode') return action.episodeTitle
    if (action.type === 'create_comic') return action.title
  }
  return ''
}

function ensureExampleExecutes(kind: ExampleKind, turn: AgentTurn): AgentTurn {
  const needsStart = kind === 'video' || kind === 'image' || kind === 'audio' || kind === '3d'
  if (!needsStart) return turn
  const hasStart = turn.actions.some(action => action.type === 'start_generation')
  if (hasStart) return turn
  return { ...turn, actions: [...turn.actions, { type: 'start_generation', confirm: true }] }
}
