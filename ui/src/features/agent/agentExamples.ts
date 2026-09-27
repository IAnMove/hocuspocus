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
  video: 'Sure. What should the video be about? If you have no topic, say **make me an example** and I will invent one and queue it.',
  image: 'Sure. What image do you want? If you have no topic, say **make me an example** and I will invent one and queue it.',
  audio: 'Sure. What music or voice do you want? If you have no topic, say **make me an example** and I will invent one (ACE-Step, no video).',
  sfx: 'Sure. Which sound effects? If you have no topic, say **make me an example** and I will queue a short pack.',
  '3d': 'Sure. What 3D object do you want? If you have no topic, say **make me an example** and I will invent one in Hunyuan3D.',
  story: 'Sure. What should the story be about? If you have no topic, say **make me an example** and I will fill in all of Story Lab.',
  series: 'Sure. Which series or episode? If you have no topic, say **make me an example** and I will fill in Series Lab.',
  comic: 'Sure. What should the comic be about? If you have no topic, say **make me an example** and I will fill in panels and balloons.',
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
    title: 'The Shoreline Lantern',
    premise: 'A retired lighthouse keeper finds a lantern that shows harbours that do not exist yet.',
    logline: 'To save her village from the fog, she must decide which future to light.',
    synopsis: 'Marta discovers the lantern predicts the tides. Every use brings an impossible harbour closer and pulls her grandson away from the present.',
    theme: 'Choosing a future has a cost in the present.',
    ending: 'She puts out the lantern and teaches her grandson to read the real stars.',
    genre: 'Fantasy drama',
    tone: 'Warm and nocturnal',
    visualStyle: 'Coastal slice-of-life, oil lamps, blue fog.',
    characters: [
      { name: 'Marta', role: 'Protagonist', personality: 'Practical', desire: 'Protect the lighthouse', flaw: 'Never asks for help', appearance: 'Wool coat, short white hair', voice: 'Low and clear' },
      { name: 'Nil', role: 'Grandson', personality: 'Curious', desire: 'See the harbour of the future', flaw: 'Impatient', appearance: 'Yellow jacket', voice: 'Quick' },
    ],
    locations: [{ name: 'Lighthouse', purpose: 'Conflict', description: 'White tower on a damp cliff' }],
    outlineBeats: ['Marta finds the lantern', 'Nil sees an impossible harbour', 'They put out the lantern together'],
  },
  {
    title: 'The Tuesday Tram',
    premise: 'A musician discovers that the 7:12 tram stops time just for him.',
    logline: 'He has a song to finish before time starts moving again.',
    synopsis: 'Oriol uses the frozen tram to rehearse. One day another passenger is awake too.',
    theme: 'Art cannot be kept in an eternal pause.',
    ending: 'He plays the song in motion and lets the tram move on.',
    genre: 'Magical comedy',
    tone: 'Light and bittersweet',
    visualStyle: 'Rainy Barcelona, tram yellows, soft grain.',
    characters: [
      { name: 'Oriol', role: 'Protagonist', personality: 'Shy', desire: 'Finish the song', flaw: 'Avoids an audience', appearance: 'Green jumper, guitar case', voice: 'Soft' },
      { name: 'Laia', role: 'Passenger', personality: 'Direct', desire: 'Make it to a goodbye on time', flaw: 'Impatience', appearance: 'Red raincoat', voice: 'Dry but kind' },
    ],
    locations: [{ name: 'Tram 7:12', purpose: 'Time bubble', description: 'Wooden interior, fogged windows' }],
    outlineBeats: ['Time stops', 'Laia is awake', 'They play in motion'],
  },
  {
    title: 'Recipes Against the Clock',
    premise: 'A bakery inherits an oven that bakes the memory that hurts each customer most.',
    logline: 'To save the business they must serve truths nobody ordered.',
    synopsis: 'Núria and her brother learn that every order draws out a secret. The town grows closer and further apart at once.',
    theme: 'Sweetness does not erase what needs to be said.',
    ending: 'They let the oven go cold and bake the hardest order by hand.',
    genre: 'Slice-of-life drama',
    tone: 'Tender with irony',
    visualStyle: 'Display cases at dawn, icing sugar, green tiles.',
    characters: [
      { name: 'Núria', role: 'Protagonist', personality: 'Organized', desire: 'Keep the bakery open', flaw: 'Controls too much', appearance: 'Cocoa-stained apron', voice: 'Quick' },
      { name: 'Ivo', role: 'Brother', personality: 'Chaotic', desire: 'Bring people back', flaw: 'Says too much', appearance: 'Cap and flour in his hair', voice: 'Warm' },
    ],
    locations: [{ name: 'Bakehouse', purpose: 'Magic engine', description: 'Stone oven, clock stopped at 6:05' }],
    outlineBeats: ['The oven bakes a memory', 'An order breaks a secret', 'They bake without magic'],
  },
  {
    title: 'The Elevator Map',
    premise: 'A caretaker discovers the elevator opens floors the building does not have.',
    logline: 'Every extra button asks for an apology that was never given.',
    synopsis: 'Fermín rides up to floor 13½, where versions of the neighbours live. To get back, he has to deliver overdue messages.',
    theme: 'What goes unsaid also takes up space.',
    ending: 'He leaves the extra button unpressed and takes the real stairs.',
    genre: 'Urban fantasy',
    tone: 'Still and strange',
    visualStyle: 'Worn marble lobby, weak neon lights, midnight.',
    characters: [
      { name: 'Fermín', role: 'Protagonist', personality: 'Discreet', desire: 'Let the building sleep', flaw: 'Avoids conflict', appearance: 'Caretaker jacket, huge keys', voice: 'Low' },
      { name: 'Alba', role: 'Neighbour', personality: 'Insomniac', desire: 'Find her cat', flaw: 'Does not believe in oddities', appearance: 'Dressing gown and phone torch', voice: 'Dry' },
    ],
    locations: [{ name: 'Elevator 3', purpose: 'Threshold', description: 'Wooden car, a mirror that reflects one second late' }],
    outlineBeats: ['An extra button appears', 'The impossible floor', 'They deliver the apologies'],
  },
]

