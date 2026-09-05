# Informe: Series y tráilers con MiniMax H3

Fecha: 20 ago 2026  
Alcance: cómo se planifican, compilan y renderizan hoy Series Lab y el Creador de tráileres; cómo se comporta MiniMax (chat M3 + H3); qué mejorar primero.  
No es una especificación de implementación. No toca launchers.

---

## 1. Resumen

Los tráilers y las series **no usan el mismo camino hasta H3**.

| | Tráiler | Series Lab |
|---|---|---|
| Dónde vive | Story Lab (`projectType: trailer`) | Lab propio (`Series → Season → Episode → Shot → Attempts`) |
| Planner LLM | 4 etapas de Story Lab + Director *short film* | 5 etapas propias (outline → script → shots → validación → delta de canon) |
| Compilación H3 | Director (`h3_dialogue`, compact compile, VOCAL TIMELINE) | `series_render.shot_generation_prompt` — **otro compilador** |
| Duración típica | 15–180 s (default 60) | Episodio ~75 s, planos 5 / 10 / 15 s |
| Canción | No se exige | No aplica |
| Continuidad entre piezas | Un solo tráiler | Canon congelado por episodio, routing de referencias por plano |
| MiniMax Chat | Escribe biblia + beats, luego Director escribe prompts de plano | Escribe outline/script/shots en JSON estricto |
| MiniMax H3 | Un pase Director (T2V, first-frame o Ref2VA) | Un job de generate por plano, intentos append-only |

La mejora más barata y visible es el **tráiler**: ya entra por Director, dura un minuto, no arrastra canon entre episodios, y el usuario puede rehacer plano a plano. Series es el producto a largo plazo, pero hoy su compilador de prompts **no hereda** los arreglos de compactación que acabamos de poner en Director.

El límite físico que manda en ambos: **H3 no corta a ritmo de tráiler de cine**. Mínimo 124 frames ≈ **5,17 s**. Máximo 345 ≈ **14,4 s**. Un tráiler de 60 s son como mucho ~11 planos. Un episodio de 75 s son ~7–8 planos de 10 s, o hasta 15 si todos van al mínimo.

---

## 2. Cómo se comporta MiniMax aquí

### 2.1 Chat (M3) — planificación

- En Settings el texto es `llm_provider: minimax`, modelo `MiniMax-M3`.
- M3 es **API**, no GGUF. Cargarlo como local pedía `huggingface.co/MiniMax-M3/...Q4_K_S.gguf` → 404. Corregido en `9fad346` (`normalize_minimax_chat_routing` + clave en `_ensure_llm_loaded`).
- El 401 de chat era la clave que no se enviaba en Director. El path de `writing_provider: minimax` (`_scoped_writing_llm`) sí la mandaba.
- M3 escribe bien JSON con schema cerrado (Series lo usa). En prosa de videoclip tiende a:
  - meter silencio y continuidad en campos de “mundo”;
  - describir el **fotograma final** (“By the final beat”, “frozen”) en vez de acción continua;
  - rellenar con boilerplate en inglés;
  - `overall_soundscape: Silence` o novelas de sonidos que no hay.
- Music Generation (`music-3.0`) está **cerrada a usuarios nuevos** desde el 20 ago 2026. Los tráilers no la necesitan. Series tampoco. No bloquear Series/tráilers por la API de música.

### 2.2 H3 (vídeo nativo)

Lo que H3 hace bien, visto en chistes, videoclips y el short `aa7b3e3f`:

- Contrato `<d>[Spanish] …</d>` con una frase corta y el hablante nombrado delante (`Mario dice:`).
- Un plano visual concreto + **una** línea de soundscape diegética + `non_diegetic_music: N/A`.
- Resolución real del tensor (`960x544` / `544x960`). El modelo obedece más al canvas que a un párrafo “portrait lock”, aunque Director sí inyecta `PORTRAIT COMPOSITION LOCK` en 9:16.

Lo que H3 hace mal o no puede:

