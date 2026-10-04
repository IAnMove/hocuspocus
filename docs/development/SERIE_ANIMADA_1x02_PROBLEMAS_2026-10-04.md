# Valle Inquietante 1x02 por MCP: problemas, dificultades y carencias

**Fecha:** 2026-10-04.
**Código:** `development` en ec00fb26, con las fases 1A, 1B, 2 y 3 del plan (`SERIES_ANIMADAS_PLAN_2026-10-04.md`).
**Instancia:** aislada en :42052.
**Encargo:** un capítulo nuevo de la serie del 1x01, hecho solo con MCP y con al menos la calidad del 1x01, en español y en inglés.

## Resumen

**El capítulo.** «El vecino del fin del mundo» / «Doom Thy Neighbor»:

- Mark Zuckerberg se muda al lado del garaje de Kevin y quiere ficharlo.
- Dario se convence de que la inteligencia artificial nos va a matar a todos.
- Todos acaban en el Despacho Oval pidiendo que la prohíban, cada uno por su motivo (Dario por miedo, Elon para ponerse al día, Sam para tener la única licencia, Mark para que la gente vuelva al metaverso, Kevin para que Wrapper sea el número uno).
- El presidente dice que no, y Jensen gana.

**En cifras.**

- 54 planos y 75 frases por idioma, con dos personajes nuevos (Mark y Trump), una pose nueva (Dario alarmado) y cuatro localizaciones nuevas.
- Español: 5:55, a −16 LUFS, con 91 subtítulos, copia con subtítulos incrustados y miniatura.
- Inglés: 5:11, con 81 subtítulos. Es una versión de idioma del mismo episodio (`languageVersions.english`), no una segunda serie como en el 1x01.
- El 1x01 duraba 5:32 en español y 4:52 en inglés.

**Cómo se hizo.** Todo por MCP: imágenes, croma, kits, rig, voces, efectos de sonido y música, serie y episodio, render en servidor, plano 3D con recorte que habla, fondo 3D en bucle, segunda pasada de efectos y montaje. No se escribió TypeScript de la UI ni se generaron escenas a mano, a diferencia del 1x01.

**Tiempo.** Del guion al capítulo en español montado, unas dos horas. La versión inglesa, renderizada en paralelo, estuvo montada media hora después. El 1x01 llevó una noche entera de scripts propios.

**Dónde está.** Instancia aislada, espacio `uncanny-valley`, serie `uv-es`, episodio 2 (ids `e2s00…e2s53`). Personajes nuevos `uv-mark` y `uv-trump`; pose `alarm` en `uv-dario`. Los scripts del agente que llaman a MCP están en el scratchpad de la sesión (`av2/`).

## Qué funcionó a la primera

- **Personajes en un clic** (fase 1B). Dos kits nuevos con 2 o 3 poses cada uno:
  - `characters.styles` con el estilo del 1x01, `generation.image` con la base como referencia para las poses, `studio.key`, `characters.save` y `characters.rig.flat`;
  - poco más de un minuto por kit una vez generadas las imágenes.
- **Voces por rasgos** (no clonadas de las personas reales): `qwen3_tts_voicedesign` con tres semillas, `qa.speech` y `voicesByLanguage`.
  - En español, las 74 frases del render salieron a la primera, sin repeticiones (WER máximo 0,2).
  - Las bocas salen de `wav2vec2-phoneme`, con unas 41 señales por frase.
- **Render en servidor** (fase 2):
  - 53 planos 2D en unos 45 minutos;
  - framing, reparto, cartelas, atrezo con ancla o posición, música, cámara, entradas desde un lado y temblor de pánico;
  - Gary sobre su mesa con `transform` y atrezo por plano.
- **Recorte que habla en Video 3D** (fase 3): Elon en Marte con su pose de móvil, bocas por cue y su voz en la banda sonora.
  - Se hizo con `world3d.templates.user.put` (la escena del 1x01 como plantilla personal) y `world3d.scene.talk`, y salió bien en los dos idiomas.
- **Fondo 3D en bucle** (fase 3): el metaverso es `pixel-synthwave` renderizado como `plateAssetId` con `series.location.plate3d`; los planos de Mark lo usan detrás.
- **Versión inglesa** (fase 3): `series.episode.language_version.set` con las 75 líneas y las cartelas, y `render_native` con `language`. Las cartelas salen en inglés.
- **Segunda pasada** sobre la escena editable de cada toma:
  - `scenes.document.get`, luego `scenes.effects.apply`, `scenes.document.save`, `scenes.video2d.export` y `series.asset.import` como toma;
  - la usaron los efectos de pantalla y el cambio de tema en inglés.