const SERIES_EXAMPLES = [
  {
    seriesTitle: 'Graveyard Shift',
    seriesPremise: 'Three workers at a mountain petrol station solve tiny mysteries.',
    episodeTitle: 'The Coffee That Never Cools',
    episodePremise: 'A pot of coffee stays hot until someone tells the truth.',
    episodeLogline: 'To close the shift, each of them has to confess something silly.',
    characters: [
      { name: 'Vera', role: 'Manager', personality: 'Blunt', desire: 'Close on time', flaw: 'Control', appearance: 'Cap and fleece', voice: 'Tired' },
      { name: 'Pol', role: 'New hire', personality: 'Hyperactive', desire: 'Be liked', flaw: 'Says too much', appearance: 'Orange vest', voice: 'Quick' },
      { name: 'Núria', role: 'Mechanic', personality: 'Quiet', desire: 'Peace', flaw: 'Holds grudges', appearance: 'Stained overalls', voice: 'Low' },
    ],
    locations: [{ name: 'Coll Petrol Station', purpose: 'Main set', description: 'Pump island, fog, weak neon' }],
    outlineBeats: ['The coffee never cools', 'They confess silly lies', 'The coffee steams normally'],
  },
  {
    seriesTitle: 'Rooftop Archive',
    seriesPremise: 'An archivist catalogues dreams that slip in through the city skylights.',
    episodeTitle: 'The Cat on the Fifth Floor',
    episodePremise: 'A cat delivers other people\'s dreams to the wrong letterbox.',
    episodeLogline: 'Returning each dream means climbing without the lift.',
    characters: [
      { name: 'Iris', role: 'Archivist', personality: 'Meticulous', desire: 'Order', flaw: 'Cannot improvise', appearance: 'Grey trench coat', voice: 'Precise' },
      { name: 'Teo', role: 'Doorman', personality: 'Jokey', desire: 'No weirdness', flaw: 'Denies the strange', appearance: 'Huge keys', voice: 'Warm' },
      { name: 'Mim', role: 'Cat', personality: 'Inscrutable', desire: 'Tuna', flaw: 'Chaos', appearance: 'Orange with a waistcoat', voice: 'Narrated meow' },
    ],
    locations: [{ name: 'Rooftop archive', purpose: 'Office', description: 'Skylights, cardboard boxes, wind' }],
    outlineBeats: ['Dreams in the letterbox', 'They climb floor by floor', 'The cat chooses the tuna'],
  },
  {
    seriesTitle: 'Lighthouse Radio',
    seriesPremise: 'A local station broadcasts announcements that happen five minutes later.',
    episodeTitle: 'The Cat Bulletin',
    episodePremise: 'The bulletin reports a lost cat that is still in the studio.',
    episodeLogline: 'They have to lose the cat on purpose so the bulletin comes true.',
    characters: [
      { name: 'Rita', role: 'Presenter', personality: 'Sweet', desire: 'Never lie on air', flaw: 'Gets tongue-tied', appearance: 'Huge headphones', voice: 'Warm radio voice' },
      { name: 'Grau', role: 'Engineer', personality: 'Cynical', desire: 'Nothing breaks', flaw: 'Denies the strange', appearance: 'Overalls and duct tape', voice: 'Dry' },
      { name: 'Pipa', role: 'Mascot cat', personality: 'Diva', desire: 'Attention', flaw: 'Hides badly', appearance: 'White with a patch over one eye', voice: 'Eloquent silence' },
    ],
    locations: [{ name: 'Lighthouse Radio booth', purpose: 'Set', description: 'Mixing desk, window onto the harbour, red neon' }],
    outlineBeats: ['The bulletin runs early', 'They try to lose the cat', 'The cat goes back on air'],
  },
  {
    seriesTitle: 'Museum at 8:03',
    seriesPremise: 'The night guards of a small museum negotiate with the artworks when nobody is looking.',
    episodeTitle: 'The Chair That Sits',
    episodePremise: 'A designer chair refuses to return to its plinth until someone uses it properly.',
    episodeLogline: 'The shift ends if they get a human to sit without breaking protocol.',
    characters: [
      { name: 'Dani', role: 'Guard', personality: 'Anxious', desire: 'A quiet shift', flaw: 'Follows rules to the letter', appearance: 'Crumpled uniform', voice: 'Whisper' },
      { name: 'Ona', role: 'Conservator', personality: 'Brave', desire: 'Understand the pieces', flaw: 'Touches too much', appearance: 'Gloves and head torch', voice: 'Firm' },
      { name: 'Chair 14', role: 'Artwork', personality: 'Offended', desire: 'Be useful', flaw: 'Dramatic', appearance: 'Light wood, long legs', voice: 'Elegant creak' },
    ],
    locations: [{ name: 'Design gallery', purpose: 'Conflict', description: 'Plinths, red sensors, parquet floor' }],
    outlineBeats: ['The chair climbs down', 'They negotiate a seat', 'It returns to the plinth'],
  },
]

