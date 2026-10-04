# Moncloa Park 1x01 por MCP: problemas, dificultades y carencias

**Fecha:** 2026-10-04.
**Código:** `development` en c5dfcc72 (con #807, #808, #809 y #810: `from_script`, `produce`, perfil `series` y sonido equilibrado), más los tres arreglos de `flat_rig` de esta rama.
**Instancia:** aislada en :42060, con su propio espacio de trabajo `moncloa-park`.
**Encargo:** una serie nueva, distinta de Valle Inquietante pero con el mismo humor y la misma técnica. Es una sátira de Pedro Sánchez desde el punto de vista de la oposición, en recortes 2D tipo South Park, con voces locales, lip-sync y Video 2D/3D, sin generación de vídeo. Hecha solo con MCP, como un agente externo, y como mínimo con la calidad de Valle Inquietante 1x02. Solo en español: es para consumo en España.

## Resumen

**La serie y el capítulo.** «Moncloa Park», 1x01 «Nunca jamás»:

- Junts tumba los decretos de vivienda. Pedro, que en 2019 prometió traer a Puigdemont de vuelta, le llama para reconquistarlo.
- Borja, su jefe de Argumentario, le ensaya la sesión de control a base de jeta: el Peugeot, Ábalos y Koldo, Cerdán, la fontanera, el fiscal general, La Mareta, Podemos y Bildu.
- La máquina del fango está en el sótano. Los cinco días de reflexión se pasan en una azotea en Video 3D y duran cinco segundos.
- En el Congreso, «¡que viene el lobo!» trae a un lobo de alquiler cada vez más harto.
- Puigdemont pide el Falcon y esa es la única línea roja.
- En Casa Paco: «¿Y esto quién lo paga?» «Tú, Paco».

**Criterios de la sátira.** Se parodia la figura pública y sus decisiones; las voces son sintéticas y se describen por rasgos; hay un cartel de parodia al inicio; nada se presenta como noticia (la tele del bar es un canal inventado); no salen familiares ni personas privadas. Los procesos judiciales se citan con su estado real, verificado el 4 de octubre de 2026 (condenados, investigados o archivados).

**En cifras.**

- 6 personajes nuevos (Pedro, Puigdemont, Borja, Paco, el Manual y el Lobo), 13 poses, 9 fondos 2D y 1 plantilla 3D personal.
- 7 pistas de música (ACE-Step) y 13 efectos de sonido (MMAudio).
- 36 voces diseñadas (6 personajes × 2 idiomas × 3 semillas). Se diseñó también el inglés antes de decidir que la serie es solo en español.
- 70 planos y 100 frases.
- Capítulo de 5:55, a −16 LUFS (pico −1,3 dBTP), con 100 subtítulos y copia con subtítulos incrustados. Igual que el 1x02 en español (5:55).
- Render en servidor de los 70 planos en ≈40 min (≈35 s por plano), ningún plano fallido. WER medio de las voces: 0,04. Montaje: ≈3 min.

**Cómo se hizo.** Todo por MCP, siguiendo la guía:

1. `series.guide`.
2. `series.create` con canon, reglas, hechos verificados y reparto.
3. Kits: `generation.image`, `studio.key`, `characters.save` y `characters.rig.flat`.
4. Voces: `qwen3_tts_voicedesign` con `qa.speech`, y `voicesByLanguage`.
5. Localizaciones: `series.asset.import` y `series.canon.approve`.
6. `series.episode.from_script` con `check: true`.
7. Render de seis planos de muestra con `render_native`.
8. `series.episode.produce`.
9. Arreglos de plano con `render_native` + `shot_ids` y montaje con `series.assembly.start`.

No se escribió TypeScript ni se tocó ninguna escena a mano. El único código tocado son los tres arreglos de `services/flat_rig.py` (problemas 1 a 3), que hicieron falta para que los personajes hablaran con la boca en la cara.

## Lo que funcionó muy bien

- **`from_script` con `check: true`** detectó de una vez todo lo que faltaba: kits, poses, audios y atrezo (un nombre de fichero mal escrito).
- **`produce` hizo el capítulo entero en una llamada a la primera:** voces, lip-sync, render 2D y 3D, aprobación y montaje con subtítulos.
- **El plano 3D con diálogo** (`kind: "3d"` con una plantilla personal) salió dentro de `produce` como cualquier plano 2D, con lip-sync.
- **`timing`, `pauseBefore`, `sfx`, `fx` y `props` en el guion** bastaron para el ritmo de las cartelas «TRES SEMANAS DESPUÉS», el ensayo rápido de preguntas y respuestas y el lobo.
- **`layout2d.perch`** sirvió para sentar al Manual en su mesita en todos los encuadres.
- **La recuperación tras un reinicio** funcionó: `jobs.leftovers`, `jobs.resume` y `jobs.discard`.

## Problemas, de más a menos grave

### Rig de personajes

1. **`characters.rig.flat` toma la camisa por los ojos cuando los ojos se tocan, y no avisa.** El estilo South Park pinta los ojos pegados y, sin una línea que los separe, `find_eyes` ve una sola mancha blanca ancha. Empareja entonces las dos mitades blancas del cuello de la camisa. En las cuatro poses de Pedro puso el parpadeo y la boca en el pecho (al 44 % de la altura en vez del 22 %) y dejó la boca pintada en la cara. Respondió `unwipedPoses: []`, así que solo se veía en la imagen de revisión. **Arreglado en esta rama:** una mancha más de 1,4 veces ancha que alta se corta por su columna más estrecha. Faltaría además un aviso cuando los «ojos» salen por debajo de un tercio de la figura.
2. **Una boca fina de trazo no se detecta y queda doble.** En el puño de Pedro, en sus tres semillas, la boca es una línea de 1–2 px que se parte en trozos de 5–10 px, y el mínimo es 12. El rig dibuja la boca nueva sin borrar la pintada. **Arreglado:** un segundo intento con umbral más suave y trozos de 5 px.
3. **Volver a hacer el rig ignora una pose sustituida.** El rig arranca siempre de las imágenes que guardó el primer rig en `provenance`, aunque la pose se haya cambiado con `characters.save`. La pose nueva de gafas volvió a salir con la boca en el pecho. **Arreglado:** la original solo sustituye a la salida del propio rig (`kit-<id>-<pose>-rig-…`). Mientras el servidor no cargó el arreglo, hubo que guardar la pose con otro id (`chulo`).
4. **Una pose con gafas de sol no se puede rigear.** Sin ojos blancos no hay dónde poner el parpadeo y el rig vuelve a coger la camisa. La pose icónica (gafas de sol y brazos cruzados) se cambió por «gafas bajadas sobre la nariz y ojos por encima». Aun así, el parpadeo se pinta un instante sobre las gafas. Faltaría un modo «pose sin parpadeo» y poder marcar la boca a mano.

### Cola de generación

5. **`priority` en `generation.image` está anunciado pero se rechaza.** `tools/list` lo publica en todas las `generation.*` (`routers/wangp_mcp.py`), pero el manejador de imagen exige exactamente `version`, `intent_id` e `input` y responde «Use version, intent_id and input for the generation tool» (`routers/image_generation_commands.py`). Funciona dentro de `input.params.priority`, que el esquema no menciona.
6. **Un trabajo en cola no se puede adelantar ni cancelar.** La prioridad solo se fija al admitir. Los fondos de 1920×1088 (≈3 min cada uno), admitidos antes, dejaron detrás las poses (≈30 s), que eran las que desbloqueaban los kits. `jobs.discard` solo vale para restos tras un reinicio y no hay `jobs.cancel`. Hubo que admitir otra semilla de cada pose con prioridad: ≈8 min de GPU de más.

### Producción

7. **«Llamar otra vez a `produce` para volver a montar» rerenderiza el episodio entero.** Tras arreglar un plano con `render_native` + `shot_ids`, como dice la guía, `produce` volvió a empezar los 70 planos (≈40 min) aunque todos tenían toma aprobada. Se canceló y se montó con `series.assembly.start` (≈3 min). `produce` debería saltarse lo aprobado, o tener `assemble_only`, y la guía debería decirlo.
8. **El diccionario de pronunciación no llega al render.** `voiceProfile.pronunciationDictionary` está en la serie y en el formulario, pero `render_native` no lo usa. Para que «Peugeot» no suene a «peyote» habría que cambiar el texto, y entonces el subtítulo sale mal escrito.
9. **El WER castiga los nombres propios.** «Vildu» por «Bildu», «Ávalos» por «Ábalos», «ser dan» por «Cerdán» o «Puig de Mont» suenan igual, pero suben el WER a 0,5–1,0 en frases cortas y provocan tomas de repetición. Habría que normalizar b/v, tildes y los nombres del canon antes de comparar, como ya se hace con los números.
10. **`produce.status` no da el avance en números.** `progress` es «Shot e1s03», sin «3 de 70». Para saber cuánto falta hay que consultar `render_native.status`.
11. **El montaje abre con 9 s de silencio** cuando las primeras cartelas no llevan música, y nada lo avisa. Se arregló poniendo música bajo el aviso de parodia y sonido bajo «2019».

### Imagen y composición

12. **«South Park style» puede devolver personajes reales de South Park.** Una mesita vacía salió con Cartman detrás. Es un riesgo de derechos: hay que revisar cada imagen. El prompt de estilo no debería nombrar la serie, y el negativo debería excluir personajes existentes.
13. **El prompt de personaje da por hecho un cuerpo humano.** Para el Manual (un libro con cara), el prefijo de personaje generó dos niños con gorro. Falta un tipo «objeto o criatura con cara» en `characters.styles`.
14. **`studio.key` no recorta y no dice dónde está el objeto.** La mesita recortada sigue midiendo 1152×896 con márgenes transparentes, y unos píxeles sueltos en los bordes hacen que la caja del alfa sea la imagen entera. Los `top` y `widthRatio` de `perch` se calcularon a mano. Faltaría que `studio.key` devolviera la caja del objeto o recortara.
15. **Una `x` explícita saca de cuadro a un personaje solo en plano medio.** El planificador solo centra a un personaje en solitario si no se le da `x`. Con la `x` de su sitio en la escena, el Manual salió cortado. La guía debería decirlo.
16. **Un personaje dentro de una tele no tiene soporte.** «Pedro en la tele del bar» se hizo con la imagen del kit como atrezo diminuto y su voz fuera de cuadro: funciona, pero no mueve la boca. Faltaría un `screen` 2D, como el `screen.talk` del 3D.
17. **El texto largo de una cartela final no se lee sobre un fondo claro.** Hubo que pasarla al fondo oscuro. Faltaría una banda oscura detrás del texto.

### 3D

18. **No hay plantillas 3D del mundo real.** No hay avión, parlamento ni oficina: solo mundos de fantasía o pixel. Solo encajaba «Azotea de noche».
19. **Meter un personaje del kit en una plantilla 3D es editar JSON.** Hubo que cambiar el hueco a `media: image`, `surface: cutout`, `sourceRef` y `character`, y registrarlo con `world3d.templates.user.put`. Con la posición por defecto Pedro salía al ≈9 % de la altura, y hicieron falta tres exportaciones de prueba para encuadrarlo sin cortarle la cabeza en el acercamiento. Falta «pon este personaje en esta plantilla, a esta altura de cuadro».

### Herramientas y mensajes

20. **`series.templates` y `jobs.leftovers` rechazan `workspace`.** El error dice «Use version 1 with input fields: » (lista vacía) o «accepts only version and an empty input». Es el mismo caso que `scenes.effects.apply` en el 1x02.
21. **`from_script` con `check: true` repite cada problema en cada plano.** Sin kits devolvió 120 líneas como «shot 2 (e1s02): pedro has no Character Kit», cortadas en «(+107 more)». Sería mejor agrupar: «pedro, borja… sin kit (planos 2, 3, 5…)» y «faltan estos 15 audios».
22. **Elegir voz sigue siendo a ciegas** (1x02, #7). `qa.speech` no da la similitud entre la voz ES y la EN, y el kit debería usar como transcripción de referencia lo que de verdad dice la toma (Whisper oyó «amistía»), no el texto pedido.

## Qué falta para que una serie nueva sea fácil

1. **Rig fiable sin revisión a ojo:** los arreglos 1 a 3 de esta rama, un aviso cuando la cara sale donde no debe y poses sin parpadeo (problema 4).
2. **Una cola gobernable:** prioridad que funcione en imágenes, y poder adelantar y cancelar (problemas 5 y 6).
3. **Volver a montar sin rerenderizar,** y avance en números (problemas 7 y 10).
4. **Voces:** pronunciación por diccionario y WER que entienda el español (problemas 8 y 9).
5. **3D:** poner un personaje del kit en una plantilla con una herramienta y tener escenarios del mundo real (problemas 18 y 19).
6. **Estilo seguro:** prompts que no nombren South Park y tipos de personaje no humanos (problemas 12 y 13).