- **Montaje** (fases 1A y 3): −16 LUFS, SRT/VTT, copia con subtítulos incrustados y miniatura del primer plano después de la cartela.

## Problemas encontrados

Ordenados por impacto. Los marcados **[BLOQUEA]** pararon el trabajo hasta encontrar un rodeo.

### Series Lab y render en servidor

1. **[BLOQUEA] Las versiones de idioma comparten la duración del plano.**
   - El render inglés guarda en `durationSeconds` la duración de su toma (e2s06: 2,17 s), y la toma española (1,71 s) ya no se puede importar («shorter than the shot»).
   - Con los dos idiomas a la vez, cada render pisa al otro.
   - **Rodeo:** reescribir la duración justo antes de cada importación.
   - **Arreglo propuesto:** duración por idioma, o que la comprobación de importación use la duración de la toma de ese idioma.
2. **[BLOQUEA] `series.episode.update` pisa la duración que puso el render.** Al reenviar los planos para cambiar la composición, `durationSeconds` vuelve al valor enviado (5 s), y las importaciones siguientes fallan. El servidor debería conservar la duración de la toma aprobada.
3. **[BLOQUEA] Un error de validación sale como «Internal Server Error».**
   - Los ids tienen que ser únicos en toda la serie: personajes, escenas y planos de todos los episodios. La escena `dario` chocó con el personaje `dario`, y `s00…s50` ya los usa el 1x01.
   - El `ValueError` sale como 500 sin decir qué id choca.
   - **Arreglo propuesto:** un 400 con el mensaje, y quizá ids de escena y plano con el ámbito del episodio.
4. **El canon vuelve a borrador por cambios que no son de canon.** Renderizar un fondo 3D (`plate3d` y `plateAssetId`) o mover un ancla de atrezo de una localización devuelve el canon a borrador, y el siguiente `series.episode.create` falla. Hubo que reaprobar el canon cuatro veces.
5. **No hay herramienta MCP para aprobar una toma de una versión de idioma.** `series.take.approve` solo aprueba la del original. Para el plano 3D y la segunda pasada en inglés hubo que reescribir `languageVersions` entero con `series.episode.update`.
6. **La música no se puede localizar por idioma.**
   - `layout2d.music` es un fichero, y la versión inglesa usa el mismo: la cabecera y los créditos sonaban con el tema cantado en español.
   - **Rodeo:** segunda pasada sobre esas dos tomas.
   - **Arreglo propuesto:** música por idioma (por ejemplo `languageVersions[lang].music`).
7. **Un solo hueco de audio por plano.**
   - `layout2d.music` es la única pista extra, y se usó para el camión, el bolígrafo, la bici, el ambiente de la calle o la fanfarria.
   - Un plano no puede tener a la vez ambiente, un efecto en un instante concreto y música.
   - `soundDesign` solo tiene un `stinger` común y ambiente por localización.
   - Falta `layout2d.sfx: [{file, start, volume}]`.
8. **No hay control del ritmo.**
   - Los silencios son fijos (0,35 s antes, 0,22 s entre frases y 0,45 s al final). El «...No.» del presidente dura 1,5 s sin pausa dramática.
   - El 1x01 tenía `intro`, `tail` y `pause` por frase.
   - Faltan `layout2d.timing` y `beat.pauseBefore`.
9. **No hay frases simultáneas, voz en off ni insertos animados.**
   - El guion se escribió para evitarlos. El 1x01 tenía el «Jensen» a coro, la voz en off de Gary sobre la pantalla, y el contador de visitas y la encuesta animados.
   - La noticia del 1x02 es una cartela de aviso sobre negro.
10. **Los planos 3D con diálogo no entran en el render en servidor.**
    - `render_native` solo hace planos 2D, y el plano de Elon en 3D se montó a mano por idioma con siete herramientas: voz, `qa.speech`, cues, escena, `talk`, exportación, e importación con aprobación.
    - Un `render_native` que haga también los planos `animation_3d` con `talk` cerraría el círculo.
