# Handoff: ritmo musical en 3D Video + mago agente de HocusPocus

Fecha: 2026-08-29
Repositorio: `/home/ina/pinokio/api/Maestro-next.git`
Rama observada: `feat/3d-compositor-recipe`
HEAD observado al comenzar este trabajo: `17a2a06`
Destinatario principal de este handoff: Grok o el siguiente agente que continúe la sesión.

## 1. Objetivo del usuario

El usuario pidió dos líneas de trabajo relacionadas:

1. Mejorar la generación de animaciones y comenzar a conectar el ritmo de una canción MP3 con las animaciones de **3D Video**. El ejemplo explícito fue que un objeto o personaje “se asome” cada vez que hay un beat.
2. Añadir en la esquina izquierda del footer, junto al histórico/visor de actividad, un acceso con el logo de HocusPocus y el texto **Ask to the Wizard**. Este acceso debe abrir una ventana con un mago animado al que se pueda:
   - preguntar cómo funciona cualquier parte de la aplicación;
   - consultar qué hay en cola y qué se está haciendo;
   - pedir que abra la pestaña apropiada;
   - pedir que rellene campos y ejemplos visibles en la interfaz;
   - pedir que lance trabajos reales en la cola;
   - cancelar o gestionar trabajos con las confirmaciones adecuadas.

El usuario también preguntó si esto necesita un agente CLI. La recomendación acordada es que **el operador cotidiano de HocusPocus no necesita un CLI**. Debe ser un agente embebido que use el LLM configurado en la aplicación y un catálogo cerrado de herramientas. Un CLI se reservaría para un futuro **Developer Agent** capaz de editar código, con sandbox, permisos y revisión de diffs.

En el último mensaje, el usuario pidió documentarlo todo porque el contexto se acabará y continuará Grok. También pidió expresamente **no perder tiempo esperando a que terminen tests ahora**. Por tanto, este documento se crea sin volver a ejecutar pruebas.

## 2. Normas obligatorias antes de continuar

Leer completamente `AGENTS.md` antes de editar. Su flujo de seis pasos es obligatorio:

1. Reabrir `AGENTS.md` y anotar las secciones aplicables.
2. Resolver `PINOKIO_HOME` antes de tocar launchers.
3. Bloquearse a un ejemplo de `/home/ina/pinokio/prototype/system/examples` si se modifica un launcher.
4. Convertir `AGENTS.md` y `/home/ina/pinokio/prototype/PINOKIO.md` en checklist previo.
5. Contrastar cada cambio de launcher con el ejemplo.
6. Repetir el checklist antes de finalizar.

En esta sesión se resolvió:

- `PINOKIO_HOME`: `/home/ina/pinokio`
- Raíz correcta del app launcher: `/home/ina/pinokio/api/Maestro-next.git`
- Ejemplo más cercano revisado: `/home/ina/pinokio/prototype/system/examples/comfy/start.js`, especialmente líneas 41–66.
- `start.js` no se modificó. Conserva el patrón requerido de captura de URL y:

  ```javascript
  url: "{{input.event[1]}}"
  ```

La tarea principal es código de la aplicación. `update.js` sí recibió después dos cambios de texto visibles, expresamente dentro del rebrand; se resolvió de nuevo el destino y se contrastó la estructura con `/home/ina/pinokio/prototype/system/examples/comfy/update.js`. No se cambió ninguna API ni paso del launcher. No tocar `start.js`, `pinokio.js`, `install.js` o `reset.js` sin repetir el procedimiento obligatorio.

Antes de diagnosticar cualquier fallo nuevo, mirar primero `logs/`, especialmente los archivos `latest`, como exige `AGENTS.md`.

## 3. Dónde estaba el proyecto

La rama venía de una fase centrada en **CharacterKit/cutout animation**:

- personajes 2D reutilizables;
- rigs faciales;
- visemas y bocas;
- diálogo sincronizado;
- audio aislado por escena/shot;
- integración de CharacterKit con el compositor 3D/Scene Animator.

Commits propios más recientes de la rama, por encima de `origin/main`:

- `6ad6954 feat: play the live CharacterKit mouth, not the scene snapshot`
  - Rehace la reproducción facial para utilizar la boca viva del CharacterKit.
  - Modifica Scene Animator, rig facial, biblioteca CharacterKit, guía, diálogo cutout, tipos y pruebas.
- `e3effce feat: hide Auditoría interna unless developer mode is on`
  - Oculta Auditoría interna salvo que esté activado Developer Mode.
- `17a2a06 Merge remote-tracking branch 'origin/main' into feat/3d-compositor-recipe`

Otros commits relevantes inmediatamente anteriores incluían fixes de visema en reposo, overlays faciales que siguen al personaje escalado, apertura de rigs desde Character Creator, preview de diálogo, generación de rigs y aislamiento de pistas de diálogo/audio por recipe shot.

Hay documentos locales sin seguimiento que pertenecen al usuario y no se tocaron:

- `CODEX_README.md`
- `resumen.md`
- `roadmap_agentmode.md`

No borrar, sobrescribir ni asumir que se pueden reemplazar. `roadmap_agentmode.md` contiene una propuesta anterior de Agent Mode en la barra lateral. El nuevo requisito del usuario cambia la colocación: ahora quiere el acceso en el **footer inferior izquierdo**.

## 4. Infraestructura de audio que ya existía

No era necesario implementar detección de beats desde cero. Ya existe:

