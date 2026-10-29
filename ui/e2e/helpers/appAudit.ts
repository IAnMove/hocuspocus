import fs from 'node:fs/promises'
import { expect, type Page, type TestInfo } from '@playwright/test'

export type FeatureEvidence = {
  id: string; title: string; route: string[]; screenshot: string; status: 'passed' | 'failed'; error?: string
  wizard: { support: 'registered' | 'partial' | 'manual'; actions: string[]; example: string; note: string }
}

const wizardRoutes: Record<string, { actions: string[]; example: string; support?: 'partial' | 'manual' }> = {
  'Direct generation/Image': { actions: ['prepare_image', 'start_generation'], example: 'Prepara una imagen de un taller de magos con Flux 2 Klein 9B y genérala.' },
  'Direct generation/Video': { actions: ['prepare_video', 'start_generation'], example: 'Prepara un plano de 5 segundos de un mago programando y genéralo.' },
  'Direct generation/Audio': { actions: ['prepare_audio', 'start_generation', 'queue_sfx_pack'], example: 'Crea y genera una canción instrumental de prueba con ACE-Step.' },
  'Direct generation/3D': { actions: ['prepare_3d', 'start_generation'], example: 'Prepara un objeto 3D a partir de esta imagen con Hunyuan3D Mini Turbo.' },
  'Direct generation/Edit': { actions: ['open_tab'], example: 'Abre Studio; el modo y los controles de edición se ajustan manualmente.', support: 'partial' },
  'Direct generation/Tools': { actions: ['remove_background'], example: 'Quita el fondo de la imagen indicada. Upscale y Revoice requieren controles manuales.', support: 'partial' },
  'Direct generation/Tools/Upscale': { actions: [], example: 'Selecciona el medio y el método en Tools → Upscale.', support: 'manual' },
  'Direct generation/Tools/Revoice': { actions: [], example: 'Selecciona el vídeo y las muestras de voz en Tools → Revoice.', support: 'manual' },
  'Direct generation/Tools/Remove background': { actions: ['remove_background'], example: 'Quita el fondo de esta imagen y conserva el mago.' },
  'Direct generation/Audio/Music': { actions: ['prepare_audio', 'start_generation'], example: 'Prepara una canción instrumental con ACE-Step y genérala.', support: 'partial' },
  'Direct generation/Audio/Speech': { actions: ['prepare_audio', 'start_generation'], example: 'Prepara una locución que diga exactamente «Hola, mundo» en español.', support: 'partial' },
  'Direct generation/Audio/SFX': { actions: ['queue_sfx_pack'], example: 'Prepara una colección de efectos de teclado mágico y chispas.' },
  'Direct generation/Audio/Mixer': { actions: [], example: 'Añade pistas y ajusta la mezcla manualmente en Audio → Mixer.', support: 'manual' },
  'Studios/Story Lab': { actions: ['create_story', 'update_story', 'generate_story_section', 'configure_story_song', 'generate_story_song', 'stage_story_video'], example: 'Crea una historia nueva de un mago programador, completa la premisa y guárdala.' },
  'Studios/Series Lab': { actions: ['create_series_episode', 'generate_series_plan', 'render_series_shots', 'assemble_series_episode'], example: 'Crea una serie de comedia tecnológica y prepara un episodio de cuatro planos.' },
  'Studios/Comics': { actions: ['create_comic', 'generate_comic', 'generate_comic_panel'], example: 'Crea un cómic nuevo de dos páginas y genera sus viñetas con MiniMax.' },
  'Studios/Character Creator': { actions: ['create_character_kit', 'attach_character_kit_references', 'build_character_kit'], example: 'Crea un Character Kit de un mago con abrigo azul usando la referencia adjunta.' },
  'Studios/Video 2.5D': { actions: ['create_3d_scene', 'add_3d_scene_layer', 'apply_3d_rhythm', 'save_3d_scene', 'export_3d_scene'], example: 'Crea una escena 2.5D, añade esta imagen, guarda la escena y expórtala.' },
  'Studios/Video 3D': { actions: [], example: 'Montar GLB y editar cámaras del mundo 3D requiere el editor.', support: 'manual' },
  'Direct generation/Edit/Replace character': { actions: ['open_tab'], example: 'Abre Generación directa → Editar → Cambiar personaje y selecciona el vídeo y el fotograma.', support: 'manual' },
  'Studios/Animate': { actions: ['open_character_kit_rig'], example: 'Abre el rig del Character Kit. Los ajustes de animación necesitan controles manuales.', support: 'partial' },
  'Production/Director': { actions: ['stage_story_video', 'stage_story_music_video', 'start_director_production'], example: 'Prepara el videoclip de la canción seleccionada y lanza la producción.' },
  'Production/Video Editor': { actions: ['create_video_editor_project', 'add_video_editor_clips', 'trim_video_editor_clip', 'add_video_editor_audio', 'export_video_editor'], example: 'Crea un montaje con estos dos vídeos, añade esta canción y expórtalo.' },
  'Workspaces': { actions: ['create_workspace_collection', 'update_workspace_collection'], example: 'Crea una colección de trabajo con estos assets y una nota sobre el proyecto.' },
  'Activity': { actions: ['inspect_queue', 'cancel_task', 'retry_task', 'resume_task'], example: 'Muestra la cola y el estado de las tareas de esta carpeta.' },
  'Settings': { actions: ['open_tab', 'download_model'], example: 'Abre Settings. Los proveedores, preferencias y credenciales se configuran manualmente.', support: 'partial' },
  'Mobile navigation': { actions: [], example: 'Desliza la fila de secciones y pulsa el destino deseado.', support: 'manual' },
}