- Cortes de 1–2 s. El suelo son 5,17 s. Un gag de 8 sílabas se **estira** a hablar casi todo el plano (lo vimos en los 45 chistes).
- Dos hablantes en el mismo clip: visemas y autoridad vocal se pelean. Series ya fuerza **un speaker por plano** (bien). El tráiler, al ir por short film, **puede meter varios**.
- Casco / boca no visible: el modelo igual “habla”.
- Listas de ausencias (`no hay coches`, `remain silent` novelado) y contratos de idioma en el cuerpo visual: el modelo se pone a ilustrar el texto meta.
- Letra de canción dentro de `<d>` si también hay audio drive (videoclips). En tráiler no hay canción; el riesgo equivalente es **VO + diálogo + “closed mouth”** a la vez.

Referencia de forma buena (~1800 caracteres, short `aa7b3e3f`):

```
integrated_multimodal_description: [Shot 1] … Nombre dice: <d>[Spanish] …</d>
overall_soundscape: una línea diegética.
non_diegetic_music: N/A
```

H3 inyecta igual un `VOCAL TIMELINE LOCK` en inglés. Está también en el short bueno; no es un bug, pero no debe comerse el 70% del prompt.

---

## 3. Tráilers — cómo están

### 3.1 Flujo real

1. Story Lab tipo **Tráiler cinematográfico** (sin canción).
2. Planner de 4 etapas: concepto, protagonistas, mundo, arco de **6–12 beats**.
3. El usuario edita formato (theatrical / teaser / character), narración (hybrid / VO / diálogo / visual), spoilers, intensidad, tagline, title cards, 15–180 s, landscape o portrait.
4. `buildTrailerAdaptation` envuelve **el planner de corto** (`buildShortFilmAdaptation`) con un brief de “CREATE AN EPIC CINEMATIC STORY TRAILER” y un arco obligatorio:
   - Cold open 0–10%
   - Promise 10–30%
   - Disruption 30–50%
   - Escalation 50–80%
   - Breath 80–90%
   - Final hook 90–100%
5. Director planifica planos H3 y genera (T2V, first-frame, o Ref2VA). Direct video **no exige fotos de identidad**.
6. Montaje ordenado, reabrir, regenerar plano a plano, Video Editor.

Código: `ui/src/features/stories/adaptations.ts`, `trailerDefaults.ts`, Story Lab panel, `_launch_runtime.py` (beats 6–12, 4 stages, “Never require a song”).

### 3.2 Lo que ya está bien

- Producto separado del videoclip: no obliga a MiniMax Music.
- Arco de tráiler escrito, no un sinopsis ni un episodio.
- “Nunca el final de la historia” está en el contrato.
- T2V directo: mismo truco que nos funcionó en videoclips de enanos/orcos (M3 escribe, H3 rueda).
- Al pasar por Director, **sí recibe** compact compile, idioma en `<d>`, VOCAL TIMELINE, portrait lock.
- Controles de spoiler / intensidad / title cards (estos últimos respetan `allowClipText`).

### 3.3 Problemas

**A. El tráiler es un corto disfrazado.**  
No hay `TrailerPlanner`. Short film está hecho para setup → clímax → resolución. El brief intenta frenarlo (“NOT A SHORT FILM”), pero M3 sigue escribiendo escenas completas, repetición de localización+acción, y diálogos de capítulo. Los porcentajes del arco no se convierten en **segundos ni número de planos**.

**B. Mentira de ritmo.**  
El texto pide “acortar planos en la escalada”. H3 no puede. Un tráiler de 60 s con el mínimo H3 son ~8–11 bloques de cinco segundos. Si el planner pide 12 beats de 2 s, el compile los **sube** al lattice y el montaje se siente lento, no “tráiler”.

**C. Habla de más.**  
Hybrid/diálogo + short film = varios `<d>` por plano o VO + personaje a la vez. H3 mezcla bocas. Visual-only está en la UI y es el modo más seguro; no es el default (`hybrid`).

