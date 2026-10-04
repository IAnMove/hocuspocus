# Serie animada estilo South Park por MCP: problemas encontrados y cómo arreglarlos

Fecha: 2026-10-04. Rama: `feat/series-ai-valley-voices` (desde `development` 2bf5f4e6).

## Qué se hizo

Se produjo por MCP, sin generación de vídeo con IA, el episodio piloto **«Uncanny Valley» 1x01 «It's Just a Wrapper»** en inglés y su versión en español **«Valle Inquietante» 1x01 «Solo es un wrapper»**:

- 6 personajes con Character Kit: Kevin y Gary (originales) y caricaturas paródicas de Elon, Sam, Dario y Jensen. Cada uno tiene pose base y poses extra, 9 bocas de recorte de papel y parpadeo.
- 12 voces locales, una por personaje e idioma. Cada voz se diseñó con Qwen3 VoiceDesign a partir de una descripción de rasgos; no se clonó la voz de ninguna persona real. Después cada línea se clonó desde esa referencia con Qwen3 Base.
- 51 planos: 49 en Video 2D con lip-sync fonético, 2 en Video 3D con los personajes recortados dentro del mundo 3D, y fondos 3D animados usados como capa de vídeo en los planos 2D.
- 136 líneas de diálogo, verificadas con Whisper y sincronizadas con el motor de fonemas.
- Música (ACE-Step) y efectos (MMAudio) locales.
- Dos series en Series Lab (`uv-en`, `uv-es`), con su capítulo ensamblado en **Capítulos**:
  - inglés: 4:52;
  - español: 5:32 (el castellano ocupa un 20 % más de tiempo hablado: 236 s frente a 197 s).

Este documento recoge cada obstáculo que apareció por el camino, en orden de impacto, con su causa y la corrección propuesta. Los marcados **[ARREGLADO]** quedan resueltos en esta rama. Los marcados **[FASE 1A]** se resuelven en `fix/series-phase1-issues` (plan: `SERIES_ANIMADAS_PLAN_2026-10-04.md`).

## Resumen

| # | Problema | Impacto | Estado |
|---|---|---|---|
| 1 | `tools/list` del MCP fallaba con `'mutation'` | Ningún cliente MCP podía descubrir herramientas | **[ARREGLADO]** |
| 2 | Series Lab sin herramientas MCP | No se podía crear la serie ni el capítulo por MCP | **[ARREGLADO]** (`series.*`) |
| 3 | Character Kits sin herramientas MCP | Personajes y voces solo por HTTP o navegador | **[ARREGLADO]** (`characters.*`) |
| 4 | Una sola voz por personaje | Imposible doblar la serie | **[ARREGLADO]** (`voicesByLanguage`) |
| 5 | Lip-sync recibía «Español de España» en vez de `es` | El motor de fonemas fallaba en series en español | **[ARREGLADO]** |
| 6 | Sin herramientas de escena para «montar personaje» y «añadir línea con lip-sync» | El agente tuvo que ejecutar código TypeScript de la UI | **[FASE 2]** |
| 7 | Una serie tiene un solo idioma; no hay versiones de un capítulo | Hicieron falta dos series | Propuesta |
| 8 | La cola reordena por duración declarada y deja sin turno a la voz | Las voces esperaron detrás de cada imagen nueva | **[FASE 1A]** envejecimiento y `priority` documentado |
| 9 | El servidor llegó a 50 GB de RAM y lo mató el sistema | Cola perdida en mitad de la producción | **[FASE 1A]** causa medida y corregida; queda el presupuesto por familia |
| 10 | TTS: ninguna voz predefinida en español; VoiceDesign no es tipo de voz | Hubo que diseñar, comprobar y clonar a mano | **[FASE 1B]** «Diseñar voz» y `qa.speech` |
| 11 | En Video 3D los recortes 2D no pueden hablar | Diálogo en 3D solo con modelos GLB | Propuesta |
| 12 | Efectos de pantalla sin `color` rompen el pintor | Previsualización y export fallan | **[FASE 1A]** |
| 13 | Inconsistencias de contrato MCP | Errores evitables en cada herramienta nueva | **[FASE 1A]** salvo la miniatura 3D |
| 14 | Otros problemas menores | Ver el detalle | **[FASE 1A]** 2, 4, 7, 8 y 9 |

