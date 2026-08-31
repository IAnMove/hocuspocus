# Plan de mejora global del Wizard de HocusPocus

Estado inicial: 2026-08-31  
Objetivo inmediato: cerrar y verificar desde la interfaz el flujo completo `Story Lab -> canción vocal -> videoclip -> Director`.  
Objetivo posterior: convertir el sistema actual de acciones del Wizard en un plano de control global, robusto y visible, sin reescribir las piezas que ya funcionan.

## 1. Principios que no debemos romper

1. La API y los stores persistidos son la fuente de verdad. El texto del chat nunca demuestra que una acción haya ocurrido.
2. Todo recurso creado recibe un ID canónico e inmutable. Los títulos, idiomas y etiquetas como `v1` solo sirven para mostrar información.
3. Cada paso consume los IDs producidos por el paso anterior. No debe volver a buscar por nombre un proyecto, cue, canción, output, job o pipeline recién creado.
4. El usuario debe ver qué hace el Wizard: navegación, sección activa y valores comprometidos en los formularios.
5. La animación visual nunca sustituye a la operación robusta. Primero se confirma el estado en store/API y después se representa la acción en la UI.
6. Si falta una decisión necesaria, el workflow pasa a `awaiting_input`, pregunta en el chat y reanuda exactamente el paso bloqueado.
7. Los trabajos costosos requieren confirmación según su política. Reintentar la misma orden debe ser idempotente o declarar que es aditiva.
8. La Activity muestra el último evento real por fecha del evento; no un log antiguo rehidratado recientemente.

## 2. Lo que ya existe y debe reutilizarse

- Catálogo de acciones del Wizard y esquemas para el LLM.
- Registro tipado de capacidades para el camino migrado.
- Ciclo común `resolve -> validate -> prepare -> confirm -> execute -> correlate -> track -> report`.
- Adaptadores de aplicación para Studio, Story Lab, Series Lab, Comics, Video3D, Video Editor, CharacterKit, Director y Queue.
- Informes estructurados con IDs reales de tareas, pipelines y outputs.
- Conversación y tarjetas de ejecución persistentes por workspace.
- Runtime de workflows con checkpoints, CAS, reanudación y consumo idempotente de eventos canónicos.
- Flujo rítmico canción -> Video3D -> escena editable -> MP4 y pruebas sintéticas de 120 BPM.
- Flujo de autoría musical en Story Lab con modelo, modo vocal, idioma, dirección musical y letra editables.
- Migraciones de alto valor en Story, Series, Comics, CharacterKit, Video Editor y Director.

Estas piezas son la base del futuro control plane; no se crea una segunda infraestructura paralela.

## 3. Bloque A — cerrar el flujo real de videoclip

### Escenario de aceptación

Desde `Ask to the Wizard`, como un usuario, pedir:

> Crea desde cero en Story Lab un videoclip llamado “Prueba Wizard <marca única>”. Escribe una canción vocal en español, heavy metal ochentero, con voz ronca y coro grave, estética visual de animación adulta fantástica de 1981. Usa ACE-Step 1.5 XL, rellena la letra completa en la ficha, genera la canción y ejecuta el videoclip.

### Resultado observable requerido

1. Se abre Story Lab y queda activo un proyecto nuevo de tipo `music_video`.
2. El título visible coincide con el solicitado.
3. Story Lab -> Music contiene una ficha visible y persistida con:
   - modelo ACE-Step 1.5 XL;
   - modo vocal, no instrumental;
   - idioma español;
   - prompt/dirección musical en español;
   - letra completa editable con secciones compatibles con ACE-Step.
4. La generación musical crea un job canónico y el workflow guarda su `task_id`.
5. Cuando termina, se crea una canción candidata con `cue_id`, `candidate_id`/`output_id`, URL reproducible y duración.
6. El audio seleccionado pertenece al proyecto recién creado. No se resuelve por el nombre de otro proyecto ni por una etiqueta `v1`.
7. Music Video Director se prepara con los IDs exactos de historia, cue y canción.
8. La producción se inicia y devuelve un `pipeline_id` real ligado a ese proyecto.
9. La tarjeta del Wizard distingue `preparado`, `en cola`, `en marcha`, `completado`, `parcial` y `fallido`.
10. Recargar la página conserva proyecto, ficha, canción seleccionada y workflow sin repetir pasos costosos.

### Diagnóstico y correcciones

- Reproducir primero desde la UI y capturar estado visible, requests y logs.
- Inspeccionar los objetos persistidos después de cada paso.
- Corregir el primer punto donde el ID producido deje de propagarse.
- Añadir una prueba de regresión por cada fallo confirmado.
- Repetir el escenario con otro nombre único hasta completar toda la cadena.
- No declarar éxito por haber abierto una pestaña ni por haber escrito una respuesta en el chat.