- `app/services/audio_analysis.py`
- API de análisis de audio `/api/v1/audio/analyze`
- cliente `analyzeAudio(...)` en `ui/src/api/client.ts`
- tipo `AudioAnalysisResult` en `ui/src/types/index.ts`
- dependencias `librosa`, `numpy` y `soundfile` ya declaradas en `app/requirements.txt`

El analizador devuelve actualmente:

- duración;
- sample rate;
- BPM;
- beats con tiempo y fuerza;
- downbeats;
- secciones energéticas;
- onset envelope;
- letras/transcripción cuando se solicita;
- ruta de voz aislada cuando se solicita;
- warnings.

Los downbeats actuales son una heurística: se elige un ancla fuerte al principio y después se toma aproximadamente uno de cada cuatro beats. Es suficiente para un primer prototipo, pero no debe presentarse como detección métrica definitiva.

El hueco real era convertir el beat map en animación editable del compositor.

## 5. Implementación de ritmo realizada

### 5.1 Nuevo helper puro

Archivo nuevo:

- `ui/src/lib/sceneRhythm.ts`

Exporta:

- `SceneRhythmCueSource = 'beats' | 'downbeats'`
- `SceneRhythmProfile = 'pulse' | 'bounce' | 'peek' | 'camera-punch'`
- `SceneRhythmCue`
- `SceneRhythmMap`
- `ApplySceneRhythmOptions`
- `buildSceneRhythmMap(...)`
- `applySceneRhythmToLayer(...)`

`buildSceneRhythmMap`:

- toma `AudioAnalysisResult`;
- suma el `startTime` de la pista para llevar cada beat al tiempo de la escena;
- descarta cues fuera de la duración;
- conserva la fuerza normalizada del beat;
- marca downbeats;
- permite usar todos los beats o solo downbeats;
- limita la cantidad de cues, por defecto a 160, para no crear timelines patológicas.

`applySceneRhythmToLayer`:

- hornea el movimiento previo de la capa y las reacciones musicales en `SceneKeyframe` normales;
- usa las funciones existentes de `sceneTimeline` para respetar offsets, velocidad y tiempo local/de escena;
- conserva eventos existentes, remapeados a tiempo de escena;
- deja `offset = 0`, `speed = 1`, `loop = false` y trims equivalentes a la escena después del horneado;
- produce el mismo camino determinista para preview, JSON de escena y captura MP4.

Perfiles implementados:

- `pulse`: pulso de escala sobre cada cue.
- `bounce`: desplazamiento vertical y escala.
- `peek`: la capa queda oculta y desplazada entre beats, y se asoma en el beat. Es la respuesta directa al ejemplo del usuario.
- `camera-punch`: aumento de escala más contenido para golpes de cámara.

La intensidad modula el desplazamiento o la ganancia. Con intensidad cero se siguen horneando posiciones temporales, aunque no haya desplazamiento visual.

### 5.2 Integración en Scene Animator

Archivo modificado:

- `ui/src/components/Sidebar/SceneAnimatorPanel.tsx`

Estado añadido:

- pista elegida para ritmo;
- análisis actual y pista a la que pertenece;
- busy/error;
- fuente `beats` o `downbeats`;
- perfil de reacción;
- intensidad.

Funciones añadidas aproximadamente alrededor de las líneas 2363–2398:

- `analyzeSceneRhythm()`
  - llama a `analyzeAudio` con `transcribe: false` y `extract_vocals: false`;
  - comprueba que existan beats;
  - informa BPM, beats y downbeats.
- `applySceneRhythm()`
  - comprueba pista, análisis y capa seleccionada;
  - impide modificar capas bloqueadas;
  - crea el mapa de ritmo con el offset real de la pista;
  - aplica keyframes a la capa seleccionada;
  - evita `peek` en cámaras y lo convierte en `camera-punch`;
  - deja un mensaje con el número de cues aplicados.

UI añadida aproximadamente alrededor de las líneas 2730–2743:

- bloque **Music rhythm → animation**;
- selector de pista, priorizando pistas `music`;
- botón **Analyze BPM and beats**;
- resumen BPM/beats/downbeats/secciones;
- selector `Every beat` / `Downbeats only`;
- selector de reacción;
- slider de intensidad;
- botón de aplicación sobre la capa seleccionada;
- explicación de que el resultado son keyframes normales y editables.

### 5.3 Pruebas añadidas

Archivo nuevo:

- `ui/tests/sceneRhythm.test.mjs`

Casos cubiertos:

1. Offset de pista y marcado de downbeats.
2. Modo downbeats-only.
3. Pulse que conserva una trayectoria previa y alcanza el pico en el beat.
4. Peek que oculta entre beats y revela en el golpe.
5. Camera punch más contenido que el pulso normal.

### 5.4 Documentación actualizada

Archivo modificado:

- `docs/3d-video-compositor/HOWUSEIT.md`

Se añadió una sección **Music rhythm → editable animation** alrededor de la línea 390. Incluye flujo de uso, limitaciones y explicación de los keyframes. También se corrigió una referencia antigua a WebM: la salida validada actual es H.264 MP4.

## 6. Verificaciones ya realizadas

No repetir estas pruebas únicamente para reconstruir contexto. Se ejecutaron antes de la petición de no esperar:

- Pruebas focalizadas de ritmo y timeline: **7/7 pass**.
- Pruebas backend de audio/pacing: **7/7 pass**.
- ESLint sobre `sceneRhythm.ts` y `SceneAnimatorPanel.tsx`: pass.
- `tsc -b`: pass.
- `npm --prefix ui run build`: pass.
- `npm --prefix ui run budget`: pass.
- Presupuesto observado del entry JS gzip: `306965 B / 327680 B`.
- `git diff --check`: limpio.

La suite UI completa produjo **306/309 pass**. Los tres fallos restantes no están en los archivos modificados por este trabajo:

1. `sceneToRecipe.test.mjs`: un speaking beat referencia una pista de audio `voice` desconocida al hacer round-trip.
2. `storyTimelinePolling.test.tsx`: esperaba `Pipeline not found`, pero la UI muestra `Failed to load pipeline (503)`.
3. `videoEditorHandoff.test.tsx`: intenta hacer `.map` sobre un valor `undefined`.

No mezclar arreglos de esos fallos con el trabajo de ritmo sin diagnosticar primero logs y baseline. El usuario pidió avanzar, no limpiar regresiones ajenas.

Estado de Git observado antes de crear este handoff:

```text
 M docs/3d-video-compositor/HOWUSEIT.md
 M ui/src/components/Sidebar/SceneAnimatorPanel.tsx
?? CODEX_README.md
?? resumen.md
?? roadmap_agentmode.md
?? ui/src/lib/sceneRhythm.ts
?? ui/tests/sceneRhythm.test.mjs
```

Este handoff quedó incluido en el commit de ritmo. El usuario pidió después crear commits de las mejoras del mago; no incluir en ellos los tres documentos locales sin seguimiento que se enumeran arriba.

## 7. Cómo probar manualmente la función de ritmo

Cuando sea oportuno y el usuario permita pruebas:

1. Abrir **3D Video**.
2. Crear o cargar una escena.
3. Añadir una pista de audio MP3 y marcarla como `music` si corresponde.
4. Seleccionar una capa visual no bloqueada.
5. En **Music rhythm → animation**, elegir la pista.
6. Pulsar **Analyze BPM and beats**.
7. Elegir `Every beat` o `Downbeats only`.
8. Elegir `Peek on beat` para reproducir literalmente el caso pedido.
9. Ajustar intensidad.
10. Pulsar **Apply to selected layer**.
11. Reproducir la escena y comprobar los keyframes.
12. Exportar/capturar MP4 y confirmar que coincide con el preview.

La aplicación estaba corriendo durante la sesión, pero no se reinició el servidor. Dependiendo de cómo se sirva el frontend, puede ser necesario reiniciar o recargar para probar el bundle nuevo.

## 8. Roadmap detallado de animación musical

### Fase A — Base actual, completada

- beat/downbeat → keyframes;
- cuatro perfiles;
- intensidad;
- offset de pista;
- keyframes editables;
- pruebas deterministas.

### Fase B — Rhythm Map persistente

Crear un contrato `RhythmMap v1` persistido con la escena:

- BPM;
- confianza del tempo;
- beats y fuerza;
- downbeats;
- onset envelope;
- secciones;
- duración;
- hash/identidad del audio;
- versión del analizador;
- configuración aplicada.

Añadir marcadores visibles en la timeline y permitir reanalizar sin perder la configuración anterior hasta confirmar.

### Fase C — Flow continuo

Los beats discretos sirven para golpes, pero el “flow” necesita señales continuas:

- conducir brillo, glow, escala, partículas o velocidad con el onset envelope;
- controles de attack/release;
- suavizado;
- umbral de fuerza;
- min-gap para evitar temblores a BPM altos;
- cuantización y subdivisiones;
- semilla determinista para variaciones.

### Fase D — Estructura musical

Mejorar downbeats y estructura:

- confianza BPM;
- compás y downbeats reales;
- breaks, builds, drops y cambios de sección;
- evaluación sobre canciones reales y click tracks sintéticos.

Mapeo recomendado:

- beat → gesto del personaje;
- downbeat → punch de cámara;
- onset fuerte → partículas/flash;
- cambio de sección → transición, plano o paleta;
- drop → combinación coordinada con límite de intensidad.

### Fase E — Coreografía multicapa

Añadir grupos y reglas:

- capa A en beats impares;
- capa B en pares;
- fondo en downbeats;
- cámara solo en cambios de sección;
- delays y fases;
- alternancia call/response;
- límite de movimiento simultáneo para conservar legibilidad.

### Fase F — Recetas y LLM

Extender recetas con un esquema cerrado semejante a:

```json
{
  "target": "character-fox",
  "source": "beats",
  "reaction": "peek",
  "intensity": 0.7,
  "attack": 0.08,
  "release": 0.18
}
```

Validar semánticamente targets, duración, intensidad, compatibilidad de perfil y cantidad máxima de cues. El LLM propone; el motor determinista genera los keyframes.

### Fase G — Criterios de aceptación

- error de sincronía menor a un frame entre cue y pico visual;
- preview y export idénticos;
- timeline manejable en canciones largas;
- no destruir movimiento anterior sin advertir;
- undo/redo funcional;
- escenas guardadas reproducibles;
- análisis cacheado por identidad de audio;
- `prefers-reduced-motion` aplicable a la UI, no a la exportación creativa.

## 9. Mago en el footer: decisión de producto

Ubicación real inspeccionada:

- `ui/src/components/ActivityFooter.tsx`

El footer ya:

- consume `/api/v1/tasks`;
- escucha eventos SSE de tareas canónicas;
- diferencia tareas activas e históricas;
- muestra subtareas, progreso, modelo, recursos y ETA;
- permite cancelar, reanudar y ocultar historial.