## 1. `tools/list` caía para todos los clientes **[ARREGLADO]**

**Síntoma.** `tools/list` devolvía `isError: true` con el texto `'mutation'`. Un cliente MCP estándar (Claude Code, Cursor, el Wizard externo) no veía ninguna herramienta. Solo funcionaba quien ya conocía los nombres.

**Causa.** `routers/wangp_mcp.py::_command_tool` leía `operation['mutation']`. Los catálogos de `audio.*` (song_analysis, speech_file_commands, phoneme_commands), `qa.lipsync` y `production.*` no declaran ese campo.

**Arreglo en la rama:**

- `_command_tool` usa `operation.get('mutation', True)`. Si un catálogo olvida el campo, la herramienta se trata como mutación, la lectura conservadora, y el listado completo nunca cae.
- Las herramientas de solo lectura declaran `mutation: False`: `audio.mouth_cues`, `audio.phoneme_cues`, `qa.lipsync`, `production.status` y `production.plan`. Así su anotación `readOnlyHint` es correcta y no sugieren un `intent_id` que su esquema rechaza.
- Test: `tests/test_wangp_mcp.py::test_a_catalog_without_a_mutation_flag_still_lists_every_tool`.

**Siguiente paso recomendado.** Un test que recorra todos los catálogos registrados en `_launch_runtime.py` y exija `mutation` explícito. El fallo se habría detectado en el PR que lo introdujo.

## 2. Series Lab no tenía MCP **[ARREGLADO]**

**Síntoma.**

- No existía ninguna herramienta `series.*` ni `episode.*`.
- Crear la serie, aprobar el canon, crear el capítulo, importar tomas, aprobarlas y ensamblar solo era posible por HTTP (`/api/v1/series/...`) o con el Wizard dentro del navegador.
- «Generar todo» (el lote nativo 2D) se ejecuta en la pestaña del navegador (`ui/src/features/series/nativeBatch.ts`); si se cierra la pestaña, se para.

**Arreglo en la rama.** `app/services/series_commands.py` es una proyección fina de los endpoints HTTP existentes. Mantiene las mismas validaciones, revisiones y bloqueos.

| Herramienta | Qué hace |
|---|---|
| `series.list`, `series.get` | Resumen y proyecto completo |
| `series.create`, `series.update` | Crear o reemplazar con revisión exacta |
| `series.canon.approve` | Aprobar el canon revisado |
| `series.episode.create`, `series.episode.update` | Capítulo, guion y planos |
| `series.asset.import` | Referencias de personaje o localización, o una toma (`as_take`) desde un fichero del workspace. Copia el fichero a `uploads/`, porque el endpoint de importación solo lee de ahí |
| `series.take.approve` | Aprobar una toma |
| `series.assembly.start`, `series.assembly.status` | Ensamblar el capítulo, que aparece en **Capítulos** |

El episodio de este documento se creó entero con estas herramientas. Tests en `tests/test_series_commands.py`.

**Pendiente:**

- Llevar al servidor el lote «Generar todo»: voz → escena → lip-sync → export → toma. Hoy solo existe en el navegador. Con un `series.episode.render_native` servidor, un agente o un usuario con la pestaña cerrada podrían producir capítulos nuevos de la serie.
- Hoy un agente debe reimplementar lo que hace `prepareNativeDraft` (`nativeDraftScene.ts`).

## 3. Character Kits sin MCP **[ARREGLADO]**

**Síntoma.** Por MCP solo existía `lips.*`, que crea colecciones de bocas y las aplica a un personaje ya existente. No había forma de crear un personaje, sus poses, sus anclajes de boca y ojos, ni su voz. Hubo que usar `PATCH /api/v1/character-kits/library/kits/{id}`.

**Arreglo en la rama.** Nuevas herramientas `characters.list`, `characters.get` y `characters.save`. `characters.save` es create/update con `base_revision`. El servidor sigue normalizando con `normalize_character_kit`, por lo que descarta en silencio los campos que no conoce.

