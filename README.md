# Comprobaciones de las webs de clase

Repositorio privado. Vigila las tres webs de clase del I.E.S. Trinidad Arroyo sin meter nada en ellas:
[automatismos](https://bernardotorio.github.io/automatismos/), [domotica](https://bernardotorio.github.io/domotica/) y
[maquinas](https://bernardotorio.github.io/maquinas/).

## Qué hace cada noche

A las 4:23 UTC (5:23 en invierno, 6:23 en verano), `.github/workflows/comprobar.yml`:

1. Trae las tres webs tal como están en `main`.
2. Abre **todas las páginas** con Chrome en cuatro variantes: escritorio y móvil de 400 px, en claro y en oscuro.
3. Busca **errores**: fallos de JavaScript, enlaces rotos (también los que la portada crea con JavaScript), páginas que
   se salen por la derecha en el móvil, la tira «‹ anterior · k de N · siguiente ›» mal, una página que estaba y ya no
   está, o una página que no responde en la web publicada.
4. Compara cada captura con la de la **última comprobación** y apunta las páginas que se ven distintas.
5. Si hay errores o páginas que han cambiado, **abre una incidencia** aquí (GitHub manda el correo) con la lista y una
   imagen «antes | después | diferencia» de cada página. La incidencia del día anterior se cierra sola.
6. Las capturas de hoy quedan como referencia para mañana: no hay nada que mantener.

Si ese día se ha cambiado una página a propósito, saldrá en la lista: lo que hay que mirar es que **no haya otras**.

## Dónde está cada cosa

| | |
|---|---|
| `comprobar_web.py` | El guion que comprueba una web. Es el mismo que usa Claude antes de publicar (proyecto «Materiales para instituto», `claude/herramientas/comprobar_web.py`): si se cambia en un sitio, se copia al otro. |
| `noche.py` | Lo pasa por las tres webs y escribe la incidencia. |
| `informes/ultima.md` | Resumen de la última noche. `informes/<web>.md`, el informe completo de cada web (con los avisos). |
| `cambios/<fecha>/` | Las imágenes de las páginas que cambiaron (se borran a los 14 días). |
| Capturas de referencia | No están en el repositorio: van en la caché de GitHub Actions. Si se pierde, esa noche no compara y empieza de nuevo. |

## A mano

- **Lanzarla ahora**: pestaña *Actions* → «Comprobar las webs de clase» → *Run workflow*.
- **Después de un cambio grande** (por ejemplo, cambiar la portada de las tres webs): *Run workflow* marcando
  «Solo guardar las capturas de hoy como referencia», para que no avise de todo.
- **Pararla**: *Actions* → «Comprobar las webs de clase» → «…» → *Disable workflow*.
- En el ordenador: `python3 comprobar_web.py C:\dev\domotica --antes-git origin/main` (necesita `pip install playwright pillow numpy`
  y `playwright install chromium`).

Los avisos (normas de las webs que no se cumplen, como una página sin la miga a la portada) no abren incidencia.