Por tanto, el mago debe reutilizar esa fuente. No crear una segunda cola, no interpretar el DOM del footer y no publicar tareas ficticias para simular actividad.

Colocación propuesta:

```text
[ icono animado · Ask to the Wizard ] [ Activity · N ] [ estado actual ] [ controles ]
```

Al pulsar se abre un popover/drawer anclado sobre el footer, por ejemplo 360–420 px de ancho y 480–560 px de alto, con botón para expandir a un panel mayor.

Nombre elegido por el usuario: **Ask to the Wizard**. Mantener el nombre en una constante para poder cambiarlo sin buscar strings por toda la app.

## 10. Estética y animación del mago

Recursos existentes:

- `ui/public/hocuspocus-icon.png`
- `ui/public/hocuspocus/scribe-keyart.png`
- `ui/public/maestro.svg`
- `ui/src/components/HocusPocusIntro.tsx`
- keyframes de la intro en `ui/src/index.css`, alrededor de las líneas 874–946.

Estados visuales recomendados:

| Estado | Visual | Semántica |
|---|---|---|
| `idle` | respiración leve y una chispa ocasional | listo |
| `listening` | inclinación/brillo de borde | el usuario está escribiendo o acaba de enviar |
| `thinking` | motas orbitando y pulso ámbar | el LLM está razonando |
| `acting` | pequeña estela y pasos visibles | está navegando o rellenando |
| `waiting` | animación lenta azul/violeta | espera una tarea real |
| `success` | destello corto verde/ámbar | acción completada |
| `error` | flash rojo contenido, sin loop agresivo | necesita atención |

Primera versión recomendada:

- icono actual;
- CSS transforms/opacity/filter;
- 4–8 motas reutilizando el lenguaje de la intro;
- transiciones breves;
- `aria-live` para estado textual;
- `prefers-reduced-motion: reduce` que elimine órbitas y rebotes.

Una versión posterior puede usar sprite WebP, Lottie o Rive. Rive es atractivo para una máquina de estados expresiva, pero añade dependencia y pipeline de assets. No es necesario para el MVP.

## 11. Arquitectura recomendada del agente

No usar clics simulados ni coordenadas. La UI debe moverse de verdad mediante las mismas acciones que usan los controles humanos.

```text
Usuario
  ↓
AgentAssistantPanel
  ↓
LLM configurado en Settings
  ↓
respuesta + acciones tipadas
  ↓
Action bus del cliente
  ├─ navegación y prefill → Zustand/useStore
  ├─ consultas → APIs de HocusPocus
  ├─ trabajos → workflows reales existentes
  └─ seguimiento → cola canónica/SSE
  ↓
pasos visibles + resultado + historial
```

Piezas ya existentes:

- `generateLlmText(...)` en `ui/src/api/client.ts`, aproximadamente línea 4113.
- `/api/v1/llm/generate` en `app/_launch_runtime.py`, aproximadamente línea 8232.
- proveedores y routing en `app/services/llm_service.py`.
- tarea canónica en `app/services/task_manager.py` y `app/routers/canonical_tasks.py`.
- actions/UI global en `ui/src/stores/useStore.ts`.
- footer y stream de actividad en `ui/src/components/ActivityFooter.tsx`.

El LLM puede ser el mismo configurado para Director: local o remoto según Settings. No fijar un proveedor en código ni enviar API keys dentro del prompt.

## 12. Opciones técnicas evaluadas

### Opción 1 — Bucle enteramente en el cliente

El panel llama a `generateLlmText` con `json_schema`, interpreta acciones y las despacha.

Ventajas:

- implementación rápida;
- cambios visibles en Zustand;
- poca infraestructura.

Limitaciones:

- el turno se pierde al cerrar la pestaña;
- peor para trabajos largos;
- seguridad y reintentos repartidos por el cliente.

Útil como prototipo, no como destino final.

### Opción 2 — Runtime híbrido UI/backend, recomendada

El backend gestiona conversación, planificación, validación de herramientas y tareas largas. El cliente ejecuta navegación/prefill para que los cambios sean visibles y devuelve resultados de cada acción.

Ventajas:

- sesiones duraderas;
- mejor control de seguridad;
- cancelación y reintentos;
- integración natural con la cola canónica;
- el panel puede cerrarse sin perder el trabajo.

Es la opción recomendada para producción.

### Opción 3 — Agente CLI por debajo

Codex, Claude Code u otro CLI tendría shell y filesystem.

No usarlo para el operador cotidiano porque:

- da permisos innecesarios;
- complica instalación, autenticación y soporte cross-platform;
- mezcla operar HocusPocus con modificar HocusPocus;
- aumenta el riesgo de prompt injection y cambios de código accidentales.

Sí puede existir más adelante como **Developer Agent**, claramente separado, con:

- sandbox;
- directorio de trabajo explícito;
- allowlist;
- aprobación humana;
- diff visible;
- sin acceso automático a secretos.

### Opción 4 — Servidor MCP de Maestro

Exponer las mismas herramientas como MCP permitiría que agentes externos consulten y operen HocusPocus. Es una ampliación valiosa, pero no hace falta para el asistente embebido y no sustituye el action bus del cliente.

## 13. Catálogo inicial de herramientas

Cada herramienta debe tener esquema JSON cerrado, validación, scope de workspace, política de confirmación y resultado serializable.

### Solo lectura