**Pendiente:** que `characters.save` devuelva la lista de campos descartados. Un agente que envía `voicesByLanguage` a un servidor antiguo hoy no recibe ningún aviso.

## 4. Una voz por personaje: voces por idioma **[ARREGLADO]**

**Síntoma:**

- `CharacterKit.voice` era una única voz.
- Para doblar la serie había que duplicar cada personaje (`kevin-en`, `kevin-es`), duplicar el rig de bocas y enlazar la serie al duplicado.
- Además, el backend descartaba cualquier campo nuevo (`normalize_character_kit` construye su resultado con una lista de campos permitidos).

**Arreglo en la rama:**

- **Modelo de datos.** `voicesByLanguage: { english?: Voice, spanish?: Voice, … }` vive junto a `voice`, que queda como voz por defecto.
  - Las claves son los mismos nombres de idioma que ya usa el selector de Qwen3 (`english`, `spanish`, `french`…).
  - Una voz de referencia (`qwen3_tts_base`) asignada a un idioma debe hablar ese idioma o `auto`.
  - Ficheros: `app/services/character_speech_definition.py`, `app/services/character_kit_library.py`, `ui/src/lib/characterVoice.ts`.
- **Resolución.** `characterVoiceFor(kit, idioma)` acepta «Español de España», `es-ES`, `spanish` o `es`. Devuelve la voz de ese idioma o, si no la hay, la voz por defecto. La usan:
  - el lote nativo de Series (`nativeDraftScene.ts`), con el idioma hablado de la serie;
  - la previsualización de habla de Face Rig y de Lips;
  - la generación de líneas en Video 3D (`Scene3DSpeakerControls`), según el idioma del clip;
  - el resumen del personaje y el estado de voz de la serie.
- **Creador de personajes.** Nueva sección «Voces por idioma» (`CharacterLanguageVoices.tsx`):
  - añadir o quitar un idioma;
  - elegir una voz predefinida, grabar o importar una referencia (empieza ya en ese idioma);
  - reutilizar una voz de idioma guardada en otro personaje;
  - la prueba de voz lee la frase de muestra en el idioma de esa voz.
- **Video 3D.** El slot de personaje conserva `voicesByLanguage`.
- **Tests:**
  - Python: `tests/test_character_language_voices.py`.
  - UI: `ui/tests/characterLanguageVoices.test.tsx`.
  - Se ejecutaron 736 tests de Python de series, personajes, habla y MCP, y la batería completa de la UI.

## 5. El lip-sync de Series recibía etiquetas de idioma **[ARREGLADO]**

**Síntoma.** `nativeBatch.ts` pasaba `series.language` («Español») al análisis de voz.

- El motor de fonemas hacía `EspeakBackend("Español")` y fallaba («CPU phoneme alignment failed»).
- «Español de España» (17 caracteres) se rechazaba directamente: el límite es 16.
- Con Rhubarb, una serie en inglés con idioma «English» usaba el reconocedor fonético en lugar de PocketSphinx, porque compara con `en`.

**Arreglo.** `speechAnalysisLanguage()` en la UI y `speech_language_code()` en el servidor (`app/services/speech_language.py`, llamada desde `speech_alignment.analyze_voice`) convierten etiquetas en códigos. Los códigos que ya son válidos (`es`, `en-gb`, `pt-br`) pasan sin cambios.

## 6. Faltan operaciones de escena para personajes que hablan (propuesta, prioridad alta)

**Síntoma:**

- `scenes.video2d.edit` no puede escribir `keyframes`, `faceBinding`, `relationship` ni `dialogueBeats`.
- El compilador que convierte las señales fonéticas en keyframes de boca (`rebuildCutoutDialogueLayers` en `ui/src/lib/cutoutDialogue.ts`) solo existe en la UI.
- El export del servidor pinta los keyframes tal como vienen; no los recompila.
- Para que un personaje hable, el agente tiene que:
  1. reimplementar `mountCharacterKitLayers` (anclajes por pose, escalado según el tamaño de la imagen);
  2. convertir formas de Rhubarb en visemas (`parseMouthCues`);
  3. compilar los keyframes.

  En esta producción se resolvió ejecutando con `tsx` esas mismas funciones de la UI desde un script.

