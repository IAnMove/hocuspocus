/** Newest first. One short line per merged PR; bump the first `pr` to re-show the welcome. */
export const WHATS_NEW: Array<{ pr: number; en: string; es: string }> = [
  { pr: 453, en: 'Wizard and MCP can edit with Qwen 2.1', es: 'Wizard y MCP editan con Qwen 2.1' },
  { pr: 448, en: 'Qwen Image 2.1: t2i+edit, 2K, RGBA', es: 'Qwen Image 2.1: t2i+edición, 2K, RGBA' },
  { pr: 450, en: 'H3 experimental 30-second clips', es: 'H3 experimental a 30 segundos' },
  { pr: 449, en: 'Studio and Story bugfixes', es: 'Correcciones de Studio y Story' },
  { pr: 447, en: 'Studio and Story bugfixes', es: 'Correcciones de Studio y Story' },
  { pr: 442, en: 'Studio audio submit extracted', es: 'Envío de audio de Studio aparte' },
  { pr: 446, en: 'Critical bugfixes', es: 'Correcciones críticas' },
  { pr: 445, en: 'Keep published songs on merge', es: 'Canciones publicadas al fusionar' },
  { pr: 444, en: 'Safer Story merge', es: 'Fusión de historias más segura' },
  { pr: 443, en: 'Video editor time cards', es: 'Tarjetas de tiempo en el editor' },
  { pr: 441, en: 'Story library router', es: 'Router de librería de Story' },
  { pr: 440, en: 'Repair persistence', es: 'Persistencia de reparaciones' },
  { pr: 438, en: 'Character kit library router', es: 'Router de librería de kits' },
  { pr: 439, en: 'Pipeline repair plan', es: 'Plan de reparación del pipeline' },
  { pr: 436, en: 'Validated H3 candidate', es: 'Candidato H3 validado' },
  { pr: 437, en: 'Series library router', es: 'Router de librería de Series' },
  { pr: 435, en: 'H3 Story prompt contracts', es: 'Contratos de prompt H3 Story' },
  { pr: 433, en: 'Studio H3 policy', es: 'Política H3 de Studio' },
  { pr: 434, en: 'Comic shot identity', es: 'Identidad de plano en cómic' },
  { pr: 432, en: 'Story music generation record', es: 'Registro de generación de música' },
  { pr: 431, en: 'Director reconcile observer', es: 'Observer de conciliación de Director' },
  { pr: 430, en: 'Studio music slice', es: 'Slice de música de Studio' },
  { pr: 428, en: 'Story session store', es: 'Store de sesión de Story' },
  { pr: 429, en: 'Wizard concurrency', es: 'Concurrencia del Wizard' },
  { pr: 427, en: 'Director locks', es: 'Bloqueos de Director' },
  { pr: 426, en: 'Story music router', es: 'Router de música de Story' },
  { pr: 425, en: 'Scene3D complexity vs main', es: 'Complejidad de Scene3D vs main' },
  { pr: 419, en: 'Dark-fantasy cutout scenes', es: 'Escenas recortables dark fantasy' },
  { pr: 423, en: 'YuE2/AuK recipe on tab return', es: 'Receta YuE2/AuK al volver de pestaña' },
  { pr: 421, en: 'YuE2 and AuK native audio', es: 'Audio nativo YuE2 y AuK' },
  { pr: 417, en: 'Custom character voices', es: 'Voces de personaje propias' },
  { pr: 416, en: 'Nine-mouth speech preview', es: 'Vista previa de 9 bocas' },
  { pr: 412, en: 'In-app help tutorial', es: 'Tutorial de ayuda en la app' },
  { pr: 413, en: 'Series Wizard production', es: 'Producción del Wizard de Series' },
  { pr: 407, en: 'Hocus lip-sync fix', es: 'Arreglo de lip-sync Hocus' },
]

export const WELCOME_SEEN_KEY = 'hocuspocus_welcome_seen_v2'

export function latestWhatsNewPr(): number {
  return WHATS_NEW[0]?.pr ?? 0
}