## 4. Bloque B — cerrar la línea base actual

1. Verificación UI de persistencia de conversación entre workspaces y recarga.
2. Verificación de que dos pestañas no sobrescriben silenciosamente la conversación.
3. Contexto activo del Wizard con IDs de workspace, sección, proyecto, cue, output, job y pipeline.
4. Eliminar resoluciones ambiguas por títulos cuando ya existe una referencia canónica.
5. Completar las acciones restantes de Studio y workspace solo después de congelar el contrato global.
6. Mantener tests de comportamiento sobre el estado persistido, no solo sobre el JSON producido por el LLM.

## 5. Bloque C — contrato global agente/UI/API

### Entidades comunes

```ts
type EntityRef = {
  kind: string
  id: string
  workspaceId: string
  version?: number
}

type ArtifactRef = {
  id: string
  kind: 'image' | 'audio' | 'video' | 'scene' | 'document'
  owner: EntityRef
  taskId?: string
  uri: string
  metadata: Record<string, unknown>
}
```

### Comando común

```ts
type CommandEnvelope<T> = {
  commandId: string
  capability: string
  workspaceId: string
  actor: 'user' | 'wizard'
  target?: EntityRef
  input: T
  idempotencyKey: string
  expectedVersion?: number
  presentation?: PresentationPlan
}
```

### Resultado común

```ts
type CommandResult = {
  commandId: string
  status: 'completed' | 'queued' | 'awaiting_input' | 'partial' | 'failed'
  entities: EntityRef[]
  artifacts: ArtifactRef[]
  taskIds: string[]
  pipelineIds: string[]
  navigationTarget?: NavigationTarget
  error?: StructuredError
}
```

### Tipos de capacidad

- `query`: lectura sin mutación.
- `navigate`: cambia el contexto visible.
- `draft`: rellena o modifica datos editables sin coste de cómputo.
- `command`: mutación atómica o trabajo en cola.
- `workflow`: encadena comandos, esperas y decisiones.

El registro central debe generar la descripción para el LLM, JSON Schema, validación, riesgo, confirmación, adaptador, tracking, resumen, documentación y prueba mínima.

## 6. Bloque D — contexto canónico de sesión

Crear un `Agent Context API` que devuelva en una sola instantánea versionada:

- workspace y usuario activos;
- área, pestaña y subsección visibles;
- entidad activa y selección actual;
- borradores sucios y versión persistida;
- recursos/artifacts disponibles;
- tareas y pipelines relevantes;
- capacidades válidas para el contexto;
- workflow del Wizard activo y su paso;
- bloqueos y preguntas pendientes.

La UI publica cambios de presencia/selección; el backend mantiene la identidad durable. El LLM recibe IDs opacos y etiquetas humanas, pero nunca debe reconstruir identidad desde el texto.

## 7. Bloque E — preguntas y reanudación

Añadir estados explícitos:

```text
prepared -> running -> waiting_task -> awaiting_input -> running
                                  |-> partial
                                  |-> failed -> retrying
                                  |-> cancelled
                                  |-> completed
```

Una pregunta pendiente guarda:

- `workflow_id` y `step_id`;
- motivo estructurado;
- campos concretos que faltan;
- opciones válidas y valor recomendado;
- IDs ya resueltos;
- respuesta del usuario;
- fecha y versión.

La respuesta del usuario completa únicamente esos campos y reanuda el mismo workflow. No se vuelve a pedir al LLM que reconstruya toda la operación desde el historial del chat.

## 8. Bloque F — migración de capacidades restantes

Orden recomendado:

1. Acciones restantes de Studio y biblioteca/workspace.
2. Flujos musicales y de videoclip sobre el workflow validado en el Bloque A.
3. Acciones Video3D adicionales y recetas rítmicas.
4. Operaciones auxiliares de Story/Series/Comics que sigan en el dispatcher legado.
5. Cola, cancelación, reintento y apertura de resultados.

Cada migración exige:

- entrada tipada;
- resolución exacta;
- adapter test sin renderizar React;
- prueba del estado persistido;
- informe con IDs reales;
- comportamiento idempotente documentado;
- compatibilidad temporal con las acciones aún no migradas.

## 9. Bloque G — pruebas y observabilidad

### Batería segura por defecto

- tipos, lint, build y presupuesto de bundle;
- registro/esquemas completos;
- ambigüedad y recursos ausentes;
- adapters y persistencia real;
- workflows: recarga, duplicados, retry, cancelación y `awaiting_input`;
- Activity ordenada por tiempo real del evento;
- ritmo sobre click tracks sintéticos.