**Propuesta.** Añadir dos operaciones a `scenes.video2d.edit`, que se ejecuten en el mismo runtime TS que ya usa `scenes.template.compile`:

- `mount_character {kit_id, pose_id, x, y, scale, z}`: crea la capa de pose, las bocas, los ojos y el parpadeo con los ids estables `kit-<id>-…`.
- `add_line {kit_id, audio_file, text, start, language, engine}`:
  - añade la pista de audio;
  - llama a `audio.mouth_cues`;
  - crea el `dialogueBeat` con `lipSync`;
  - recompila las bocas.

Opcionalmente, `animate_talk {kit_id, style: bob|still|shake}` para la animación limitada de cuerpo, igual que `animateSeriesDraft`.

**[FASE 2] Arreglo.**

- `scenes.video2d.edit` acepta tres operaciones:
  - `mount_character {workspace, kit_id, x, framing, pose_id?, z?, motion?}`;
  - `add_line {kit_id, id, text, start, end, filename, cues?}`;
  - `animate_talk {motion?}`.
- Usan el compilador de planos de Series (`ui/scripts/seriesShot.ts`), que monta el kit con `mountCharacterKitLayers` y compila las bocas con `rebuildCutoutDialogueLayers`.
- Las señales fonéticas vienen de `audio.mouth_cues`. Sin ellas, la boca sigue el texto y la operación avisa.
- Además, `series.episode.render_native` renderiza en el servidor todos los planos 2D de un capítulo.

## 7. Un capítulo en varios idiomas (propuesta)

**Síntoma.**

- Una serie tiene un único `language`/`spokenLanguage`, y no existe el concepto de doblaje.
- Para tener el mismo capítulo en inglés y en español se crearon dos series, `uv-en` y `uv-es`, que comparten los mismos Character Kits. Con el punto 4 cada serie toma automáticamente la voz de su idioma.
- Los planos, el guion traducido y las tomas están duplicados, y un cambio de canon en una serie no llega a la otra.

**Propuesta:**

- Añadir `episode.languageVersions[]`: cada versión tiene su idioma, sus textos de diálogo (mismos ids de línea), su audio, sus tomas y su ensamblado.
- La UI muestra un selector de idioma en Planos y Resultados.
- «Generar todo» genera la versión del idioma activo.
- El ensamblado produce `…_series_assembly_<lang>.mp4`.
- Los textos de los carteles (título, cartelas) deberían salir de un diccionario por idioma.
- Opcional: fondos con rótulos localizados, porque la pizarra «RUNWAY: 3 DAYS» quedó en inglés en la versión española.

## 8. La cola deja sin turno a la voz (propuesta, prioridad alta)

**Síntoma:**

- 24 diseños de voz encolados antes que unas imágenes pasaron de la posición 12 a la 21 y se ejecutaron después de todas las imágenes enviadas más tarde.
- Las músicas de 6 s y los efectos de 2 s también se les adelantaban.

**Causa.** `services/job_lifecycle.py::_scheduled_before` ordena por prioridad, después por duración de salida declarada (la más corta primero) y después FIFO.

- Una imagen cuenta como 1 s.
- Una línea de TTS declara `duration_seconds: 20`, que es un tope y no el trabajo real.
- No hay envejecimiento de la espera, así que siempre gana la imagen.

**Lo que funcionó.** `params.priority: 10`. MCP lo acepta (`_pop_command_priority`), pero no aparece en ningún esquema ni descripción.

**Propuesta:**

1. Envejecimiento: subir la prioridad efectiva con el tiempo en cola.
2. Ordenar por coste estimado por modelo (TTS ≈ segundos, imagen 2K ≈ minutos), no por la duración de salida.
3. Documentar `priority` en los esquemas `generation.*`.
4. Exponer en `status` el motivo de la posición en cola.

**[FASE 1A]** Puntos 1 y 3:

- Un trabajo que lleva `HOCUS_QUEUE_MAX_WAIT_SECONDS` (300 s por defecto) en cola solo puede ser adelantado por una prioridad mayor.
- `tools/list` muestra `priority` en todas las herramientas `generation.*`.