const COMIC_EXAMPLES = [
  {
    title: 'Antenna Soup',
    synopsis: 'Two neighbours argue whether the rooftop antenna cooks better than they do.',
    styleName: 'Newspaper strip, clean ink, 4 panels',
    characters: [
      { name: 'Rosa', role: 'Neighbour', description: 'Polka-dot dressing gown, wooden spoon' },
      { name: 'Quim', role: 'Neighbour', description: 'Cap, toy binoculars' },
    ],
    panels: [
      { caption: 'Tuesday, rooftop.', dialogue: 'The soup tastes weird.', sfx: '' },
      { caption: '', dialogue: 'The antenna has its own recipe.', sfx: 'BEEP' },
      { caption: '', dialogue: 'Shall we add bread?', sfx: '' },
      { caption: 'The end.', dialogue: 'Let\'s just order pizza.', sfx: 'DING' },
    ],
  },
  {
    title: 'The Frozen Bell',
    synopsis: 'Break never ends because the school bell has turned into a snowman.',
    styleName: 'Children\'s comic, flat colours, 4 panels',
    characters: [
      { name: 'Mar', role: 'Pupil', description: 'Huge scarf, frog backpack' },
      { name: 'Bell', role: 'Soft antagonist', description: 'A bell with snowy arms' },
    ],
    panels: [
      { caption: 'Playground.', dialogue: 'Can nobody hear the bell?', sfx: '' },
      { caption: '', dialogue: 'I\'m on holiday.', sfx: 'BRRR' },
      { caption: '', dialogue: 'We\'ll give you a hat.', sfx: '' },
      { caption: 'Break wins.', dialogue: 'Five more minutes.', sfx: 'DING' },
    ],
  },
  {
    title: 'Lantern and Tide',
    synopsis: 'A lighthouse keeper argues with the tide because it keeps moving his chairs.',
    styleName: 'Short graphic novel, watercolour, 4 panels',
    characters: [
      { name: 'Leo', role: 'Lighthouse keeper', description: 'Raincoat, salt-crusted moustache' },
      { name: 'Tide', role: 'The sea personified', description: 'A wave wearing a hat' },
    ],
    panels: [
      { caption: 'Pier.', dialogue: 'Give me back my chair.', sfx: '' },
      { caption: '', dialogue: 'It\'s mine at high tide.', sfx: 'SPLASH' },
      { caption: '', dialogue: 'Then I\'ll lend you the lighthouse.', sfx: '' },
      { caption: 'Deal.', dialogue: 'Until low tide.', sfx: 'FOG' },
    ],
  },
  {
    title: 'Cat in the Printer',
    synopsis: 'The office cat becomes the official toner.',
    styleName: 'Office webcomic, clean line, 4 panels',
    characters: [
      { name: 'Beto', role: 'Intern', description: 'Checked shirt, endless coffee' },
      { name: 'Pixel', role: 'Cat', description: 'Grey, sits on everything' },
    ],
    panels: [
      { caption: 'Monday.', dialogue: 'The printer wants toner.', sfx: '' },
      { caption: '', dialogue: 'I am the toner.', sfx: 'Prrr' },
      { caption: '', dialogue: 'Will you print the report?', sfx: '' },
      { caption: 'Delivered.', dialogue: 'It comes out covered in fur.', sfx: 'CLUNK' },
    ],
  },
  {
    title: 'The Shy Traffic Light',
    synopsis: 'A traffic light will not turn green because the crossing makes it shy.',
    styleName: 'Urban strip, pastel, 4 panels',
    characters: [
      { name: 'Luz', role: 'Traffic light', description: 'Thin pole, imaginary glasses' },
      { name: 'Eva', role: 'Cyclist', description: 'Yellow helmet, basket of bread' },
    ],
    panels: [
      { caption: 'Crossing.', dialogue: 'Are you going to turn green?', sfx: '' },
      { caption: '', dialogue: 'People are watching.', sfx: 'TICK' },
      { caption: '', dialogue: 'I\'ll close my eyes.', sfx: '' },
      { caption: 'They cross.', dialogue: 'A shy green.', sfx: 'DING' },
    ],
  },
  {
    title: 'Cloud Library',
    synopsis: 'A librarian fines a cloud for returning the rain late.',
    styleName: 'Poetic children\'s, soft watercolour, 4 panels',
    characters: [
      { name: 'Vera', role: 'Librarian', description: 'Wool jumper, enormous stamp' },
      { name: 'Cloud 7', role: 'Reader', description: 'A cloud with reading glasses' },
    ],
    panels: [
      { caption: 'Children\'s room.', dialogue: 'This shower is due back today.', sfx: '' },
      { caption: '', dialogue: 'My calendar clouded over.', sfx: 'PITTER' },
      { caption: '', dialogue: 'Fine: one rainbow.', sfx: '' },
      { caption: 'Returned.', dialogue: 'With a sunshine bookmark.', sfx: 'SHHH' },
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
      reply: `I'll invent a different example video and send it to the queue.\n\n**Prompt:** ${prompt}`,
      actions: [
        { type: 'prepare_video', prompt, durationSeconds: 5, resolutionPreset: '720p', aspectRatio: '16:9', seed: -1, outputCount: 1 },
        { type: 'start_generation', confirm: true },
      ],
    }
  }
  if (kind === 'image') {
    const prompt = pickExample(IMAGE_EXAMPLES, salt, item => usedInHistory(history, item))
    return {
      reply: `I'll invent an example image and send it to the queue.\n\n**Prompt:** ${prompt}`,
      actions: [
        { type: 'prepare_image', prompt, resolutionPreset: 'auto', aspectRatio: 'auto', seed: -1, outputCount: 1 },
        { type: 'start_generation', confirm: true },
      ],
    }
  }
  if (kind === 'audio') {
    const example = pickExample(AUDIO_EXAMPLES, salt, item => usedInHistory(history, item.prompt))
    return {
      reply: `I'll invent an example audio piece in Studio → Audio → Music (ACE-Step, **no video**).\n\n**Prompt:** ${example.prompt}`,
      actions: [
        { type: 'prepare_audio', subMode: 'music', prompt: example.prompt, durationSeconds: example.durationSeconds },
        { type: 'start_generation', confirm: true },
      ],
    }
  }
  if (kind === 'sfx') {
    const clips = pickExample(SFX_PACKS, salt, pack => pack.some(clip => usedInHistory(history, clip.name)))
    return {
      reply: 'I\'ll invent a short example SFX pack and queue it. Remember: MMAudio still produces an LTX video for each clip; it is not an audio-only generator.',
      actions: [{ type: 'queue_sfx_pack', style: 'example pack', clips, confirm: true }],
    }
  }
  if (kind === '3d') {
    const prompt = pickExample(MODEL3D_EXAMPLES, salt, item => usedInHistory(history, item))
    return {
      reply: `I'll invent an example 3D object in Hunyuan3D and send it to generate.\n\n**Prompt:** ${prompt}`,
      actions: [
        { type: 'prepare_3d', prompt, preset: 'balanced', seed: hashSalt(salt) % 10_000 },
        { type: 'start_generation', confirm: true },
      ],
    }
  }
  if (kind === 'story') {
    const story = pickExample(STORY_EXAMPLES, salt, item => usedInHistory(history, item.title))
    return {
      reply: `I'll invent and save an example story in Story Lab: **${story.title}**.`,
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
        language: 'English',
        characters: story.characters,
        locations: story.locations,
        outlineBeats: story.outlineBeats,
      }],
    }
  }
  if (kind === 'series') {
    const episode = pickExample(SERIES_EXAMPLES, salt, item => usedInHistory(history, item.episodeTitle))
    return {
      reply: `I'll invent and save an example episode in Series Lab: **${episode.seriesTitle} / ${episode.episodeTitle}**.`,
      actions: [{
        type: 'create_series_episode',
        seriesTitle: episode.seriesTitle,
        seriesPremise: episode.seriesPremise,
        seriesLogline: episode.episodeLogline,
        episodeTitle: episode.episodeTitle,
        episodePremise: episode.episodePremise,
        episodeLogline: episode.episodeLogline,
        genre: 'Comedy',
        tone: 'Warm',
        visualStyle: 'Simple cinematic sitcom',
        worldSummary: episode.seriesPremise,
        theme: 'Shifts and small secrets',
        ending: episode.outlineBeats[episode.outlineBeats.length - 1],
        language: 'English',
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
    reply: `I'll invent a different example comic and fill in panels and balloons: **${comic.title}**. I won't draw the panels yet: say **launch it** or press **Generate all images** in Comic Director.`,
    actions: [{
      type: 'create_comic',
      title: comic.title,
      synopsis: comic.synopsis,
      language: 'English',
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
        reply: 'Sure, I\'ll invent an example. For which section: video, image, audio, SFX, 3D, story, series or comic?',
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