export function wizardEvidence(route: string[]): FeatureEvidence['wizard'] {
  const key = route.join('/'), entry = wizardRoutes[key]
  if (entry) return { ...entry, support: entry.support ?? 'registered', note: 'Contrato inspeccionado en el registro de capacidades. La captura verifica UI; sólo un caso con traza y resultado acredita ejecución real del Wizard.' }
  if (route[0] === 'Direct generation' && route[1] === 'Edit') return { support: 'manual', actions: [], example: `Selecciona la fuente y ajusta ${route.at(-1)} en el panel de edición.`, note: 'No se identifica una capacidad dedicada prepare_edit en el registro inspeccionado.' }
  return { support: 'partial', actions: ['open_tab'], example: `Abre ${route.at(-1)}; algunos filtros se ajustan manualmente.`, note: 'Navegación parcial. No se certifica una acción específica para cada filtro con esta captura.' }
}

export async function openAuditApp(page: Page, workspace?: string) {
  page.setDefaultTimeout(20_000)
  await page.goto('/')
  await page.getByRole('button', { name: 'Skip', exact: true }).click({ timeout: 8_000 }).catch(() => undefined)
  await expect(page.getByRole('button', { name: 'Studios', exact: true })).toBeVisible()
  if (workspace) await expect(page.getByRole('button', { name: `Switch output folder: ${workspace}`, exact: true })).toBeVisible()
  const close = page.getByRole('button', { name: 'Close Ask to the Wizard', exact: true })
  await close.waitFor({ state: 'visible', timeout: 15_000 }).catch(() => undefined)
  // The panel's entrance animation can keep the visible icon moving for a
  // moment after the main navigation is ready. This is test setup, so force
  // the already-resolved button click instead of misreporting a tour failure.
  if (await close.isVisible()) await close.click({ force: true })
}

export async function captureFeature(page: Page, info: TestInfo, records: FeatureEvidence[], route: string[], action: () => Promise<void>) {
  const id = String(records.length + 1).padStart(2, '0') + '-' + route.join('-').toLowerCase().replace(/[^a-z0-9]+/g, '-')
  const screenshot = `${id}.png`
  let error: string | undefined
  try { await action() } catch (cause) { error = cause instanceof Error ? cause.message : String(cause) }
  await page.screenshot({ path: info.outputPath(screenshot), fullPage: true, animations: 'disabled' })
  const record: FeatureEvidence = { id, title: route.at(-1)!, route, screenshot, status: error ? 'failed' : 'passed', error, wizard: wizardEvidence(route) }
  records.push(record)
  await fs.writeFile(info.outputPath('features.json'), JSON.stringify(records, null, 2))
  console.log(`[feature] ${record.status}: ${route.join(' → ')}`)
  expect.soft(error, route.join(' → ')).toBeUndefined()
}