Los puntos 2 y 4 siguen pendientes.

## 9. OOM del servidor al alternar modelos (propuesta, prioridad alta)

**Síntoma.** Durante la producción el proceso llegó a **50 GB de RSS** y el kernel lo mató (`oom-kill … anon-rss:50097120kB`). La cola mezclaba Qwen Image 2.1, Qwen3 TTS (VoiceDesign, Base y CustomVoice), ACE-Step XL y MMAudio.

**Consecuencias.**

- Se perdió la cola.
- Las músicas y los efectos quedaron como `jobs.leftovers` y se recuperaron con `jobs.resume`.
- Las exportaciones 3D quedaron `interrupted` y no aparecían en `leftovers`; hubo que reenviarlas.

**Propuesta:**

- Presupuesto de RAM para modelos cacheados u «offloaded»: descargar el menos usado al cambiar de familia.
- Lectura de RSS antes de cargar un modelo.
- Que las exportaciones de escena interrumpidas aparezcan en `jobs.leftovers` o tengan su propio `resume`.
- Agrupar por modelo de forma explícita y visible, en vez de alternar.

**[FASE 1A] Causa medida.** Con el servidor aislado ocioso, la RSS era de 37,8 GB. De ella, 35 GiB estaban en unos 1.000 montículos de arenas de glibc (regiones de hasta 64 MiB, alineadas a 64 MiB). No eran modelos cargados. Cada trabajo corre en su propio hilo, y los pesos liberados se quedan en la arena de ese hilo. En una prueba aparte, un fichero de pesos de 2,4 GB cargado y liberado en un hilo dejó la RSS en 2,46 GiB; `malloc_trim(0)` la bajó a 0,45 GiB.

**Arreglo:**

- `services/memory_trim.py` devuelve la memoria libre al sistema en tres momentos: al liberar el modelo de wgp, al descargar para el siguiente modelo y al terminar cada trabajo de GPU.
- `HOCUS_MALLOC_TRIM=0` lo desactiva.
- Las exportaciones de escena interrumpidas aparecen en `jobs.leftovers`. `jobs.resume` las relanza con su propio comando guardado; `jobs.discard` las cancela.

Siguen pendientes el presupuesto de RAM por familia de modelos y la agrupación por modelo.

## 10. Voces locales: lo que faltó (propuesta)

**Síntomas:**

- Las 9 voces predefinidas de Qwen3 CustomVoice no tienen ninguna nativa en español.
- `qwen3_tts_base`, necesario para guardar una voz de referencia en un personaje, no viene descargado (2,2 GB).
- VoiceDesign (voz a partir de una descripción) es el modelo más útil para crear personajes, pero no es un tipo de voz de personaje.
- Para usarlo hubo que:
  1. generar una muestra;
  2. comprobarla;
  3. guardarla como referencia (`qwen3_tts_base`) con su transcripción.

  El Creador de personajes no ofrece ese flujo.
- VoiceDesign desobedece a veces el género o el registro. Con descripciones «masculinas» dio voces a 220–350 Hz.
  - Calibración: Ryan, voz predefinida masculina, gritando el mismo texto, da 224 Hz; Serena, femenina, 282 Hz.
  - Lo resolvieron dos cambios: empezar la descripción con «Male voice.» y usar un texto de referencia calmado (Jensen bajó a 104–144 Hz).
- No hay control de calidad de voz por MCP. La inteligibilidad (WER con Whisper) y el tono (pYIN) se midieron con un script local.

**Propuesta:**

- En el Creador de personajes, opción **«Diseñar voz»**:
  - descripción e idioma;
  - genera 3 candidatas con distintas semillas;
  - muestra el tono medio y la duración y permite escucharlas;
  - la elegida se guarda como referencia con su transcripción.
- Herramienta `qa.speech {file, text, language}`: devuelve transcripción, WER, F0 mediana, palabras por segundo y silencios. Whisper ya está en `ckpts/whisper`.
- Ofrecer la descarga de `qwen3_tts_base` en el momento en que se elige «voz propia».
- Normalizar números al calcular el WER: «forty-four billion» frente a «$44 billion» disparó retomas innecesarias.

