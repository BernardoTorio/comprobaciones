#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
noche.py — La comprobación de cada noche de las tres webs de clase (lo lanza .github/workflows/comprobar.yml).

Pasa comprobar_web.py por automatismos, domotica y maquinas (clonadas en --webs), compara sus capturas con las
de la última vez (--refs, que viene de la caché de GitHub Actions) y deja:
  · informes/<web>.md y informes/ultima.md   (en este repositorio)
  · cambios/<fecha>/…png                     («antes | después | diferencia» de las páginas que han cambiado)
  · <salida>/aviso.md y <salida>/titulo.txt  (el texto de la incidencia, si hay algo que contar)
Escribe en GITHUB_OUTPUT: novedades=true|false y fallo=true|false.
"""
import argparse
import datetime
import json
import os
import shutil
import subprocess
import sys

WEBS = ['automatismos', 'domotica', 'maquinas']
PUBLICADA = 'https://bernardotorio.github.io/%s/'
MAX_LINEAS = 40
MAX_IMAGENES = 12
DIAS_CAMBIOS = 14


def pct(f):
    return ('%.1f' % (100 * f)).replace('.', ',') if f >= 0.001 else 'menos del 0,1'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--webs', required=True)
    ap.add_argument('--refs', required=True)
    ap.add_argument('--salida', required=True)
    ap.add_argument('--fuentes')
    ap.add_argument('--repo', default=os.path.dirname(os.path.abspath(__file__)))
    ap.add_argument('--url-repo', default='https://github.com/BernardoTorio/comprobaciones')
    ap.add_argument('--url-run', default='')
    ap.add_argument('--sin-publicada', action='store_true')
    a = ap.parse_args()
    hoy = datetime.datetime.now(datetime.timezone.utc).astimezone(datetime.timezone(datetime.timedelta(hours=1)))
    fecha, fecha_txt = hoy.strftime('%Y-%m-%d'), hoy.strftime('%d/%m/%Y')
    os.makedirs(a.salida, exist_ok=True)
    guion = os.path.join(a.repo, 'comprobar_web.py')

    procs = {}
    for w in WEBS:
        cmd = [sys.executable, guion, os.path.join(a.webs, w), '--salida', os.path.join(a.salida, w),
               '--referencia', os.path.join(a.refs, w), '--actualizar-referencia']
        if a.fuentes:
            cmd += ['--fuentes', a.fuentes]
        if not a.sin_publicada:
            cmd += ['--publicada', PUBLICADA % w]
        procs[w] = subprocess.Popen(cmd, stdout=open(os.path.join(a.salida, w + '.log'), 'w'), stderr=subprocess.STDOUT)
    fallo = []
    for w, p in procs.items():
        if p.wait() not in (0, 1):
            fallo.append(w)
            print('::error::La comprobación de %s ha fallado:' % w)
            print(open(os.path.join(a.salida, w + '.log')).read()[-3000:])

    dir_inf = os.path.join(a.repo, 'informes')
    dir_cam = os.path.join(a.repo, 'cambios', fecha)
    os.makedirs(dir_inf, exist_ok=True)
    shutil.rmtree(dir_cam, ignore_errors=True)
    cuerpo, resumen, tot_err, tot_cam, tot_pag, n_img = [], [], 0, 0, 0, 0
    for w in WEBS:
        fj = os.path.join(a.salida, w, 'informe.json')
        if w in fallo or not os.path.isfile(fj):
            resumen.append('| %s | no se ha podido comprobar | | |' % w)
            continue
        d = json.load(open(fj, encoding='utf-8'))
        shutil.copy(os.path.join(a.salida, w, 'informe.md'), os.path.join(dir_inf, w + '.md'))
        errores = list(d['generales']['errores'])
        vistos = set()
        for r in d['detalle']:
            for m in r['errores']:
                if (r['pagina'], m) not in vistos:
                    vistos.add((r['pagina'], m))
                    errores.append('`%s`: %s' % (r['pagina'], m))
        por = {}
        for c in d['cambios']:
            por.setdefault(c['pagina'], []).append(c)
        tot_err += len(errores)
        tot_cam += len(por)
        tot_pag += len(d['paginas'])
        resumen.append('| %s | %d | %d | %d de %d |' % (w, len(errores), d['avisos'], len(por), len(d['paginas'])))
        if not errores and not por:
            continue
        cuerpo += ['', '## %s' % w, '']
        if errores:
            cuerpo += ['**Errores**', ''] + ['- ' + e for e in errores[:MAX_LINEAS]]
            if len(errores) > MAX_LINEAS:
                cuerpo.append('- … y %d más (en `informes/%s.md`)' % (len(errores) - MAX_LINEAS, w))
            cuerpo.append('')
        if por:
            cuerpo += ['**Páginas que se ven distintas que la última vez**', '']
            for i, p in enumerate(sorted(por)):
                cs = por[p]
                if i >= MAX_LINEAS:
                    cuerpo.append('- … y %d más (en `informes/%s.md`)' % (len(por) - MAX_LINEAS, w))
                    break
                if cs[0]['tipo'] == 'nueva':
                    cuerpo.append('- `%s`: página nueva' % p)
                    continue
                cuerpo.append('- `%s`: %s' % (p, ', '.join('%s (%s %%)' % (c['variante'], pct(c['frac'])) for c in cs)))
                img = cs[0].get('imagen')
                if img and n_img < MAX_IMAGENES and os.path.isfile(os.path.join(a.salida, w, img)):
                    os.makedirs(dir_cam, exist_ok=True)
                    nombre = '%s__%s' % (w, os.path.basename(img))
                    shutil.copy(os.path.join(a.salida, w, img), os.path.join(dir_cam, nombre))
                    cuerpo.append('  ![%s](%s/blob/main/cambios/%s/%s?raw=true)' % (p, a.url_repo, fecha, nombre))
                    n_img += 1

    # limpiar las imágenes de hace más de DIAS_CAMBIOS días
    raiz = os.path.join(a.repo, 'cambios')
    if os.path.isdir(raiz):
        limite = (hoy - datetime.timedelta(days=DIAS_CAMBIOS)).strftime('%Y-%m-%d')
        for dname in os.listdir(raiz):
            if dname < limite and os.path.isdir(os.path.join(raiz, dname)):
                shutil.rmtree(os.path.join(raiz, dname), ignore_errors=True)

    tabla = ['| Web | Errores | Avisos | Páginas que han cambiado |', '|---|---|---|---|'] + resumen
    with open(os.path.join(dir_inf, 'ultima.md'), 'w', encoding='utf-8') as f:
        f.write('# Última comprobación: %s\n\n%s\n\n%s\n' % (hoy.strftime('%d/%m/%Y %H:%M'), '\n'.join(tabla),
                '[Ver la ejecución](%s)' % a.url_run if a.url_run else ''))
    partes = []
    if tot_err:
        partes.append('%d error%s' % (tot_err, '' if tot_err == 1 else 'es'))
    if tot_cam:
        partes.append('%d página%s' % (tot_cam, ' ha cambiado' if tot_cam == 1 else 's han cambiado'))
    if fallo:
        partes.append('no se ha podido comprobar ' + ', '.join(fallo))
    novedades = bool(partes)
    intro = ['Comprobación de las webs de clase del %s.%s' % (fecha_txt, (' [Ver la ejecución](%s) (ahí están las imágenes y los informes completos).' % a.url_run) if a.url_run else ''), '']
    if tot_pag and tot_cam > 0.5 * tot_pag:
        intro += ['> Han cambiado casi todas las páginas a la vez. Lo más probable es que haya cambiado el navegador o las letras '
                  'del servidor de GitHub, no las webs. Si no has tocado nada, se puede cerrar sin más.', '']
    with open(os.path.join(a.salida, 'aviso.md'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(intro + tabla + cuerpo + ['', '---', 'Los avisos (normas de las webs que no se cumplen) no abren incidencia: están en `informes/`. '
                                                     'Las capturas se comparan con las de la última comprobación; las de hoy quedan como referencia.']) + '\n')
    with open(os.path.join(a.salida, 'titulo.txt'), 'w', encoding='utf-8') as f:
        f.write('Webs de clase · %s: %s' % (hoy.strftime('%d/%m'), ', '.join(partes) if partes else 'sin novedades'))
    out = os.environ.get('GITHUB_OUTPUT')
    if out:
        with open(out, 'a') as f:
            f.write('novedades=%s\nfallo=%s\n' % ('true' if novedades else 'false', 'true' if fallo else 'false'))
    res = os.environ.get('GITHUB_STEP_SUMMARY')
    if res:
        with open(res, 'a', encoding='utf-8') as f:
            f.write(open(os.path.join(a.salida, 'aviso.md'), encoding='utf-8').read())
    print(open(os.path.join(a.salida, 'titulo.txt'), encoding='utf-8').read())
    print('\n'.join(tabla))


if __name__ == '__main__':
    main()