- `get_app_state`
- `list_tasks`
- `get_task_details`
- `list_available_models`
- `explain_feature`
- `get_current_tab`
- `get_current_generation_form`
- `list_recent_outputs`

### Navegación y preparación, sin coste

- `open_tab`
- `set_studio_mode`
- `select_model`
- `set_prompt`
- `set_duration`
- `set_resolution`
- `set_fast_h3`
- `clear_start_end_images`
- `prefill_example`
- `open_output`

### Trabajo real

- `start_generation`
- `start_director_pipeline`
- `analyze_audio`
- `apply_beat_motion`
- `cancel_task`
- `resume_task`

No crear una herramienta genérica `run_shell` para el mago de usuario.

## 14. Confirmaciones y seguridad

Automático:

- responder preguntas;
- consultar cola;
- navegar;
- rellenar campos;
- proponer un plan;
- analizar información local no sensible.

Requiere confirmación visible o una orden inequívoca del usuario:

- iniciar una generación normal se puede ejecutar directamente cuando la frase es imperativa y explícita; si es ambigua o supera umbrales de coste/tiempo, se confirma;
- lanzar Director/Series completos;
- resolución/duración por encima de umbrales configurables;
- cancelar una tarea;
- reemplazar una escena o configuración con cambios no triviales;
- borrar o resetear cualquier cosa.

Reglas:

- allowlist de tools;
- workspace obligatorio en cada consulta;
- idempotency key para acciones mutantes;
- no API keys en prompts ni historial;
- no shell arbitraria;
- no acceso general al filesystem;
- registro de cada acción del agente;
- botón Stop para cancelar el turno;
- confirmar de nuevo si el estado cambió desde que se propuso el plan.

## 15. Conocimiento de la aplicación

Para explicar cómo funciona HocusPocus no conviene enviar todo el repositorio al LLM en cada turno.

Crear un `FeatureRegistry` estructurado con:

- id de feature;
- título y aliases;
- pestaña donde vive;
- requisitos;
- campos principales;
- acciones disponibles;
- ejemplos;
- enlaces a documentación local.

Después añadir recuperación de fragmentos de `docs/` si hace falta. Empezar con un índice pequeño y mantenible. Las respuestas sobre estado dinámico deben venir de tools, no de documentación estática.

## 16. Orden recomendado de implementación del mago

### Corte 1 — Cascarón visual y lectura — completado

- `ui/src/features/agent/AgentAssistantPanel.tsx`
- `ui/src/features/agent/agentSession.ts`
- botón con logo en `ActivityFooter.tsx`
- estados visuales del mago en `ui/src/index.css`
- historial ligero por workspace;
- preguntas generales mediante `generateLlmText`;
- contexto real de `fetchCanonicalTasks`;
- inicialmente sin mutaciones; esta limitación ya fue sustituida por el Corte 2/3 mínimo descrito abajo.

Aceptación:

- “¿Qué hay en cola?” responde con tareas reales.
- “¿Qué está haciendo ahora?” incluye fase, progreso y subtarea.
- “¿Cómo creo un vídeo 3D?” explica el flujo correcto.

### Corte 2 — Action bus de navegación/prefill — primer alcance completado

Implementado en:

- `ui/src/features/agent/agentActions.ts` (tipos, esquema, parser, snapshot y dispatch);
- `ui/src/features/agent/agentKnowledge.ts` (system prompt, mapa y contexto);
- `ui/src/features/agent/AgentAssistantPanel.tsx` (turno, ejecución y resultados visibles).

Las acciones llaman al store existente. No usar `document.querySelector` ni eventos de clic artificiales.

Aceptación:

- “Llévame a 3D Video” abre esa tab.
- “Ponme un ejemplo de vídeo H3 rápido” abre Studio/Video, selecciona modelo compatible y rellena los campos sin generar.
- Cada acción aparece como un paso visible en el chat.

### Corte 3 — Mutaciones — generación de vídeo mínima completada

- `start_generation` pasa por `useStore.startGeneration()`;
- el trabajo aparece en el footer porque el backend crea la tarea canónica;
- el agente espera por el stream existente;
- una orden explícita de generar funciona como autorización para el trabajo normal; siguen pendientes confirmación reforzada, idempotencia y botón Stop para acciones caras/destructivas.

Aceptación:

- “Genéralo” muestra resumen de modelo, duración y resolución; tras confirmar entra en la cola real.
- “Cancela el trabajo” identifica la tarea exacta y pide confirmación.

### Corte 4 — Runtime backend duradero

Propuesta de archivos:

- `app/services/agent_runtime.py`
- `app/routers/agent.py` o ruta delgada integrada siguiendo convenciones existentes;
- endpoint de turno y stream de eventos;
- persistencia por workspace;
- reanudación tras recarga.

No asumir sintaxis o arquitectura del router: estudiar primero los routers actuales y las normas del repo.

### Corte 5 — Ritmo, Director y recetas

- `analyze_audio`;
- `apply_beat_motion`;
- abrir Scene 3D y preparar el perfil `peek`;
- lanzar Director para videoclips;
- reutilizar Series/CharacterKit, sin reimplementar sus pipelines.

Ejemplo final deseado:

> “Usa esta canción, abre 3D Video, haz que el personaje se asome en cada downbeat y que la cámara pulse solo al entrar el estribillo.”

El mago debe:

1. comprobar que hay pista;
2. abrir 3D Video;
3. analizar el audio;
4. proponer/aplicar `peek` al personaje;
5. aplicar punch de cámara a cues estructurales;
6. mostrar los keyframes;
7. pedir confirmación antes de renderizar.