**D. Title cards vs H3.**  
H3 inventa texto ilegible si se le pide un cartel. El contrato de “at most three cards” pelea con `NO VISIBLE TEXT LOCK` del compile. Si `allowClipText` está off, mejor ningún cartel y el gancho visual.

**E. Identidad.**  
T2V sin refs: el protagonista cambia de plano a plano (lo vimos cuando no hay first-frame). Con refs, hay que **enrutar solo las del plano**, igual que Series. El tráiler hoy reutiliza las refs del corto, no el router de Series.

**F. Post.**  
No hay un recorte automático al “beat” de tráiler. El Video Editor puede recortar a mano un plano de 5 s a 1,8 s y **ahí** nace el ritmo de tráiler. Eso no está en el pipeline.

### 3.4 Cómo mejorar tráilers (empezar aquí)

Orden práctico, de más impacto a menos:

1. **Planificar contra el lattice H3, no contra Hollywood.**  
   Tabla para 60 s: 8–10 planos. Asignar segundos del arco de verdad (p. ej. cold open = 1 plano de 5 s, escalada = 3–4 planos de 5 s, breath = 1, hook = 1). Dejar de pedir “planos más cortos”.

2. **Planner de tráiler propio** (no short film).  
   Schema: `role: cold_open|promise|disruption|escalation|breath|hook`, `durationSeconds` en {5,10}, un beat visual, **0 o 1** línea hablada, `speakerId` o `narrator`, sin resolución. Prohibir repetir `locationId+action`.

3. **Default narración = visual**, VO opcional.  
   Si hay VO: una voz, `<d>[Spanish] …</d>` con “el narrador dice:”, planos mudos **sin** audio drive. Si hay diálogo: un speaker, plano de reacción mudo al lado.

4. **Montaje que recorta.**  
   Generar a 5,17 s y recortar en assembly a la duración de beat deseada (1,5–3 s en escalada). Eso sí parece tráiler. Guardar el master H3 intacto (append-only).

5. **Misma forma de prompt que el short bueno.**  
   Cuerpo visual concreto, hablante nombrado, una línea de sonido del sitio (viento, pasos, no “Silence” ni “low room tone genérico”), `N/A` de música salvo que el usuario ponga banda después.

6. **Identidad.**  
   Un still de protagonista (Character Creator / una foto) en todos los planos donde salga. T2V puro solo para teaser de mundo sin cara recurrente.

7. **Title cards fuera de H3.**  
   Superponer título/tagline en el editor, no pedirlas al modelo.

Con eso un tráiler de 60 s es un producto cerrable **esta semana de trabajo**, sin esperar al canon de Series.

---

## 4. Series — cómo están

### 4.1 Flujo real

Jerarquía: `Series → Season → Episode → Scene → Shot → Attempts` (append-only).

1. Setup: escritura (MiniMax M3), imagen, H3.
2. Propuesta de canon (texto, opcionalmente imágenes). El usuario **aprueba** una revisión. El LLM no muta el master solo.
3. Episodio: outline 4–8 beats → script (máx. **8 escenas**) → shots → validación → delta de canon (hechos a aceptar a mano).
4. Routing determinista de referencias por plano (`series_reference_router`): no se mandan todas las caras a todos los planos; el speaker tiene prioridad.
5. Render de seleccionados / faltantes / fallidos / todos. Cancelar registra intento interrumpido; el retry **añade**, no pisa.
6. Aprobar/rechazar intentos, abrir secuencia en Video Editor.
7. Hechos de continuidad: solo los aceptados pasan al siguiente episodio.

Persistencia: `.series-library-v1.json`, jobs en `.series-jobs-v1/{planning,render}/`. Cada episodio congela el canon con el que nació.

Planner (`series_planning.py`): JSON schema cerrado, un speaker por plano (`speakingCharacterIds` max 1), diálogo solo en `dialogueBeats.text` (idioma de la serie), visuales en **inglés**. Prompt de shots pide ~`target/10` planos, 5/10/15 s, no alargar un clip para llenar el capítulo.

Render (`series_render.py`): arma el prompt H3 **en casa**:

- T2V / first-frame: `integrated_multimodal_description: [Shot 1] {escena} {diálogo}`
- Ref2VA: `subject_definitions` / `summary` / `retention_analysis` / `detailed_description`
- Soundscape: `shot.audioDirection` o, si falta, **“Low room tone and the synchronized sounds of visible objects and physical actions.”**
- `non_diegetic_music: N/A`
- Identity lock del protagonista si `protagonistConsistency`
- Un speaker: `Nombre (S1), emotion, delivery: <d>[Spanish] …</d>`

No llama a `compile_h3_official_prompt` / compact soundscape de Director.

### 4.2 Lo que ya está bien

- Canon con revisión humana. Hechos no se cuelan solos.
- Un hablante por plano y split automático si el LLM junta un diálogo.
- Referencias por plano, no el pack entero.
- Intentos con prompt efectivo, seed, frames, manifiesto, timestamps.
- Lip-sync declarado **best-effort** (correcto con H3).
- Escala de episodio: más planos, no clips > 15 s.
- Bootstrap de serie conocida es borrador sin aprobar (derechos a cargo del usuario).

### 4.3 Problemas

**A. Dos compiladores H3.**  
Director ya compacta (silence si no hay sonido, no novelas de audio, `<d>` limpio). Series sigue con el soundscape genérico que **pedimos quitar** en videoclips. Un episodio sonará a “oficina con todo lo que se ve” aunque el plano sea un desierto. Unificar: Series debe llamar al mismo compile que Director, o copiar su política.

**B. Biblia entera en cada etapa.**  
`planning_prompt` serializa series + canon + characters + locations + props + prior summaries. En M3 eso es caro, lento y el modelo **repite** identity lock en cada `prompt` de shot (el render lo vuelve a pegar). Mandar un *digest* (identity de los IDs del episodio, no los 12 personajes).

**C. Script de 8 escenas vs 1 speaker.**  
Una conversación de tres personas son 3 planos mínimo. 75 s / 10 s = 7–8 planos. O el capítulo es mudo con poco diálogo, o hay que subir el techo de escenas/planos y aceptar episodios “piloto corto”, no TV de 22 min. El techo de 720 planos existe en código; el script de 8 escenas es el cuello.

**D. `prompt` + `action` + identity lock.**  
El planner escribe `prompt` en inglés y `action`; el render concatena ambos + cámara + “no captions”. Fácil duplicar y contradecir. Mejor: el planner solo rellena campos estructurados; el compile genera el string H3.

**E. Continuidad visual entre planos.**  
First-frame suelto no es el último frame del plano anterior. Hay `continuityFromShotId` y estrategias first_last / references, pero el default `auto` a menudo cae en T2V y **cambia la cara**. El piloto coherente necesita last-frame → next first-frame o Ref2VA con el mismo still.

**F. Diálogo corto estirado a 5,17 s.**  
Igual que los chistes. El timing hint de Series (`From x to y seconds`) ayuda si la línea es mucho más corta que el plano; si no, H3 recita lento. Solución: negocio mudo en `action` + habla 1,5–2,5 s, o dos frases.

**G. Lip-sync vs cascos / criaturas.**  
El router no sabe “esta entidad no tiene boca visible”. Hace falta un flag `canLipSync` en el personaje.

**H. Known-series bootstrap.**  
M3 inventa con conocimiento general. Está acotado y sin auto-aprobación, pero es el sitio más fácil de colar copyright y canon falso. La UI tiene que gritar “verifica” más que ahora.

### 4.4 Cómo mejorar Series (después del tráiler, o en paralelo el compile)

1. **Un solo compile H3** para Series y Director (prioridad: soundscape, `<d>` con nombre, sin contrato de idioma en el visual, VOCAL TIMELINE corto).
2. **Planner produce datos, no el string final.** `action`, `dialogueBeats`, IDs, `audioDirection` opcional. El render es determinista.
3. **Digest de canon** en el prompt de shots: solo entidades referenciadas + 8 hechos + identity de 1 línea.
4. **Cadena de frames** en el piloto: plano 2 usa el último frame aprobado del 1 salvo corte explícito.
5. **Piloto de 60–90 s** como default de producto (no 22 min). La UI ya piensa en 75 s; venderlo como “piloto H3”, no como capítulo de TV.
6. **Rechazar / rehacer un plano** ya existe; exponerlo como el gesto principal (como Workspaces en videoclip).
7. **audioDirection vacío = silencio o un objeto visible**, nunca “low room tone and synchronized sounds of everything”.