**[FASE 1B] Arreglo:**

- **«Diseñar voz».** Está en el Creador de personajes y en cada idioma del editor de voces.
  - Pide descripción, idioma y una frase de muestra tranquila, y genera tres tomas de VoiceDesign con semillas distintas.
  - Cada toma muestra su transcripción y sus métricas: WER, tono mediano y palabras por segundo.
  - Si la descripción dice hombre o mujer, avisa cuando el tono sale de un rango típico.
  - La toma elegida se guarda como voz de referencia (`qwen3_tts_base`) de ese idioma, con su transcripción.
  - Si falta un modelo, ofrece descargarlo.
- **`qa.speech`** (MCP y `POST /api/v1/qa/speech`) devuelve:
  - transcripción con Whisper small en CPU;
  - WER con números y porcentajes escritos en letra en los dos lados;
  - tono mediano, ritmo y silencios en los extremos;
  - avisos.
- **Medidas:**
  - Con las voces de referencia de la producción y su propio texto, el WER es de 0 a 0,1, en 1–2,5 s por toma.
  - En una prueba real («Lola»), las tres voces femeninas salieron a 324–353 Hz, y `qa.speech` lo avisó.

## 11. Recortes 2D que hablan dentro de Video 3D (propuesta)

**Síntoma.**

- `scenes.speech.prepare` y el pintor de bocas 3D solo admiten slots `model3d` (`app/services/scene_speech_command.py:14`).
- Un personaje de papel (`media: image`, `surface: cutout`) en un set 3D no puede mover la boca.
- Se resolvió con dos recursos:
  - planos 3D de situación sin diálogo (Elon en Marte, Jensen en la sala de servidores);
  - el set 3D renderizado como **fondo de vídeo** de planos 2D con el personaje hablando delante.

**Propuesta.** Permitir en un slot `image` con `surface: cutout`:

- `speech.mouthSprites` (las 9 bocas del Character Kit con su anclaje);
- `eyes.blink`.

El renderer 3D pintaría la boca activa sobre el plano del recorte, como hace el pintor 2D. Bastaría con reutilizar el kit del personaje.

## 12. Efectos de pantalla sin `color` rompen el pintor (propuesta, fácil)

**Síntoma.** `scenes.video2d.preview` y el export fallaban con:

`preview_paint_failed: SyntaxError: Failed to execute 'addColorStop' on 'CanvasGradient': The value provided ('undefined') …`

Pasaba con los efectos `smoke` y `dust` sin `color`.

**Causa.** El esquema (`scene2d_schema.py::_sfx`) marca `color` como opcional, pero los pintores (`stormPaint.ts`, `animePaint.ts`, `layerStyle.ts`) lo usan siempre.

**Propuesta.** Al normalizar el documento, rellenar `color` con el valor de `app/shared/scene_effects.json` (es lo que hace el editor), o que los pintores usen ese valor por defecto.

**Relacionado.** Hubo además un fallo intermitente del mismo tipo en cartelas con fuentes `marker`/`hand` que no se reprodujo al repetir; puede ser una carrera de carga de fuentes.

**[FASE 1A] Arreglo:**

- El render sin interfaz pasa los efectos por `parseSceneFx`, como el editor.
- El servidor rellena `color` con el valor del catálogo al validar y al exportar.
- La página de render cargaba las letras sin reglas `@font-face`, así que `marker` y `hand` se pintaban con `cursive`. Ahora `fonts.css` se importa también en el renderer.

## 13. Contratos MCP inconsistentes (propuesta)