### Pruebas de navegador

- abrir el Wizard y enviar una petición;
- observar navegación y formulario rellenado;
- editar un valor antes de ejecutar;
- responder a una pregunta bloqueante;
- recargar durante una espera y continuar una sola vez;
- abrir/reproducir el audio generado;
- verificar que el videoclip usa el artefacto seleccionado.

### Smoke con GPU/proveedor, siempre opt-in

- canción corta -> canción seleccionada -> videoclip/Video3D -> salida;
- conservar `project_id`, `cue_id`, `output_id`, `task_id` y `pipeline_id` en el informe;
- no ejecutarlo en nightly sin flags explícitos.

## 10. Bloque H — magia visible del Wizard

Primero aprobar con el usuario un prototipo pequeño en Studio -> Video:

1. Abrir pestaña y sección.
2. Esperar a que el panel confirme que está montado.
3. Revelar y enfocar el control mediante un ancla semántica estable.
4. Comprometer el valor atómicamente en store/API.
5. Reproducir visualmente un relleno progresivo corto.
6. Aplicar un brillo/chispas al control confirmado.
7. Ceder inmediatamente si el usuario empieza a escribir.

Reglas:

- usar `data-wizard-anchor`, nunca selectores CSS posicionales;
- las animaciones se pueden omitir y respetan `prefers-reduced-motion`;
- no robar foco durante escritura del usuario;
- un ancla visual ausente no invalida una operación ya confirmada;
- velocidad configurable: instantánea, normal o teatral;
- la tarjeta de ejecución sigue siendo la fuente factual del progreso.

No extender las anclas a toda la aplicación hasta que el usuario apruebe ritmo, partículas, auto-scroll y comportamiento del foco.

## 11. Orden de commits propuesto

1. `docs: record Wizard control plane improvement plan`
2. `fix: close Story music video identity chain`
3. `test: cover Story music video UI workflow`
4. `feat: add canonical Wizard session context`
5. `feat: add Wizard awaiting-input checkpoints`
6. `feat: finalize global command and result contracts`
7. Commits pequeños por dominio para las capacidades restantes.
8. `test: add browser Wizard workflows and opt-in media smoke`
9. `feat: prototype visible Wizard form magic`
10. Commits de expansión visual solo después de la revisión del usuario.

## 12. Criterio de cierre

El Agent Mode no se considera terminado porque el LLM haya producido un plan correcto. Se considera cerrado cuando:

- el usuario ve el estado y los formularios correctos;
- API/store contienen exactamente lo que se muestra;
- todos los pasos están ligados mediante IDs canónicos;
- una recarga no duplica ni pierde trabajo;
- los bloqueos preguntan y reanudan el mismo workflow;
- jobs y pipelines pueden seguirse hasta su salida;
- las pruebas cubren éxito, ambigüedad, fallo, retry y cancelación;
- el flujo visible sigue funcionando con animaciones desactivadas.

## 13. Punto actual para el relevo

El **Bloque A está cerrado** con una prueba real desde la UI. No comenzar la capa de chispas ni una migración masiva antes de congelar el contrato global del Bloque B.

### Validación real del 31 de agosto de 2026

- Se escribió la petición completa en `Ask to the Wizard` mediante teclado y clics de navegador, sin invocar directamente los adapters.
- El Wizard creó un proyecto `music_video`, abrió Story Lab y rellenó una canción vocal en español con ACE-Step 1.5 XL, letra completa y modo instrumental desactivado.
- ACE-Step generó un WAV de 75 segundos, el candidato quedó seleccionado y la ficha mostró un reproductor utilizable.
- El mismo workflow conservó `project_id`, `cue_id`, `candidate_id`, `production_id` y `pipeline_id` hasta Music Video Director.
- Se reprodujo y corrigió una carrera CAS: el autosave adelantaba la revisión mientras ACE-Step generaba. La persistencia ahora relee la biblioteca y reaplica la mutación por IDs canónicos, sin sobrescribir cambios concurrentes.
- Se reprodujo y corrigió una pérdida de dirección artística: si el LLM dejaba un estilo genérico pero el brief contenía una película/serie/año explícitos, ese look no llegaba al master prompt. Los videoclips recuperan ahora la estética explícita para `visualStyle`, prompts de sujetos/localizaciones y `directVideoMasterPrompt`.
- Una segunda creación visible confirmó en API `projectType=music_video`, español, letra vocal, IDs nuevos y un master prompt que contiene `Heavy Metal 1981`.
- Se descubrió que una orden explícita «ejecuta» arrancaba Director con `auto_mode=false` y quedaba en `Review direct video prompts`. El inicio confirmado del Wizard activa ahora auto mode; preparar sin ejecutar continúa siendo visible, editable y manual.
- El pipeline anterior se reanudó pulsando su botón visible `Generate` y pasó de `paused` a generación H3 real. No se esperó a que terminara el render completo.