---

## 5. Lecciones de lo que ya rodamos (chistes y videoclips)

Sirven tal cual para tráiler y series:

| Hallazgo | Qué hacer en tráiler/series |
|---|---|
| Forma ~1k–1,8k caracteres, un `[Shot 1]`, un `<d>`, un soundscape | Compile único |
| Hablante sin nombre (`Dice:`) vs `Mario dice:` | Siempre `Nombre (S1): <d>` |
| One-liner estirado a 5,17 s | Acción muda + ventana de habla corta |
| Soundscape “Sala quieta. Solo su voz” / `Silence` | Una línea del sitio (pasos, forja, paloma) |
| Estilo genérico “cómic cinematográfico” en todo | Preset por serie / visualStyle del canon |
| Mandaloiano con casco hablando | `canLipSync: false` |
| Planner “frozen / by the final beat” | Prohibir stills; pedir acción continua |
| `project world/franchise: No character speaks` | Silencio solo en VOCAL TIMELINE |
| Music API muerta | Tráiler/series no dependen de ella; bien |
| M3 remoto con clave | `writing_provider: minimax` en ambos labs |

El videoclip de enanos que gustó era: M3 escribe, H3 T2V, **0% performer a cámara**, canción encima, 7 planos de ~10 s. Un tráiler puede copiar esa cadencia (pocos planos largos, idea clara) y el editor recorta. Una series piloto, igual: 7–10 planos, un speaker, still de identidad.

---

## 6. Secuencia recomendada

**Ahora (tráilers), sin tocar Series:**

1. Documentar en UI el suelo de 5,17 s (“cada plano H3 dura ≥ 5 s; el ritmo de tráiler se recorta en montaje”).
2. Schema de beats de tráiler con cupo de planos/segundos por acto.
3. Default visual-only + un still de protagonista.
4. Recorte en assembly (guardar master, exportar cut).
5. Title cards en post, no en H3.

**Enseguida (código compartido):**

6. Series llama al compile H3 de Director (soundscape + `<d>`).
7. Quitar el soundscape genérico de `series_render`.

**Luego (Series piloto):**

8. Digest de canon en planning.
9. Last-frame continuity por defecto en el piloto.
10. Planner no escribe el string H3.
11. `canLipSync` y negocio mudo para líneas cortas.

**No hacer:**

- Prometer lip-sync cerrado.
- Prometer tráiler con cortes de 1 s nativos de H3.
- Meter MiniMax Music en el tráiler.
- Autorizar canon con el bootstrap de serie conocida.
- Duplicar otro compilador “por si acaso”.

---

## 7. Mapa de archivos

Tráiler:  
`ui/src/features/stories/adaptations.ts` (`buildTrailerAdaptation`)  
`ui/src/features/stories/trailerDefaults.ts`  
`ui/src/features/stories/StoryLabPanel.tsx`  
`app/_launch_runtime.py` (plan 4 etapas, beats 6–12)  
`app/services/director/planners/short_film.py` (el planner que realmente escribe los planos)  
`app/services/director/h3_dialogue.py` (compile que sí aplica)

Series:  
`docs/series-lab/IMPLEMENTATION.md`  
`app/services/series_planning.py`  
`app/services/series_render.py`  
`app/services/series_reference_router.py`  
`app/services/series_library.py`  
`ui/src/features/series/*`

H3 común:  
`docs/minimax-h3-prompting.md`  
`docs/h3-prompt-revisions.md`  
`app/services/minimax_h3_duration.py`  
`grokrespuesta.md` (auditoría de prompts de chistes y videoclips de hoy)