| Herramienta | Inconsistencia | Propuesta |
|---|---|---|
| `jobs.wait` | Al agotar `timeout_s` responde `status: "failed"`, con el trabajo vivo dentro de `error` (`code: "timeout"`). Un cliente que lee `status` cree que falló. | Responder `status` del trabajo y `timed_out: true`, sin error. |
| `jobs.leftovers`, `jobs.resume`, `jobs.discard` | `intent_id` va al nivel superior y rechazan `input`; el resto de comandos usan `input`. `jobs.leftovers` rechaza `input: {}`. | Aceptar ambas formas. |
| `studio.key` | Rechaza `intent_id` y no tiene receipt, aunque escribe un fichero. | Aceptar `intent_id` como el resto de mutaciones. |
| `generation.music`, `generation.speech`, `generation.sfx` | Solo aceptan `version: 2`; `generation.image` acepta 1 y 2. El error no lo explica. | Mensaje con la versión válida. |
| `generation.sfx` | Ignora `output_name`: el fichero se llama `sfx_<prompt>_<seed>.wav` (`_launch_runtime.py:22641`). | Respetar `output_name`. |
| `scenes.document.save` (Video 3D) | Sin `preview`, la biblioteca 3D muestra una miniatura negra. | Generar la miniatura en el servidor con el preview existente. |
| Puerto del servidor | Si el puerto está ocupado, el servidor elige otro (42050 → 42051 → 42053) y solo lo anuncia en el log. | Escribir el puerto efectivo en `settings/server.json` o exponerlo en `media.options`. |

**[FASE 1A]** Resueltas todas menos la miniatura negra de Video 3D:

- `jobs.wait` devuelve `timed_out: true` con el trabajo vivo.
- `jobs.*` aceptan `input`.
- `studio.key` acepta `intent_id`.
- Una versión no admitida responde `unsupported_version` con `supported_versions`.
- `generation.sfx` respeta `output_name`.
- El puerto efectivo, la URL MCP y el pid se publican en `app/settings/server-endpoint.json`.
- Además, `characters.save` devuelve `ignoredFields` (problema 3), y un test exige `mutation` explícito en todos los catálogos (problema 1).

## 14. Otros problemas

1. **Tres rutas de «subir fichero»:**
   - `image_refs` exige `/api/v1/uploads/<file>` (hay que copiar a `app/uploads`);
   - `assets.upload` escribe en el workspace;
   - `series/assets/import` exige un `uploadPath` dentro de `uploads`.

   Propuesta: aceptar en todas partes una referencia canónica de workspace (`/api/v1/file/<f>?workspace=…`) o un `asset_id`.
2. **El carril de render 3D espera a la GPU.** Una exportación de Video 3D estuvo más de 40 minutos en `waiting_resource` mientras la cola de imágenes seguía llena. Propuesta: intercalar o dar prioridad a los renders cortos, o renderizar en CPU cuando la GPU está ocupada.

   **[FASE 1A]** La cabeza de la cola de generación cede la GPU a un ticket del coordinador que lleva esperando más que ella, o más de `HOCUS_GPU_WAITER_MAX_WAIT_SECONDS` (120 s por defecto). La causa era que la cabeza esperaba bloqueada en el semáforo y siempre ganaba la liberación.
3. **«Capítulos» depende del nombre del fichero.** El filtro de la galería reconoce `_series_assembly` en el nombre (`app/services/output_result_kind.py`). Un capítulo montado en el Video Editor no aparece aunque pertenezca a una serie. Propuesta: clasificar por `result_kind` del sidecar o por el vínculo `episode.assemblyAssetIds`.
4. **Imágenes con croma verde y personajes inesperados:**
   - Qwen añadió dos veces una cabeza de personaje detrás de un «escritorio estilo South Park».
   - Una GPU con detalles verdes perdió esos detalles al quitar el croma.
   - `studio.key` solo ofrece `green` o `isnet-anime`.

   Propuesta: modo de croma configurable (magenta o azul) y una advertencia cuando el sujeto contiene el color del croma.

   **[FASE 1A]** `studio.key` acepta `blue` y `magenta`, cada uno con su supresión de derrame, y un `intent_id` que reproduce el resultado guardado. La advertencia sigue pendiente.