## 17. Pruebas de aceptación del agente

1. “¿Qué hay en cola?”
2. “¿Por qué está esperando la GPU?”
3. “Llévame a 3D Video.”
4. “Rellena un ejemplo de H3 rápido, pero no generes todavía.”
5. “Ahora genéralo.”
6. “Cancela el trabajo activo.”
7. “¿Cómo hago que un objeto se asome con la música?”
8. “Aplica el ritmo de esta pista a la capa seleccionada.”
9. Cambiar de workspace y comprobar que no mezcla tareas ni conversación.
10. Activar reduced motion y comprobar que el mago sigue siendo legible sin animación.

## 18. Próximos pasos exactos para Grok

1. Leer `AGENTS.md` completo y rehacer el checklist obligatorio.
2. Revisar `logs/*/latest` antes de diagnosticar.
3. Revisar el diff actual y no tocar los tres documentos locales del usuario.
4. Abrir manualmente 3D Video y validar el flujo de ritmo si el usuario autoriza pruebas; no repetir suites largas.
5. No rehacer `sceneRhythm.ts`: la base ya existe y tiene pruebas.
6. Si se continúa con ritmo, empezar por persistencia del `RhythmMap` y marcadores de timeline.
7. Si se continúa con el mago, ampliar el bus actual: imágenes/audio/3D, cancelación confirmada, seguimiento del job y acciones de ritmo/Director.
8. Reutilizar `ActivityFooter`, `generateLlmText`, `fetchCanonicalTasks` y el store existente.
9. No introducir un agente CLI en el flujo cotidiano.
10. Mantener las mutaciones fuera de la allowlist desactivadas. La generación de vídeo ya usa schema cerrado y sólo arranca tras `prepare_video` en el mismo turno; añadir idempotencia antes de ampliar operaciones.
11. Antes de finalizar, ejecutar el checklist de salida de `AGENTS.md` y documentar cualquier prueba que sí se haya ejecutado.

## 19. Decisiones que no deben perderse

- El ritmo debe producir keyframes editables, no un efecto oculto solo durante el render.
- Preview y export deben usar exactamente la misma evaluación temporal.
- `peek` es un perfil de primera clase porque responde al ejemplo del usuario.
- Los beats fuertes y downbeats deben distinguirse; no mover todo igual.
- El mago va en el footer inferior izquierdo, junto a Activity.
- El mago debe verse actuar dentro de la aplicación.
- API/store son las manos; la UI es el escenario visible.
- No simular clics por coordenadas.
- No crear una segunda cola.
- No usar CLI para el asistente de usuario.
- Un futuro Developer Agent debe estar separado y tener permisos explícitos.
- La estética importa: mago con personalidad y estados, pero sin sacrificar accesibilidad ni claridad.

## 20. Continuación iniciada después del handoff

El bloque de ritmo y este handoff se guardaron en el commit:

```text
3ac6f5d feat: sync 3d scene animation to music beats
```

Después comenzó el **Corte 1** del mago. Los cambios posteriores a ese commit
añaden, o deben conservar si todavía no se han confirmado:

- `ui/src/features/agent/agentKnowledge.ts`
  - mapa resumido de la aplicación;
  - saneado de la cola canónica;
  - system prompt inicial de modo solo lectura, sustituido después por el contrato operativo del apartado 21;
  - constructor del contexto conversacional.
- `ui/src/features/agent/AgentAssistantPanel.tsx`
  - panel anclado sobre el footer;
  - avatar con estados `idle`, `listening`, `thinking`, `success` y `error`;
  - historial por workspace en `localStorage`;
  - preguntas al LLM configurado mediante `generateLlmText`;
  - snapshot real de las tareas que ya mantiene `ActivityFooter`;
  - sugerencias rápidas y mensajes de error de configuración.
- `ui/src/components/ActivityFooter.tsx`
- franja reservada **Ask to the Wizard** antes de Activity, dentro del flujo flex normal para desplazar el contenido existente hacia la derecha;
  - exclusión mutua entre el panel del agente y el histórico de Activity.
- `ui/src/index.css`
  - halo, motas, respiración, estado de pensamiento y entrada del panel;
  - fallback completo para `prefers-reduced-motion`.

Ese primer corte dejó de ser sólo consulta. La continuación actual añade
acciones tipadas, navegación, prefill completo de vídeo y envío explícito a la
cola real. La app añade el resultado verdadero de cada acción al mensaje; el
LLM no puede afirmar por sí solo que algo terminó bien.

## 21. Estado actual del mago operativo (2026-08-29)

Implementación añadida después de los commits `79f567b` y `c7343c0`:

- `ui/src/features/agent/agentActions.ts`
  - allowlist de 17 destinos de navegación;
  - esquema JSON estricto para `open_tab`, `prepare_video` y `start_generation`;
  - parser que trata la salida del LLM como no confiable, limita campos y un máximo de seis acciones;
  - impide `start_generation` si no hubo `prepare_video` antes en el mismo turno;
  - snapshot acotado del formulario actual y modelos T2V disponibles;
  - selección de un modelo T2V instalado/habilitado;
  - preparación visible de Studio → Video;
  - propiedades soportadas: prompt, modelo, duración, preset/resolución, aspect ratio, negative prompt, seed, inference steps, guidance, output count, dirección de audio H3 y Turbo;
  - envío por `useStore.startGeneration()`, por lo que utiliza la cola y el ciclo de descarga/VRAM existentes;
  - comprobación de que apareció un job nuevo y propagación del error real si el submit falla.
