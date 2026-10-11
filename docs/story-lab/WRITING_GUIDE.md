# Ayuda para escribir

En Story Lab y Series Lab, despliega **Ayúdame a escribir** en el apartado que
quieras desarrollar. La ayuda comparte las fichas existentes. Un cambio en una
respuesta vinculada aparece también en el editor habitual.

## Recorrido

1. Escribe una respuesta, consulta el ejemplo orientativo o salta a otra pregunta.
2. Activa **Profundizar** para ver todas las preguntas del apartado.
3. Pide **Ejemplos para mi historia** para recibir alternativas para esa pregunta.
4. Usa **Proponer respuestas pendientes** para completar huecos, o
   **Desarrollar con mis respuestas** para ampliar el apartado.
5. Edita el borrador. Marca los cambios que quieres incorporar y pulsa
   **Aplicar lo seleccionado**. Los campos ya escritos empiezan desmarcados.
6. Usa **Revisar coherencia** para pedir observaciones concretas. Las observaciones
   son propuestas editoriales; no son una puntuación objetiva.

La ayuda cubre historia, personaje, mundo, relación, momento, serie, temporada,
episodio y escena. En Series, las temporadas aparecen en Configuración. Las
preguntas de escenas desarrollan su función, entrada, salida y acontecimientos;
los diálogos y los planos siguen en los editores y generadores del episodio.

Las preguntas no son obligatorias y no fuerzan una estructura de actos.
La interfaz y los ejemplos orientativos están en español e inglés. El LLM
escribe en el idioma del proyecto y usa su proveedor configurado, incluido
el perfil global cuando se hereda. La escritura manual no llama al LLM.

## Guardado y revisión

- Los campos existentes mantienen su ubicación original. Las decisiones extra,
  el borrador pendiente y el último cambio reversible se guardan en
  `project.writingGuide`, dentro de la biblioteca del workspace.
- Cerrar la ayuda o recargar conserva el borrador recibido y editado. Una petición
  todavía en curso se cancela al salir; se puede pedir de nuevo.
- El resultado no se aplica automáticamente, incluso con el flujo directo del
  proyecto. Hay que revisar o descartar el borrador antes de pedir otro.
- Si cambias un campo mientras el LLM genera, no puedes aplicar una sustitución
  basada en el valor anterior. Puedes desmarcar ese cambio y aplicar los demás.
- **Deshacer lo aplicado** restaura los campos del último cambio aceptado si
  no los has editado después. No restaura todo el proyecto.
- Los ejemplos y las observaciones no se convierten en decisiones hasta que
  tú los incorporas. Cambiar respuestas no lanza generación de medios.

Las decisiones extra aceptadas alimentan la generación habitual de Story Lab
y la preparación de Series. Los episodios nuevos congelan las decisiones
generales en su canon; las notas de temporada se leen en vivo, como su premisa
y su arco, y no reabren la aprobación del canon. Las notas de un episodio se
usan solo en ese episodio.
Los episodios anteriores a esta función no heredan decisiones nuevas a escondidas.
La importación Story → Series conserva las decisiones compatibles y descarta
los borradores pendientes.

## API y mantenimiento

`POST /api/v1/writing-guide/propose` funciona en los runtimes completo y core.
Devuelve una propuesta; no modifica bibliotecas. La interfaz aplica los campos
seleccionados mediante el guardado existente y sus controles de revisión.

```json
{
  "scope": "character",
  "action": "develop",
  "questionId": "desire",
  "language": "Español",
  "values": {
    "desire": "Recuperar su nave",
    "need": "Confiar en su tripulación",
    "flaw": "Confunde proteger con controlar"
  },
  "context": {"project": {"premise": "Una capitana pierde el mando"}},
  "writingProvider": "maestro"
}
```

Acciones: `examples`, `fill`, `develop`, `review`.
Los scopes, preguntas, campos y ejemplos viven en
[`app/shared/writing_guide.json`](../../app/shared/writing_guide.json), compartido
por el servidor y la UI. Los cambios de canon pasan por
[`bindings.ts`](../../ui/src/features/writing-guide/bindings.ts).

La respuesta contiene `suggestions` (campo, valor y motivo), `examples`,
`review` (campo, problema y alternativa), proveedor, modelo, duración y
`usage`. El consumo aparece como desconocido cuando el proveedor no lo comunica.
No se estima a partir del número de caracteres. No se guardan claves API en
la propuesta ni se envían medios o propuestas anteriores como contexto.
Los errores incluyen un código estable en `detail.code`. La interfaz traduce
ese código al idioma de la UI, independiente del idioma del proyecto.

Cada acción solicita una respuesta estructurada, con un máximo de 2400 tokens
de salida. Admite hasta 6000 caracteres por respuesta y 24000 de contexto.
La validación rechaza campos desconocidos y respuestas malformadas. No hace
una segunda generación para reparar JSON; el proveedor conserva sus reintentos
de transporte existentes.

## Validación

- `tests/test_writing_guide.py`: contrato HTTP, proveedor, datos inválidos,
  persistencia, importación, decisiones aceptadas y canon congelado.
- `ui/tests/writingGuide.test.tsx`: edición, propuestas tardías, aplicación
  parcial, deshacer, identidad estable y reapertura.
- `ui/e2e/specs/writing-guide.spec.ts`: recorrido de Story y Series con API
  simulada, guardado y pantalla móvil.

Estas pruebas usan respuestas simuladas. No demuestran la calidad literaria
de un modelo concreto y no consumen tokens de proveedores ni generan medios.
