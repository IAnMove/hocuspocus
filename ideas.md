# Ideas frikis: por qué Vader se pasó al Lado Oscuro

Las tres que se están generando ahora:

1. **Obi-Wan desplegó el viernes un kernel lleno de errores y lo dejó solo.**
2. **Le negaron el merge a `main` / Palpatine le da root.**
3. **“En mi máquina funciona.”**

El resto, para más tarde:

## Repo y git

- **`git push --force` de Obi-Wan.** Mustafar es el repo en llamas. Anakin tenía su rama. Obi-Wan reescribe `main`. “Yo he sido tu hermano. Yo he reescrito tu historial.”
- **Code review eterno.** Mace Windu deja 47 nits. “Aprobaré el PR cuando seas más maduro.” Palpatine hace Approve sin leer.
- **Los clones son un fork bomb.** La Guerra de los Clones como `while true; do clone; done`.
- **SVN en el Templo.** Anakin descubre que los Jedi aún usan Subversion. Palpatine le enseña git. Tarde.

## Datos, YAML, arena

- **YAML / la arena.** Odia la arena porque se mete en todos sitios, como la indentación. Un espacio de más y el Consejo es `null`.
- **Excel convirtió los midiclorianos en fechas.** `19966` → 1 de enero. Palpatine “arregla” el censo a mano.
- **`null` de Padmé.** Intentó salvarla con un `UPDATE` sin transacción. Quedó `undefined`. El Lado Oscuro promete un backup que no existe.
- **`any` de TypeScript.** La arena es untyped. Se cuela en toda la codebase.

## Infra y ops

- **Siempre es DNS.** La Fuerza es un name server. Los Jedi no flushan. Los Sith tienen TTL a 1 segundo y root hints.
- **`chmod 777` en el Templo.** “Para que compile.” El Imperio es un umask.
- **Hotfix en prod, sin ticket.** Palpatine: “es un cambio pequeño.” No hay rollback. La galaxia es el postmortem. (Cercana a la del viernes; se puede mezclar.)
- **Kubernetes de 400 líneas para un hello world.** El Consejo llama a eso “el Código.”
- **Bluetooth / impresora del Senado.** Nadie lo admite, pero eso también corrompe a un Chosen One.

## Bugs clásicos

- **Heisenbug.** Solo falla en Mustafar. En Coruscant, verde.
- **Off-by-one.** El Consejo de 12. Anakin es el 13. Le falta un índice.
- **0.1 + 0.2 !== 0.3.** La Fuerza no es IEEE-754. Anakin insiste en que sí.
- **Race condition con su propio clon.** Merge conflict consigo mismo.
- **Recursión sin caso base.** El odio llama al odio llama al odio.

## Oficina

- **Jira sin descripción.** Ticket: “arreglar la galaxia.” Story points: 3. Real: 19 años.
- **“Lo metemos en el backlog.”** Palpatine lo dice mil años.
- **El product owner quiere blockchain.** Palpatine otra vez.
- **Outlook.** No hace falta explicar más.
- **La hoja de cálculo como base de datos del Ejército clon.**

## Una frase para un estribillo futuro

> El Lado Oscuro no es odio.  
> Es producción sin staging,  
> un force-push un viernes,  
> y un “en mi máquina funciona”.