Pruebas de cierre del bloque:

- build de producción de UI;
- 56 pruebas focalizadas de acciones, selección/persistencia de canciones, estética y carrera de revisión;
- recorrido de navegador hasta creación, ficha, audio, staging, checkpoint y reanudación.

### Siguiente bloque

Comenzar **Bloque B — contexto canónico de sesión y selección**. Antes de migrar dominios completos, fijar el contrato único de IDs, `activeContext`, resultados, bloqueos `awaiting_input` y política `prepare/review/execute`. Después migrar una capacidad vertical pequeña y repetir el recorrido visible.

### Nota de relevo — Activity cerrada

**Acabé el minibloque Activity (prompt y procedencia) y comienzo el Bloque B.**

- Las generaciones nuevas congelan en la tarea canónica el prompt real completo (máximo 32 000 caracteres) y la herramienta que las inició.
- Story Lab distingue canción de historia y videoclip; Director identifica el flujo de videoclip; las generaciones comunes conservan un fallback visible de Studio por modalidad.
- El footer enseña una versión truncada, ofrece el texto completo al pasar el cursor y permite copiarlo con clic tanto en la barra como en el historial.
- Verificado con pruebas UI, contratos backend y build de producción. No fue necesario reiniciar ni interrumpir el render activo.

### Nota de relevo — Bloque B/D cerrado

**Acabé el Bloque B/D (contexto canónico) y comienzo el Bloque E (`awaiting_input`).**

- Existe una instantánea versionada `hocuspocus.wizard_context` que acompaña cada turno del LLM.
- Contiene IDs canónicos de workspace, entidad, proyecto, producción, cue, output, tarea y pipeline, además de selección, drafts, artifacts, capacidades y workflow activo.
- Las etiquetas siguen siendo solo presentación: no se convierten en identidad ni cruzan workspaces.
- La serialización es JSON segura, corta ciclos y conserva referencias compartidas sin enviar stores vivos.
- Se mantiene el snapshot compacto anterior durante la migración de capacidades.

### Nota de relevo — Bloque E cerrado

**Acabé el Bloque E (`awaiting_input`) y comienzo el Bloque C (contrato global).**

- Workflow y paso pueden quedar en `awaiting_input` con pregunta, campos, opciones, recomendación, entidades ya resueltas, versión y respuesta persistidas.
- La respuesta valida versión/paso, rechaza campos extra y modifica únicamente los campos declarados antes de reanudar exactamente el mismo paso.
- El chat muestra la pregunta y opciones; la respuesta se entrega directamente al runtime, sin pedir al LLM que reconstruya el workflow.
- La ambigüedad de audio en canción → Video3D deja de fallar: pregunta qué output exacto usar y continúa desde `attach-audio`.
- Backend, recarga, duplicados, seguridad contra prototype pollution, chat y flujo rítmico están cubiertos por pruebas focalizadas.

### Nota de relevo — Bloque C cerrado

**Acabé el Bloque C (contrato global) y comienzo el Bloque F (migración de capacidades).**

### Nota de relevo — Bloque F cerrado

**Acabé el Bloque F (72/72 acciones bajo el registro y contrato común) y comienzo el Bloque G (pruebas y observabilidad).**

El catálogo de acciones, la guía que recibe el LLM, el JSON Schema, el parser y
el ejecutor se derivan ya del mismo registro. Un test exhaustivo falla si se
añade una acción al tipo `AgentAction` sin registrar su capacidad. Studio,
navegación de Labs, cola/workspaces, Comics, Character Kit y Video Editor ya no
dependen de una descripción paralela para ser controlables por el Wizard.

- `EntityRef`, `ArtifactRef`, `CommandEnvelope`, `CommandResult`, `NavigationTarget`, `PresentationPlan` y `StructuredError` comparten una frontera JSON validada.
- El contrato rechaza IDs vacíos, referencias entre workspaces, ciclos, prototipos no planos, valores no reproducibles y claves de idempotencia incoherentes.
- El runner común devuelve, junto al informe existente, el comando canónico y un resultado con entidad, artifacts, task IDs, pipeline IDs y navegación verificables.
- Las claves idempotentes incorporan workspace, capacidad, target canónico e input serializado de forma estable.
- El contrato no depende de React y queda listo para trasladarse a backend/API sin duplicar semántica.