- `ui/src/features/agent/agentKnowledge.ts`
  - eliminadas las instrucciones de sólo lectura;
  - el mago habla con una personalidad mágica breve pero mantiene exactitud técnica;
  - sólo genera ante verbos de acción explícitos;
  - devuelve JSON estructurado y no declara éxito antes de que el cliente ejecute.
- `ui/src/features/agent/AgentAssistantPanel.tsx`
  - historial actualizado a `hocuspocus-agent-chat-v2` para no rehidratar el saludo antiguo de sólo lectura;
  - mensajes de trabajo HocusPocus, sin el texto visible “Maestro”;
  - estado visual `acting`, pasos y resultados reales `✦/⚠`;
  - sugerencias rápidas de navegación y preparación.
- `ui/src/index.css`
  - animación breve de conjuro para el estado `acting`, incluida en el fallback existente de reduced motion.

Branding visible corregido además en el fallback de tareas, la descripción de H3
Legacy y los mensajes de Update. `scripts/check_brand_contract.py` vuelve a
validar HocusPocus y conserva deliberadamente contratos internos como
`maestro-video-editor-draft-v1`, `.maestro-tasks-v1.sqlite3` y `MAESTRO_EVENT`.
Las referencias a Maestro como proyecto upstream/crédito también se conservan.

`README.md` raíz se dejó expresamente **intacto** por la última indicación del
usuario.

Verificación corta realizada, sin lanzar ninguna generación ni suite larga:

- `python scripts/check_brand_contract.py`: PASS;
- `npm run build` dentro de `ui/`: TypeScript + Vite PASS;
- bundle servido por el runtime: `index-BABGOZiQ.js` y `index-DKdWp3hG.css`;
- `git diff --check`: limpio.

Siguientes ampliaciones recomendadas, en orden:

1. Añadir tests puros del parser/dispatch e idempotency keys.
2. Generalizar `prepare_video` a recetas tipadas de imagen, audio y 3D.
3. Añadir `cancel_task`/`resume_task` con confirmación visible y selección inequívoca.
4. Mostrar el job canónico creado y permitir que el mago siga su progreso.
5. Conectar `analyze_audio` + `apply_beat_motion` para operar el flujo de ritmo ya implementado en 3D Video.
6. Llevar el bucle al backend si se necesita persistencia cuando el panel/pestaña se cierra.
7. Mantener un futuro CLI como **Developer Agent** separado, con sandbox, permisos, aprobación y diff; no usarlo para navegación/formularios/cola normal.

## 22. Arreglo de navegación, Markdown y órdenes directas (2026-08-30)

Tras probar el mago en la aplicación se observó este caso real:

- el usuario pidió directamente un vídeo;
- el LLM respondió con una lista Markdown de preguntas innecesarias;
- sólo propuso `open_tab("studio")`;
- Studio ya era la barra lateral activa, pero conservaba el modo 3D;
- el chat mostró “He abierto Studio” aunque visualmente no cambió nada y no se
  creó ningún trabajo.

El arreglo mantiene al LLM como planificador, pero añade garantías locales:

- las respuestas del mago renderizan Markdown básico mediante nodos React
  seguros, sin HTML crudo ni una dependencia nueva;
- una petición inequívoca como “hazme/genera/crea un vídeo de X” se reconcilia
  siempre con `prepare_video` + `start_generation` y valores conservadores si
  el LLM sólo pregunta o navega;
- preguntas explicativas y órdenes negadas siguen siendo de sólo consulta;
- `prepare_video` selecciona de verdad Studio, el modo Video y la galería de
  vídeos antes de rellenar el formulario;
- `open_tab` usa el estado canónico de cada destino, cierra overlays o el drawer
  móvil cuando corresponde, expande Director mediante el evento ya existente y
  distingue “ya estaba visible” de “he abierto”;
- Character Creator apunta ahora a `characters`, no a la antigua vista `avatars`
  de Edits.

La verificación de este arreglo no debe lanzar una generación real: basta con
lint, build y el contrato de marca. La prueba manual posterior debe usar una
petición explícita y comprobar que el resultado del chat incluye tanto la
preparación como el identificador real de la tarea creada en la cola.

El arreglo anterior quedó guardado en:

```text
776130f fix: make wizard navigation and commands visible
```

## 23. Catálogo de capacidades y Story/Series operables (2026-08-30)

El siguiente fallo observado fue una petición explícita de crear un capítulo de
una serie conocida. El LLM inventó un argumento útil en el chat y abrió Story
Lab, pero no rellenó nada. Los logs confirmaron dos llamadas LLM correctas y
ninguna mutación de Series Lab después de ellas. La causa no era el modelo: el
Wizard sólo disponía de `open_tab`, `prepare_video` y `start_generation`.

### Fuente de conocimiento única

Se añade `ui/src/features/agent/agentCapabilities.ts` como catálogo canónico de
funciones ya implementadas. Cada descriptor contiene:

- identificador estable;
- propósito;
- cuándo debe utilizarse;
- riesgo (`read`, `edit` o `compute`);
- parámetros principales.

`agentKnowledge.ts` genera desde ese catálogo el bloque de capacidades que
recibe el LLM. Al implementar otra herramienta hay que registrarla allí; no se
debe enseñar sólo mediante prosa aislada en el prompt. El catálogo contiene por
ahora:

1. `open_tab`
2. `prepare_video`
3. `prepare_image`
4. `prepare_audio`
5. `queue_sfx_pack`
6. `open_story_section`
7. `open_series_section`
8. `start_generation`
9. `create_story`
10. `create_series_episode`
11. `inspect_queue`
12. `cancel_task`
13. `resume_task`

### Proceso común de cualquier acción

```text
petición → intención estructurada → parser/validación → resolución de IDs reales
→ preflight/permisos → executor API/store → verificación → resultado y navegación
```

El LLM nunca recibe permiso para escribir directamente en Zustand, manipular el
DOM o inventar IDs/revisiones. Las acciones compuestas resuelven esos detalles
con APIs reales.

### Navegación interna

`ui/src/features/agent/agentUiBus.ts` permite abrir subpestañas que antes eran
estado local privado de React:

- Story Lab: Overview, World, Characters, Relationships, Structure y
  Productions.
- Series Lab: Setup, Canon, Episode room, Shots y Review.

El bus conserva el último destino solicitado en memoria, por lo que también
funciona si el panel lazy todavía no se había montado cuando terminó la acción.

### `create_story`

La acción crea y guarda un proyecto Story Lab completo y editable con:

- título, tipo, brief, premisa, logline, sinopsis, tema y final;
- género, tono, idioma y estilo visual;
- mundo y localizaciones;
- personajes y una relación inicial cuando hay más de uno;
- al menos tres beats causales;
- selección visible de Story Lab → Overview.

El guardado usa la revisión CAS de la biblioteca. Una repetición exacta abre la
historia existente en vez de duplicarla.

### `create_series_episode`

La acción compuesta:

1. busca una serie por título normalizado;
2. reutiliza la existente o crea una nueva cuando `create_if_missing=true`;
3. rellena sólo el setup/canon que falte;
4. para una orden explícita de crear el capítulo, aprueba el canon mínimo que
   Series Lab exige (el resultado lo comunica de forma visible);
5. crea el episodio mediante el endpoint real, con título, premisa, logline,
   duración y outline;
6. recarga el store, selecciona los IDs devueltos por backend y abre Series Lab
   → Episode room;
7. evita duplicar un episodio con el mismo título y premisa.

Un universo conocido se marca `known_universe_experimental` y guarda una nota
de derechos; el Wizard nunca afirma que el usuario tenga derecho de publicación
o monetización. Crear el borrador no renderiza tomas ni consume generación de
vídeo.

### Inventario pendiente para “controlar toda la app”

El mismo catálogo debe crecer por familias, no mediante un CLI con shell libre:

- navegación: selección interna de Director, Settings, outputs, workspaces,
  stories, series, episodios, escenas y capas;
- Studio: vídeo, imagen y audio/SFX ya se preparan; faltan 3D, LoRAs y referencias;
- Story: patch, generación de secciones, aplicación de propuestas, aprobación,
  imágenes y staging de producciones;
- Series: bootstrap conocido, plan completo, aplicación, shots, render,
  revisión y assembly;
- 3D/rhythm: cargar escena, seleccionar capa, adjuntar audio, analizar beat map,
  aplicar perfil y guardar/capturar;
- cola: inspeccionar, cancelar y reanudar ya están conectados; falta reintentar con confirmación y seguimiento continuo del job;
- workspace: seleccionar y crear; borrado siempre con confirmación reforzada.

Un CLI sólo queda recomendado para un **Developer Agent** separado que edite
código o ejecute tareas de sistema. La operación cotidiana de HocusPocus debe
seguir usando este registro cerrado de herramientas y las APIs/stores reales.

## 24. Cola canónica operable (2026-08-30)

Tras el commit de Story/Series Lab, el mago todavía no podía responder de
forma actuada a “¿qué hay en cola?”, “¿por qué espera la GPU?” o “cancela el
trabajo activo”: tenía el snapshot en el prompt, pero ninguna herramienta de
cola. Se añaden tres acciones sobre las APIs canónicas existentes:

- `inspect_queue` refresca `/api/v1/tasks` y abre el historial de Activity.
- `cancel_task` exige `confirm=true` y un id, o la única raíz activa.
- `resume_task` usa el mismo contrato de confirmación y `canResumeCanonicalTask`.

Una orden explícita de cancelar se repara en cliente si el LLM omite la
acción, igual que las órdenes de vídeo. No se lanza ninguna generación en esta
ampliación.

## 25. Studio imagen operable (2026-08-30)

`prepare_image` abre Studio → Image, elige un modelo de familia imagen
instalado/habilitado y rellena prompt, resolución y recuento. `start_generation`
acepta esa preparación en el mismo turno. Una orden inequívoca (“hazme una
imagen de X”) se repara en cliente como el vídeo. 3D sigue pendiente.

## 26. Studio Audio / SFX (2026-08-30)

La pestaña Audios es solo galería. Crear sonido es Studio → Audio.

Falló un turno real: el LLM emitió `opentab` y un objeto con todos los
campos vacíos concatenados, porque el schema exigía ~40 required. El
schema ahora solo exige `type`; el parser acepta alias (`opentab`).

- `prepare_audio` abre Studio → Audio (speech/music/sfx) y rellena MMAudio
  cuando el submodo es SFX.
- `queue_sfx_pack` encola varios one-shots MMAudio. Una petición explícita
  de efectos para un juego tipo Vampire Survivors rellena un pack de 10
  clips si el modelo no los mandó.