11. **La toma no guarda su escena.** `attempt.metadata` es `null` y `sceneFilename` solo está en el `metadata` del asset de la toma.

### Personajes y voces

12. **No se puede rigear solo una pose nueva.**
    - `characters.rig.flat` exige incluir `base` («the blink comes from it») y rehace las nueve bocas compartidas y la imagen base.
    - Añadir «alarmado» a Dario cambió las bocas que usa el 1x01, y como un kit no tiene versiones, re-renderizar el capítulo 1 ya no daría lo mismo.
13. **`characters.rig.flat` borra la boca pintada.** Con Trump se pierde su morrito, el rasgo de la caricatura. No hay opción de conservar la boca original como boca de reposo.
14. **El parpadeo deja ver los contornos de los ojos:** círculos fantasma alrededor de los párpados cerrados.
15. **Elegir voz es a ciegas.**
    - `qa.speech` da WER, tono y ritmo, pero no si la voz encaja con el personaje ni si la inglesa y la española se parecen (similitud de hablante).
    - Hubo que leer transcripciones: Trump ES s22 decía «eso mejor».
    - Falta un `voices.pick` sobre varias semillas.
16. **`qa.speech` cuenta «A.I.» frente a «AI» como error** (WER 0,14 en una toma perfecta). Habría que normalizar las siglas con puntos, como ya se hace con los números.

### Imágenes, sonido y escenas

17. **Un efecto de sonido devolvió la base de datos de tareas como salida.**
    - `task.result_refs` de `generation.sfx` incluía `.maestro-tasks-v1.sqlite3-wal`, porque la detección de salidas compara el directorio y coge el WAL de SQLite.
    - Ese nombre llegó a la música de un plano, y la exportación lo rechazó («Each audioTrack needs a workspace audio filename»).
18. **El recibo de `generation.image` no refleja el resultado.** Con la tarea `completed`, `generation.receipt` sigue en `queued` con `artifacts: []`, y el fichero solo está en `task.result_refs`.
19. **El formato de las referencias de imagen cambió.** Las rutas absolutas de `uploads/` del 1x01 se rechazan. Las URL del workspace valen, lo cual es mejor, pero el error no da ningún ejemplo.
20. **Editar un fondo con referencia degrada el estilo.** «La misma calle con una fortaleza al lado» devolvió un cielo blanco y texturas realistas. Para mantener la continuidad hubo que componer el fondo del 1x01 con la fortaleza como atrezo anclado.
21. **Las imágenes de 1920×1088 tardan unas seis veces más que las de 896×1152** (≈3 min frente a ≈30 s) y retrasan voces y sonidos en la misma cola.
22. **Los efectos de pantalla tapan a los personajes y algunos apenas se ven.**
    - `manga_impact` centrado cubre la cara del que grita.
    - `speedlines` son rayas finas casi invisibles sobre fondos claros, incluso con intensidad 2.
    - Un efecto no se puede poner detrás de un personaje.
23. **`scenes.effects.apply` rechaza `workspace`**, cuando casi todas las herramientas lo exigen.
24. **`world3d.scene.preview` no pinta los mundos pixel o atmos:** suelo gris vacío. Para ver una plantilla hay que exportarla.
25. **Los subtítulos parten frases.** El SRT corta «Me he sentido muy / identificado.», y la segunda parte dura 0,95 s.
26. **El bucle del fondo 3D tiene costura:** el último segundo es más oscuro que el primero. Aquí no se nota, porque ningún plano supera los 8 s.
27. **`qa.export` da «fail» a un capítulo correcto.**
    - Marca como problema las cartelas sobre negro (aviso y noticia), el silencio bajo el aviso inicial y las pausas normales de 0,4–1 s entre frases.
    - Devuelve `duration: null`.
    - No sabe qué partes son cartelas ni que en un diálogo hay pausas, así que su veredicto no sirve para un episodio.

## Qué falta para que «un capítulo» sea un clic

1. Duración, música y aprobación por idioma: problemas 1, 5 y 6.
2. Pistas de efectos y ritmo por plano en `layout2d`: problemas 7 y 8.
3. Planos 3D con diálogo dentro de `render_native`: problema 10.
4. Rig incremental y versiones de kit: problema 12.
5. Que los cambios de render y de composición no toquen el canon: problema 4.
6. Errores de validación legibles e ids con ámbito de episodio: problema 3.