5. **Edición con referencia que cambia el estilo.** El garaje de día generado desde el de noche con `image_refs` perdió el estilo plano (quedó acuarela). Se rehízo solo con texto.
6. **Rig de bocas para estilo plano.** Lips Creator genera bocas con el modelo de imagen. Para el estilo South Park, que es plano, fue mejor otro enfoque:
   - borrar la boca pintada con inpainting;
   - dibujar 9 bocas vectoriales parametrizadas (ancho, curvatura, sonrisa ladeada, versión «pantalla» para Gary);
   - detectar automáticamente ojos y boca (blobs blancos y trazo oscuro bajo los ojos);
   - generar el parpadeo con la forma exacta de cada ojo.

   Propuesta: llevar ese generador al Creador de personajes como «Pack de bocas planas» y «Borrar boca original». El código de referencia está en la sección de artefactos.

   **[FASE 1B]**
   - **Rig plano.** `services/flat_rig.py` (MCP `characters.rig.flat` y `POST …/kits/{id}/flat-rig`) hace todo eso en una llamada y devuelve una imagen de revisión. En los seis personajes de la producción da los mismos anclajes que el script original.
   - **Caras que no sirven.** Rechaza una cara recortada con el fondo (`face_keyed_out`) o tan clara como los ojos (`face_too_light`).
   - **Creador.** Con un estilo elegido, el Creador de personajes:
     - genera tres opciones sobre croma y las recorta;
     - guarda la elegida ya rigada;
     - añade poses nuevas con la misma identidad.
7. **Velocidad de exportación 2D.** Unos 5 s de CPU por segundo de vídeo a 1080p y 24 fps, con concurrencia 2 por defecto (`HOCUS_SCENE_EXPORT_CONCURRENCY`). Un capítulo de 5 minutos en dos idiomas tarda unos 45 minutos. Propuesta:
   - subir la concurrencia por defecto en máquinas con muchos núcleos (aquí había 32);
   - render incremental: reutilizar los planos que no cambian.

   **[FASE 1A]** Por defecto, un pintor por cada seis núcleos, entre 2 y 6 (5 con 32 núcleos); como máximo 8 si se fija a mano. La ganancia no está medida. El render incremental sigue pendiente.
8. **Ensamblado sin normalización de sonoridad.** Los capítulos salen a −19,3 y −19,6 LUFS, con un rango de 9,5 a 12,7 LU. Cada plano mezcla su audio por separado y el ensamblado concatena. Propuesta: `loudnorm` (−16 LUFS, −1 dBTP) al ensamblar, y fundidos de audio de 2–3 fotogramas en los cortes.

   **[FASE 1A]** El ensamblado aplica dos pasadas de `loudnorm` con ganancia lineal y el vídeo copiado sin recodificar. Con los capítulos reales: inglés de −19,2 a −16,1 LUFS y −1,2 dBTP; español de −19,5 a −16 LUFS; unos 16 s por capítulo. Los fundidos de audio en los cortes siguen pendientes.
9. **Subtítulos.** No se generan SRT por idioma, aunque el texto y el tiempo de cada línea son exactos (`dialogueBeats`). Propuesta: generar SRT y VTT al ensamblar.

   **[FASE 1A]** El ensamblado escribe `<capítulo>.srt` y `.vtt` con los `dialogueBeats` de cada toma, colocados con los mismos desfases que el fundido del montaje. Cada subtítulo tiene como máximo dos líneas de 42 caracteres. Con los capítulos reales: 73 subtítulos en inglés y 80 en español. Además, la energía de la voz es 3,5 veces mayor dentro de cada subtítulo que medio segundo antes.

## Artefactos de esta producción

- Workspace `uncanny-valley` de la instancia aislada:
  - Character Kits `uv-kevin`, `uv-gary`, `uv-elon`, `uv-sam`, `uv-dario` y `uv-jensen`, cada uno con voces `english` y `spanish`;
  - series `uv-en` y `uv-es`;
  - escenas `uv-<lang>-1x01-sNN-*.scene.json` (Video 2D) y `uv-1x01-*-3d-*.world3d.scene.json` (Video 3D).
- Escenas Video 3D: el plano de Marte (s10), la catedral de GPUs (s39) y dos fondos animados (Marte y sala de servidores). Estos fondos se usan como capa `video` en los planos 2D s11–s13 y s40–s43.
- Los scripts del agente (generación de imágenes y voces, rig de bocas, maquetación de planos, exportación y Series Lab por MCP) se guardaron fuera del repositorio. Son la referencia para las propuestas 6 y 14.6.

