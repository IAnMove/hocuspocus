# 4/6 · Personajes 3D: recorridos, mezcla, objetos, cara y manos

> Hoja de ruta de calidad local (2026-10-03). Serie: [1 Render máster](01-render-master.md) ·
> [2 Iluminación HDRI y LUT](02-iluminacion-hdri-lut.md) · [3 Biblioteca CC0](03-biblioteca-cc0.md) ·
> **4 Personajes 3D** · [5 Sonido](05-sonido.md) · [6 Control de calidad](06-control-calidad.md)
>
> Base comprobada: `origin/development` `ce070bee` más el PR #765 (rig humanoide revisado). Estado: aprobado por el usuario el 2026-10-03, sin código (ver «Decisiones del usuario»).
> Requiere que el PR #765 esté en `development` antes de la fase 1.

## Objetivo

Que un personaje rigueado camine por donde diga la escena sin patinar, pase de un clip a otro con suavidad, se siente en una
silla real o sostenga un objeto, parpadee y mire de forma natural, y mueva algo más que una manopla. Todo determinista y en CPU.

## Qué hay hoy (comprobado en el código)

`S/` = `ui/src/features/scene3d/`.

- **Rig** (PR #765, `app/services/humanoid_rig/`):
  - **Esqueleto:** 25 huesos sin dedos, mandíbula ni ojos (`names.py:33-59`).
  - **Clips:** se hornean en el servidor con un worker NumPy (`worker.py`, `motion.py:179-191`).
  - **Objetivos de IK locales:** los pies van relativos al tobillo en reposo (`Pose.plant`, `motion.py:163`) y las manos
    relativas al pecho (`Pose.reach`, `:168`). No hay objetivos en coordenadas del mundo ni de un objeto.
  - **Caminar y sentarse:** se camina en el sitio (`clip_recipes.py:84-97`). `sit_down` se sienta en un asiento invisible con
    desplazamientos fijos (`:233-243`).
  - **Recorridos importados:** el retarget quita el desplazamiento de la cadera (`retarget.py:343-352`).
- **Movimiento del slot en Video 3D:**
  - Un solo tramo, recto o Bézier cuadrático con `via` (`S/performance.ts:36-53`, `S/types.ts:146-152`).
  - La velocidad del recorrido no está ligada a la del clip: `fitClipPlayback` (`performance.ts:14-21`) solo ajusta la
    duración, **así que los pies patinan**.
- **Clips en Video 3D:**
  - Una acción por slot (`S/gpu.ts:280-297`), posicionada de forma determinista con `setTime`.
  - **No hay `crossFadeTo`, fundidos, secuencia de clips ni keyframes.**
- **Cara:**
  - La boca y los ojos se pintan con un shader sobre la malla (`speech/mouths.ts:50-67`, `speech/eyes.ts:149-172`) y siguen
    al skinning.
  - Hay 9 visemas sacados de Rhubarb o de fonemas CTC (`app/services/scene3d_speech.py`, `phoneme_ctc.py`).
  - **El parpadeo es un temporizador fijo** de 4,7 s (`eyes.ts:135-139`).
  - **No hay mirada:** ni pupila, ni look-at, ni gestos de cabeza al hablar.
  - Los GLB generados no tienen morph targets.

## Diseño

1. **Recorridos sin patinar, horneados en el servidor.** Se manda al worker el recorrido completo: puntos de paso,
   tiempos, la velocidad o el clip (caminar o correr) y el suelo. El worker devuelve un clip con desplazamiento de raíz real
   en el que los pies quedan **fijos en coordenadas del mundo** mientras apoyan. Usa la IK de piernas que ya existe, con
   objetivos del mundo en vez de relativos al tobillo.
   - En Video 3D, el slot reproduce el clip con su desplazamiento y no usa `motion`.
   - Las curvas giran el cuerpo de forma progresiva y los pies pivotan sobre el apoyo.
   - La zancada se adapta a la velocidad dentro de un margen, y fuera de él se cambia de caminar a correr.
2. **Secuencias de clips con fundido determinista.** Un campo `clips: [{clip, start, duration, fade}]` en el slot sustituye
   al clip único, que sigue siendo válido. Los pesos de cada acción se calculan como función pura del tiempo de escena, nunca
   acumulando estado de un fotograma a otro, para que el motion blur por acumulación de [1 Render máster](01-render-master.md)
   siga siendo correcto.
3. **Objetos e interacción.**
   - Objetivos en coordenadas del mundo o de un objeto: sentarse en el slot X (altura y posición del asiento a partir de su
     caja), alcanzar un punto y mirar a un objetivo.
   - Sostener un objeto es emparentar el slot del objeto al hueso de la mano con un desplazamiento. Eso se hace en el cliente,
     sin IK.
4. **Cara viva sin morph targets.**
   - Parpadeo con intervalos semilla-aleatorios por personaje (deterministas) y doble parpadeo ocasional.
   - Mirada: la pupila pintada se desplaza hacia la cámara o un objetivo. Se añade un giro sutil del hueso `Head` después del
     mixer.
   - Pequeños asentimientos ligados a la energía de la voz.
   - Para personajes importados con blendshapes VRM o ARKit, se mapean los 9 visemas y el parpadeo a sus expresiones estándar.
5. **Manos en dos niveles.**
   - Si el personaje importado ya trae dedos (Mixamo o VRM), el retarget mapea las pistas de los dedos; hoy se descartan.
   - Para el rig propio: investigar un pulgar más un bloque de dedos detectados en la silueta de la mano, con poses de puño,
     mano abierta y señalar. Es experimental: solo se integra si pasa la prueba con mallas reales.

## Fases (un PR por fase)

### Fase 1 · Recorridos sin patinar
- **Qué:**
  - Un modo `path` en el worker, con varios puntos de paso, giros y una zancada adaptada a la velocidad.
  - Exportar el clip con el desplazamiento de raíz.
  - En Video 3D, un recorrido de varios tramos (Catmull-Rom) y reproducir el clip con desplazamiento en el slot.
- **Archivos:**
  - `app/services/humanoid_rig/motion.py`, `clip_recipes.py`, `clips.py`, `worker.py` y `routers/model3d_animate.py`;
  - `S/performance.ts`, `S/types.ts` y `S/gpu.ts`.
- **Pruebas:**
  - Durante cada apoyo, el pie se desplaza menos del 0,2 % de la pierna, en coordenadas del mundo.
  - La raíz sigue el recorrido con un error menor del 2 % de la pierna.
  - Una curva de 90° no produce patinaje.
  - La velocidad está dentro de los límites de zancada.
- **Quién: Claude.** Es IK y geometría del rig que acabo de rehacer.

### Fase 2 · Secuencias y fundidos
- **Qué:**
  - El campo `clips[]` con fundidos.
  - Los pesos calculados de forma pura a partir del tiempo de escena.
  - La compatibilidad con `clip` único.
- **Pruebas:** el mismo `t` da la misma pose, se pinte en el orden que se pinte; un fundido de 0 s equivale a un corte; un
  documento con `clip` único da el mismo hash que hoy.
- **Quién: Claude** el esquema y el núcleo de pesos en `gpu.ts`; delegable la UI de la secuencia (`Scene3DAnimationControls.tsx`).

### Fase 3 · Objetos: sentarse, alcanzar y sostener
- **Qué:**
  - Objetivos de IK en coordenadas del mundo o de un objeto, en el worker: `sit` sobre un slot, `reach` a un punto y
    `look_at`.
  - Emparentar un objeto a la mano en el cliente.
- **Pruebas:**
  - La pelvis queda a ± 2 cm de la superficie del asiento, escalado a la altura del personaje.
  - La mano llega al punto con un error menor del 1 % del brazo.
  - Un objeto sostenido sigue a la mano sin retraso de un fotograma.
- **Quién: Claude** la IK del worker; delegable el emparentado en el cliente.

### Fase 4 · Cara: parpadeo, mirada y cabeza
- **Qué:**
  - Parpadeo con semilla por personaje.
  - Desplazamiento de la pupila hacia el objetivo y giro de cabeza aditivo con límites.
  - Asentimientos a partir de la energía del audio de voz.
  - El mapeo VRM y ARKit de los visemas.
- **Pruebas:** el mismo personaje y semilla dan el mismo parpadeo; no hay dos parpadeos a menos de 1,5 s; la mirada apunta
  al objetivo con un error menor de 5°; la cabeza no pasa de ± 25°.
- **Quién:** delegable, sobre `speech/eyes.ts` y `speech/runtime.ts`. Claude revisa.

### Fase 5 · Manos
- **Qué:**
  - (a) Retarget de dedos cuando el destino los tiene.
  - (b) Investigación del pulgar y el bloque de dedos en el rig propio, con un informe con capturas en 3 mallas reales antes
    de integrar.
- **Quién: Claude**, en los dos casos (contrato de huesos y detección).

## Decisiones del usuario

- Si los recorridos se hornean siempre en el servidor (más preciso) o se acepta la aproximación en el cliente para la
  vista previa.
- Si la investigación de dedos (fase 5b) merece la pena para mallas generadas, que suelen tener los dedos fundidos.
  **Decidido el 2026-10-03:** la mano queda entera; no habrá huesos de dedos ni bloque de dedos, porque las mallas
  generadas aún no tienen ese nivel. El informe está en `docs/development/HUMANOID_HANDS_RESEARCH.md` (PR #783).
- La prioridad entre las fases 3 (objetos) y 4 (cara). Se propone primero la 4: es más barata y se nota en todos los planos
  con diálogo.

## Riesgos

- **Recorridos muy cerrados o velocidades extremas.** Se limitan la curvatura y la velocidad, y se avisa en la validación
  ([6 Control de calidad](06-control-calidad.md)).
- **Coste de hornear en el servidor.** Hoy un rig con clips tarda alrededor de 1 s; un recorrido de 60 s a 30 fps son unos
  1800 fotogramas de IK. Hay que medirlo en la fase 1.
- **Compatibilidad.** Los documentos con `clip` y `motion` siguen funcionando igual (test de hash).

## Fuera de alcance

Motion matching, física de ropa y pelo, multitudes, y morph targets en mallas generadas.

## Dependencias

- La [3 Biblioteca CC0](03-biblioteca-cc0.md) aporta animaciones Quaternius para las secuencias.
- El [5 Sonido](05-sonido.md) usa los contactos de los pies de la fase 1.
- El [6 Control de calidad](06-control-calidad.md) usa el suelo y los contactos para detectar personajes flotando o que
  atraviesan el suelo.
