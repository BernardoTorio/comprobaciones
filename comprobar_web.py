#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
comprobar_web.py — Comprueba una web de clase (automatismos, domotica, maquinas) antes de publicar.

Abre con Chrome (Playwright) todas las páginas .html de la raíz de la carpeta, en cuatro variantes
(escritorio y móvil de 400 px, en claro y en oscuro), y mira lo que dicen los CLAUDE.md de las webs:

  ERRORES (hay que arreglarlos)
    · errores de JavaScript o de consola
    · enlaces a archivos que no existen (también los que la portada crea con JavaScript)
    · archivos propios que no cargan
    · la página se sale por la derecha (hay que deslizar de lado toda la página)
    · la tira «‹ anterior · k de N · siguiente ›»: número de pasos, paso actual, flechas, botón «Siguiente»
      y que todas las páginas del grupo lleven la misma tira
    · un .html o un PDF que estaba antes y ya no está (los QR impresos apuntan a su nombre)
  AVISOS (normas de las webs que no se cumplen)
    · falta el enlace para volver a index.html, la miga a la portada o el botón de modo claro/oscuro
    · Esc no vuelve al índice · el modo oscuro o el claro no se aplica · pide algo de fuera que no es Google Fonts
    · un enlace a index.html#pestaña que no existe
  CAMBIOS DE ASPECTO (con --antes, --antes-git o --referencia)
    · qué páginas se ven distintas que antes, con una imagen «antes | después | diferencia» de cada una

Uso:
  python3 comprobar_web.py CARPETA [--salida DIR] [--paginas a.html b.html] [--variantes movil-claro ...]
                           [--antes CARPETA_ANTERIOR | --antes-git origin/main | --referencia DIR [--actualizar-referencia]]
                           [--fuentes DIR] [--publicada URL] [--sin-capturas] [--estricto]

Deja en DIR (por defecto, ./comprobacion_<web>): informe.md, informe.json, capturas/<variante>/<página>.png,
hojas/<variante>_NN.png (hojas de contacto para mirarlas de un vistazo) y cambios/ (si se compara).
Sale con código 1 si hay errores (con --estricto, también si hay avisos).

Necesita: pip install playwright pillow numpy   (y Chrome, o «playwright install chromium»).
La letra Atkinson Hyperlegible: con --fuentes DIR se sirve desde los .woff2 de esa carpeta
(npm i @fontsource/atkinson-hyperlegible → node_modules/@fontsource/atkinson-hyperlegible/files);
sin ella se intenta Google Fonts y, si no hay red, se usa la letra de respaldo (se avisa en el informe).
"""
import argparse
import datetime
import functools
import http.server
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.parse
import urllib.request

VARIANTES = [
    # nombre, ancho, alto, tema, móvil
    ('escritorio-claro', 1280, 800, 'light', False),
    ('movil-claro', 400, 800, 'light', True),
    ('escritorio-oscuro', 1280, 800, 'dark', False),
    ('movil-oscuro', 400, 800, 'dark', True),
]
ALTO_MAX = 6000          # las capturas de página entera se recortan a esta altura
UMBRAL = 0.0002          # fracción de píxeles distintos a partir de la cual «ha cambiado»
MIN_PIXELES = 60         # y, además, al menos estos píxeles
HOSTS_FUENTES = ('fonts.googleapis.com', 'fonts.gstatic.com')
CARPETAS_PDF = ('temas', 'practicas', 'ejercicios')

RANGO_LATIN = ('U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,'
               'U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD')
RANGO_LATIN_EXT = ('U+0100-02BA,U+02BD-02C5,U+02C7-02CC,U+02CE-02D7,U+02DD-02FF,U+0304,U+0308,U+0329,'
                   'U+1D00-1DBF,U+1E00-1E9F,U+1EF2-1EFF,U+2020,U+20A0-20AB,U+20AD-20C0,U+2113,U+2C60-2C7F,U+A720-A7FF')

SONDA = r"""
(ANCHO) => {
  const W = ANCHO, de = document.documentElement, o = {};
  const desc = el => { let s = el.tagName.toLowerCase(); if (el.id) s += '#' + el.id;
    const c = (el.getAttribute('class') || '').trim().split(/\s+/).filter(Boolean).slice(0, 2).join('.'); if (c) s += '.' + c; return s; };
  o.titulo = document.title || ''; o.lang = de.getAttribute('lang') || '';
  o.ancho = W; o.scrollW = Math.max(de.scrollWidth, document.body ? document.body.scrollWidth : 0);
  o.fuera = [];
  if (o.scrollW > W + 2 && document.body) {
    for (const el of document.body.querySelectorAll('*')) {
      const r = el.getBoundingClientRect(); if (!r.width || !r.height || r.right <= W + 2) continue;
      const cs0 = getComputedStyle(el); if (cs0.position === 'fixed' || cs0.visibility === 'hidden') continue;
      let p = el.parentElement, dentro = false;
      while (p && p !== document.body) { const cs = getComputedStyle(p);
        if (/(auto|scroll|hidden|clip)/.test(cs.overflowX)) { dentro = true; break; } p = p.parentElement; }
      if (!dentro) { o.fuera.push(desc(el) + ' (+' + Math.round(r.right - W) + ' px)'); if (o.fuera.length >= 3) break; }
    }
  }
  o.enlaces = [...document.querySelectorAll('a[href]')].map(a => ({ h: a.getAttribute('href'), abs: a.href,
    falta: a.classList.contains('missing'), txt: (a.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 40) }));
  const nav = document.querySelector('.t6nav, .tira, .tnav');
  if (nav) { const pasos = [...nav.querySelectorAll('.steps a')];
    o.tira = { donde: ((nav.querySelector('.where') || {}).textContent || '').trim(),
      pasos: pasos.map(a => a.getAttribute('href')),
      cur: pasos.findIndex(a => a.classList.contains('cur') || a.getAttribute('aria-current') === 'page'),
      flechas: [...nav.querySelectorAll('a.arr, a.tarr')].map(a => a.getAttribute('href')) }; }
  const nb = document.querySelector('a.nextbig'); o.nextbig = nb ? nb.getAttribute('href') : null;
  o.volver = !!document.querySelector('a[href^="index.html"]');
  o.miga = !!document.querySelector('a[href="index.html"]');
  o.botonTema = !!document.querySelector('#themeBtn, .themebtn, #tema, #btnTema, button[aria-label*="modo" i], button[title*="modo" i], button[aria-label*="tema" i], button[title*="tema" i]');
  const lum = c => { const m = /rgba?\(([^)]+)\)/.exec(c || ''); if (!m) return null; const v = m[1].split(',').map(parseFloat);
    if (v.length > 3 && v[3] === 0) return null; return (0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2]) / 255; };
  let l = document.body ? lum(getComputedStyle(document.body).backgroundColor) : null;
  if (l === null) l = lum(getComputedStyle(de).backgroundColor);
  o.fondo = l; o.secs = [...document.querySelectorAll('[id^="sec-"]')].map(e => e.id.slice(4));
  o.letra = (document.fonts && document.fonts.check) ? document.fonts.check('16px "Atkinson Hyperlegible"') : null;
  return o;
}
"""

INICIO = """(() => { try { localStorage.setItem('tema', '%(t)s'); localStorage.setItem('maq-tema', '%(t)s'); } catch (e) {}
  let s = 20261123; Math.random = () => { s = (Math.imul(s, 1664525) + 1013904223) >>> 0; return s / 4294967296; }; })();"""


class Silencioso(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def servir(carpeta):
    h = functools.partial(Silencioso, directory=carpeta)
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), h)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, 'http://127.0.0.1:%d' % srv.server_address[1]


class Fuentes:
    """Sirve Atkinson Hyperlegible desde una carpeta con los .woff2 de @fontsource (sin red y siempre igual)."""

    def __init__(self, carpeta):
        self.archivos = {}
        self.css = ''
        if not carpeta:
            return
        if not os.path.isdir(carpeta):
            sys.exit('No existe la carpeta de --fuentes: %s (lleva los .woff2 de @fontsource/atkinson-hyperlegible)' % carpeta)
        for peso in (400, 700):
            for sub, rango in (('latin-ext', RANGO_LATIN_EXT), ('latin', RANGO_LATIN)):
                n = 'atkinson-hyperlegible-%s-%d-normal.woff2' % (sub, peso)
                p = os.path.join(carpeta, n)
                if os.path.isfile(p):
                    self.archivos[n] = p
                    self.css += ("@font-face{font-family:'Atkinson Hyperlegible';font-style:normal;font-weight:%d;"
                                 "font-display:swap;src:url(https://fonts.gstatic.com/local/%s) format('woff2');"
                                 "unicode-range:%s}\n" % (peso, n, rango))
        if not self.css:
            sys.exit('En %s no están los .woff2 de Atkinson Hyperlegible (atkinson-hyperlegible-latin-400-normal.woff2…)' % carpeta)

    def __bool__(self):
        return bool(self.css)


def lista_paginas(carpeta):
    return sorted(f for f in os.listdir(carpeta) if f.lower().endswith('.html') and os.path.isfile(os.path.join(carpeta, f)))


def lista_pdf(carpeta):
    out = []
    for c in CARPETAS_PDF:
        d = os.path.join(carpeta, c)
        if os.path.isdir(d):
            out += sorted(c + '/' + f for f in os.listdir(d) if f.lower().endswith('.pdf'))
    return out


class Web:
    """Una carpeta servida en local y abierta con el navegador."""

    def __init__(self, navegador, carpeta, fuentes, red_fuentes):
        self.nav = navegador
        self.carpeta = os.path.abspath(carpeta)
        self.srv, self.base = servir(self.carpeta)
        self.fuentes = fuentes
        self.red_fuentes = red_fuentes

    def cerrar(self):
        self.srv.shutdown()

    def abrir(self, pagina, variante, esc=False, captura=None, doble=False):
        nombre, ancho, alto, tema, movil = variante
        r = {'pagina': pagina, 'variante': nombre, 'errores': [], 'avisos': [], 'info': [], 'sonda': None,
             'redirige': None, 'inestable': 0.0}
        ctx = self.nav.new_context(viewport={'width': ancho, 'height': alto}, color_scheme=tema, reduced_motion='reduce',
                                   is_mobile=movil, has_touch=movil, device_scale_factor=1, locale='es-ES',
                                   timezone_id='Europe/Madrid')
        ctx.add_init_script(INICIO % {'t': tema})
        externos, base = set(), self.base

        def ruta(route):
            u = route.request.url
            if u.startswith(base) or u.startswith('data:') or u.startswith('blob:'):
                return route.continue_()
            host = urllib.parse.urlparse(u).hostname or ''
            if host in HOSTS_FUENTES:
                if self.fuentes:
                    if host == 'fonts.googleapis.com':
                        return route.fulfill(status=200, content_type='text/css', body=self.fuentes.css,
                                             headers={'access-control-allow-origin': '*'})
                    f = self.fuentes.archivos.get(u.rsplit('/', 1)[-1])
                    if f:
                        return route.fulfill(status=200, content_type='font/woff2', path=f,
                                             headers={'access-control-allow-origin': '*'})
                    return route.abort()
                return route.continue_() if self.red_fuentes else route.abort()
            externos.add(host or u[:40])
            return route.abort()

        ctx.route('**/*', ruta)
        page = ctx.new_page()
        page.on('pageerror', lambda e: r['errores'].append('error de JavaScript: ' + str(e).split('\n')[0][:220]))

        def consola(m):
            if m.type == 'error' and 'Failed to load resource' not in m.text:
                r['errores'].append('error en la consola: ' + m.text.split('\n')[0][:220])
        page.on('console', consola)

        def respuesta(resp):
            if resp.status >= 400 and resp.url.startswith(base):
                p = urllib.parse.unquote(urllib.parse.urlparse(resp.url).path).lstrip('/')
                if resp.request.method == 'HEAD' and p.lower().endswith('.pdf'):
                    r['info'].append('PDF «próximamente» (todavía no está): ' + p)
                elif p != 'favicon.ico':
                    r['errores'].append('no carga un archivo propio (%d): %s' % (resp.status, p))
        page.on('response', respuesta)
        page.on('dialog', lambda d: d.dismiss())
        try:
            page.goto(base + '/' + urllib.parse.quote(pagina), wait_until='load', timeout=30000)
            try:
                page.evaluate('() => document.fonts ? document.fonts.ready.then(() => true) : true')
            except Exception:
                pass
            page.wait_for_timeout(450)
            fin = urllib.parse.unquote(urllib.parse.urlparse(page.url).path).lstrip('/')
            if fin != pagina:
                r['redirige'] = fin + (('#' + urllib.parse.urlparse(page.url).fragment) if urllib.parse.urlparse(page.url).fragment else '')
            else:
                r['sonda'] = page.evaluate(SONDA, ancho)
                if captura:
                    os.makedirs(os.path.dirname(captura), exist_ok=True)
                    page.screenshot(path=captura, full_page=True, animations='disabled', caret='hide')
                    if doble:
                        page.wait_for_timeout(350)
                        otra = captura + '.2.png'
                        page.screenshot(path=otra, full_page=True, animations='disabled', caret='hide')
                        r['inestable'] = diferencia(captura, otra)[0]
                        os.remove(otra)
                if esc and pagina != 'index.html':
                    try:
                        page.keyboard.press('Escape')
                        page.wait_for_url(re.compile(r'/index\.html'), timeout=1500)
                    except Exception:
                        r['avisos'].append('la tecla Esc no vuelve al índice')
        except Exception as e:
            r['errores'].append('no se ha podido abrir: ' + str(e).split('\n')[0][:200])
        for h in sorted(externos):
            r['avisos'].append('pide algo de fuera que no es Google Fonts: ' + h)
        ctx.close()
        return r


def pct(f):
    return ('%.1f' % (100 * f)).replace('.', ',') if f >= 0.001 else 'menos del 0,1'


def recortar(ruta):
    from PIL import Image
    im = Image.open(ruta)
    if im.height > ALTO_MAX:
        im.crop((0, 0, im.width, ALTO_MAX)).save(ruta)


def diferencia(a, b, salida=None):
    """Fracción de píxeles distintos entre dos capturas y, si se pide, imagen «antes | después | diferencia»."""
    import numpy as np
    from PIL import Image
    A, B = Image.open(a).convert('RGB'), Image.open(b).convert('RGB')
    w, h = max(A.width, B.width), min(max(A.height, B.height), ALTO_MAX)

    def lienzo(im):
        c = Image.new('RGB', (w, h), (255, 255, 255))
        c.paste(im.crop((0, 0, min(im.width, w), min(im.height, h))), (0, 0))
        return c
    A2, B2 = lienzo(A), lienzo(B)
    a16, b16 = np.asarray(A2, dtype=np.int16), np.asarray(B2, dtype=np.int16)
    d = np.abs(a16 - b16).max(axis=2) > 24
    if d.any():
        # tolerancia de 1 px: un píxel solo cuenta si no se parece a ninguno de sus vecinos en la otra imagen
        # (el mismo texto dibujado medio píxel más allá no es un cambio)
        ys, xs = np.where(d.any(axis=1))[0], np.where(d.any(axis=0))[0]
        y0, y1, x0, x1 = max(int(ys[0]) - 1, 0), min(int(ys[-1]) + 2, h), max(int(xs[0]) - 1, 0), min(int(xs[-1]) + 2, w)

        def sin_vecino(p, q):
            m = np.ones(p.shape[:2], dtype=bool)
            qp = np.pad(q, ((1, 1), (1, 1), (0, 0)), mode='edge')
            for dy in (0, 1, 2):
                for dx in (0, 1, 2):
                    m &= np.abs(p - qp[dy:dy + p.shape[0], dx:dx + p.shape[1]]).max(axis=2) > 24
            return m
        pa, pb = a16[y0:y1, x0:x1], b16[y0:y1, x0:x1]
        d2 = np.zeros_like(d)
        d2[y0:y1, x0:x1] = sin_vecino(pa, pb) | sin_vecino(pb, pa)
        d = d2
    n = int(d.sum())
    frac = n / float(w * h)
    if salida and n:
        m = np.asarray(B2).copy()
        m[d] = (255, 0, 200)
        ys = np.where(d.any(axis=1))[0]
        y0, y1 = max(0, int(ys[0]) - 60), min(h, int(ys[-1]) + 60)
        if y1 - y0 < 400:
            y1 = min(h, y0 + 400)
        esc = min(1.0, 560.0 / w)
        trozos = [im.crop((0, y0, w, y1)).resize((int(w * esc), max(1, int((y1 - y0) * esc)))) for im in (A2, B2, Image.fromarray(m))]
        if trozos[0].height > 1800:
            trozos = [t.crop((0, 0, t.width, 1800)) for t in trozos]
        hoja = Image.new('RGB', (sum(t.width for t in trozos) + 20, trozos[0].height + 26), (245, 245, 245))
        from PIL import ImageDraw
        dr, x = ImageDraw.Draw(hoja), 0
        for t, txt in zip(trozos, ('ANTES', 'DESPUES', 'DIFERENCIA (en rosa)')):
            dr.text((x + 4, 6), txt, fill=(0, 0, 0))
            hoja.paste(t, (x, 26))
            x += t.width + 10
        os.makedirs(os.path.dirname(salida), exist_ok=True)
        hoja.save(salida)
    return frac, n


def hojas_contacto(dir_capturas, dir_hojas, variante, paginas):
    """Hojas con miniaturas, para mirar muchas páginas de un vistazo."""
    from PIL import Image, ImageDraw
    nombre, ancho, alto, tema, movil = variante
    cols, filas = (6, 2) if movil else (4, 3)
    tw = 210 if movil else 320
    th = int(tw * (1500 if movil else 800) / ancho)
    hechas = []
    os.makedirs(dir_hojas, exist_ok=True)
    por = cols * filas
    for i in range(0, len(paginas), por):
        lote = paginas[i:i + por]
        hoja = Image.new('RGB', (cols * (tw + 10) + 10, filas * (th + 30) + 10), (120, 120, 120))
        dr = ImageDraw.Draw(hoja)
        for j, p in enumerate(lote):
            f = os.path.join(dir_capturas, nombre, p[:-5] + '.png')
            if not os.path.isfile(f):
                continue
            im = Image.open(f).convert('RGB')
            im = im.crop((0, 0, im.width, min(im.height, 1500 if movil else 800)))
            im = im.resize((tw, max(1, int(im.height * tw / im.width))))
            x, y = 10 + (j % cols) * (tw + 10), 10 + (j // cols) * (th + 30)
            dr.rectangle((x, y, x + tw, y + 18), fill=(255, 255, 255))
            dr.text((x + 3, y + 3), p[:-5][:34], fill=(0, 0, 0))
            hoja.paste(im, (x, y + 20))
        out = os.path.join(dir_hojas, '%s_%02d.png' % (nombre, i // por + 1))
        hoja.save(out)
        hechas.append(out)
    return hechas


def revisar_sonda(r, web, paginas_todas, pestanas):
    """Lo que se deduce de la sonda de una página en una variante."""
    s, pagina, nombre = r['sonda'], r['pagina'], r['variante']
    movil, oscuro = 'movil' in nombre, 'oscuro' in nombre
    if s['scrollW'] > s['ancho'] + 2:
        r['errores'].append('se sale por la derecha %d px (hay que deslizar toda la página de lado)%s'
                            % (s['scrollW'] - s['ancho'], ': ' + ', '.join(s['fuera']) if s['fuera'] else ''))
    vistos = set()
    for e in s['enlaces']:
        h = e['h'] or ''
        if not h or h.startswith(('#', 'mailto:', 'tel:', 'javascript:', 'data:', 'blob:')) or h in vistos:
            continue
        vistos.add(h)
        u = urllib.parse.urlparse(e['abs'])
        if not e['abs'].startswith(web.base):
            continue
        ruta = urllib.parse.unquote(u.path).lstrip('/') or 'index.html'
        if not os.path.exists(os.path.join(web.carpeta, ruta)):
            if e['falta']:
                continue        # la portada ya lo marca «próximamente»
            r['errores'].append('enlace roto: %s («%s»)' % (h, e['txt']))
        elif ruta == 'index.html' and u.fragment and pestanas and u.fragment not in pestanas:
            r['avisos'].append('enlace a una pestaña que no existe: %s' % h)
    if not s['titulo'].strip():
        r['avisos'].append('no tiene <title>')
    if s['fondo'] is not None:
        if oscuro and s['fondo'] > 0.5:
            r['avisos'].append('el modo oscuro no se aplica (fondo claro)')
        if not oscuro and s['fondo'] < 0.5:
            r['avisos'].append('el modo claro no se aplica (fondo oscuro)')
    if not s['botonTema']:
        r['avisos'].append('no tiene botón de modo claro/oscuro')
    if pagina != 'index.html':
        if not s['volver']:
            r['avisos'].append('no tiene enlace para volver a index.html')
        elif not s['miga']:
            r['avisos'].append('no tiene la miga que lleva a la portada (index.html)')
    t = s.get('tira')
    if t:
        n = len(t['pasos'])
        m = re.search(r'(\d+)\s+de\s+(\d+)', t['donde'])
        if t['cur'] < 0:
            r['errores'].append('tira: ningún paso está marcado como el actual')
        else:
            if t['pasos'][t['cur']] != pagina:
                r['errores'].append('tira: el paso marcado como actual es %s' % t['pasos'][t['cur']])
            if m and (int(m.group(1)) != t['cur'] + 1 or int(m.group(2)) != n):
                r['errores'].append('tira: dice «%s» y es el paso %d de %d' % (m.group(0), t['cur'] + 1, n))
            ant = t['pasos'][t['cur'] - 1] if t['cur'] > 0 else None
            sig = t['pasos'][t['cur'] + 1] if t['cur'] + 1 < n else None
            if ant and ant not in t['flechas']:
                r['errores'].append('tira: la flecha «anterior» no lleva a %s' % ant)
            if sig and sig not in t['flechas']:
                r['errores'].append('tira: la flecha «siguiente» no lleva a %s' % sig)
            if s['nextbig'] is None:
                r['avisos'].append('lleva tira pero no el botón grande «Siguiente»')
            elif sig and s['nextbig'].split('#')[0] != sig:
                r['errores'].append('el botón grande «Siguiente» lleva a %s y el paso siguiente es %s' % (s['nextbig'], sig))
            elif not sig and not s['nextbig'].startswith('index.html'):
                r['errores'].append('es la última del grupo y el botón grande no vuelve al índice (%s)' % s['nextbig'])


def main():
    ap = argparse.ArgumentParser(description='Comprueba una web de clase antes de publicar.')
    ap.add_argument('carpeta')
    ap.add_argument('--salida')
    ap.add_argument('--paginas', nargs='*')
    ap.add_argument('--variantes', nargs='*', choices=[v[0] for v in VARIANTES])
    ap.add_argument('--antes', help='carpeta con la versión anterior de la web')
    ap.add_argument('--antes-git', help='referencia de git con la versión anterior (p. ej. origin/main)')
    ap.add_argument('--referencia', help='carpeta con capturas de referencia guardadas')
    ap.add_argument('--actualizar-referencia', action='store_true', help='después de comparar, guarda las capturas nuevas como referencia')
    ap.add_argument('--fuentes', help='carpeta con los .woff2 de Atkinson Hyperlegible (@fontsource)')
    ap.add_argument('--publicada', help='dirección publicada (p. ej. https://bernardotorio.github.io/domotica/): comprueba que cada página responde')
    ap.add_argument('--sin-capturas', action='store_true')
    ap.add_argument('--estricto', action='store_true')
    a = ap.parse_args()

    carpeta = os.path.abspath(a.carpeta)
    if not os.path.isfile(os.path.join(carpeta, 'index.html')):
        sys.exit('En %s no hay index.html: no parece una web de clase' % carpeta)
    nombre_web = os.path.basename(carpeta.rstrip('/\\'))
    salida = os.path.abspath(a.salida or ('comprobacion_' + nombre_web))
    if os.path.commonpath([salida, carpeta]) == carpeta:
        sys.exit('La carpeta de --salida no puede estar dentro de la web (se publicaría): %s' % salida)
    for d in ('capturas', 'hojas', 'cambios'):
        shutil.rmtree(os.path.join(salida, d), ignore_errors=True)
    os.makedirs(salida, exist_ok=True)
    variantes = [v for v in VARIANTES if not a.variantes or v[0] in a.variantes]
    todas = lista_paginas(carpeta)
    paginas = [p for p in todas if not a.paginas or p in a.paginas]
    if a.paginas:
        for p in a.paginas:
            if p not in todas:
                sys.exit('No existe %s en %s' % (p, carpeta))
    comparar = bool(a.antes or a.antes_git or a.referencia)
    capturar = not a.sin_capturas or comparar

    tmp_antes = None
    carpeta_antes = os.path.abspath(a.antes) if a.antes else None
    if a.antes_git:
        tmp_antes = tempfile.mkdtemp(prefix='antes_')
        p1 = subprocess.Popen(['git', '-C', carpeta, 'archive', a.antes_git], stdout=subprocess.PIPE)
        p2 = subprocess.run(['tar', '-x', '-C', tmp_antes], stdin=p1.stdout)
        p1.wait()
        if p1.returncode or p2.returncode:
            sys.exit('No se ha podido sacar la versión %s con git archive' % a.antes_git)
        carpeta_antes = tmp_antes

    from playwright.sync_api import sync_playwright
    fuentes = Fuentes(a.fuentes)
    res, general_err, general_avi, general_info, cambios = [], [], [], [], []
    with sync_playwright() as pw:
        args = ['--no-sandbox', '--force-color-profile=srgb', '--font-render-hinting=none', '--disable-lcd-text',
                '--disable-font-subpixel-positioning', '--hide-scrollbars']
        try:
            nav = pw.chromium.launch(args=args)
        except Exception:
            nav = pw.chromium.launch(channel='chrome', args=args)
        red_fuentes = False
        if not fuentes:
            try:
                c = nav.new_context()
                pg = c.new_page()
                pg.goto('https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible:wght@400;700&display=swap', timeout=6000)
                red_fuentes = True
                c.close()
            except Exception:
                red_fuentes = False
            if not red_fuentes:
                general_info.append('No hay red para Google Fonts ni --fuentes: las páginas se han visto con la letra de respaldo, '
                                    'no con Atkinson Hyperlegible (los anchos pueden cambiar un poco).')
        web = Web(nav, carpeta, fuentes, red_fuentes)
        web_antes = Web(nav, carpeta_antes, fuentes, red_fuentes) if carpeta_antes else None

        # pestañas de la portada (para los enlaces index.html#pestaña)
        r0 = web.abrir('index.html', VARIANTES[0])
        pestanas = set((r0['sonda'] or {}).get('secs', []))
        enlazadas = set()
        if r0['sonda']:
            for e in r0['sonda']['enlaces']:
                if e['abs'].startswith(web.base):
                    enlazadas.add(urllib.parse.unquote(urllib.parse.urlparse(e['abs']).path).lstrip('/'))

        total = len(paginas) * len(variantes)
        hecho = 0
        for v in variantes:
            for p in paginas:
                cap = os.path.join(salida, 'capturas', v[0], p[:-5] + '.png') if capturar else None
                r = web.abrir(p, v, esc=(v[0] == variantes[0][0]), captura=cap, doble=comparar)
                if r['sonda']:
                    revisar_sonda(r, web, todas, pestanas)
                    if cap and os.path.isfile(cap):
                        recortar(cap)
                elif r['redirige']:
                    dest = r['redirige'].split('#')[0]
                    if os.path.exists(os.path.join(carpeta, dest)):
                        r['info'].append('redirige a ' + r['redirige'])
                    else:
                        r['errores'].append('redirige a %s, que no existe' % r['redirige'])
                res.append(r)
                hecho += 1
                if hecho % 20 == 0 or hecho == total:
                    print('  %d de %d' % (hecho, total), flush=True)

        # la tira, entre páginas del mismo grupo
        por_pag = {r['pagina']: r for r in res if r['variante'] == variantes[0][0] and r['sonda']}
        if not a.paginas:
            tiras = {p: tuple(r['sonda']['tira']['pasos']) for p, r in por_pag.items() if r['sonda'].get('tira')}
            padre = {p: p for p in tiras}

            def raiz(x):
                while padre[x] != x:
                    x = padre[x]
                return x
            for p, pasos in tiras.items():
                for q in pasos:
                    if q in tiras:
                        padre[raiz(q)] = raiz(p)
            grupos = {}
            for p in tiras:
                grupos.setdefault(raiz(p), []).append(p)
            for g in grupos.values():
                formas = {}
                for p in g:
                    formas.setdefault(tiras[p], []).append(p)
                if len(formas) > 1:
                    general_err.append('la tira no es igual en todo el grupo (hay que rehacerla en todas): '
                                       + ' · '.join('%s llevan %d pasos' % (', '.join('`%s`' % x for x in sorted(ps)), len(f)) if len(ps) > 1
                                                    else '`%s` lleva %d pasos' % (ps[0], len(f)) for f, ps in sorted(formas.items(), key=lambda kv: -len(kv[1]))))
                for p in g:
                    for q in tiras[p]:
                        if q in todas and q not in tiras and q in por_pag:
                            general_err.append('`%s` sale en la tira de `%s` pero no lleva tira' % (q, p))
            sueltas = [p for p in todas if p != 'index.html' and p not in enlazadas]
            if sueltas and r0['sonda']:
                general_info.append('Páginas sin enlace desde la portada (normal si están escondidas o solo redirigen): ' + ', '.join(sueltas))

        # ¿falta algo que antes estaba?
        if web_antes:
            for f in lista_paginas(carpeta_antes):
                if f not in todas:
                    general_err.append('`%s` estaba antes y ya no está: los QR impresos apuntan a ese nombre' % f)
            ahora_pdf = set(lista_pdf(carpeta))
            for f in lista_pdf(carpeta_antes):
                if f not in ahora_pdf:
                    general_err.append('el PDF `%s` estaba antes y ya no está' % f)

        # comparación de aspecto
        if comparar:
            ref_dir = os.path.abspath(a.referencia) if a.referencia else os.path.join(salida, '_antes')
            if web_antes:
                shutil.rmtree(ref_dir, ignore_errors=True)
                antes_pags = set(lista_paginas(carpeta_antes))
                print('  capturando la versión anterior…', flush=True)
                for v in variantes:
                    for p in paginas:
                        if p in antes_pags:
                            cap = os.path.join(ref_dir, v[0], p[:-5] + '.png')
                            ra = web_antes.abrir(p, v, captura=cap)
                            if os.path.isfile(cap):
                                recortar(cap)
            inest = {(r['pagina'], r['variante']): r['inestable'] for r in res}
            primera = bool(a.referencia) and not os.path.isdir(ref_dir)
            if primera:
                general_info.append('No había capturas de referencia: se guardan las de hoy y no se compara nada.'
                                    if a.actualizar_referencia else 'No hay capturas de referencia en %s: no se compara nada.' % ref_dir)
            for v in variantes:
                for p in paginas:
                    if primera:
                        break
                    nueva = os.path.join(salida, 'capturas', v[0], p[:-5] + '.png')
                    vieja = os.path.join(ref_dir, v[0], p[:-5] + '.png')
                    if not os.path.isfile(nueva):
                        continue
                    if not os.path.isfile(vieja):
                        cambios.append({'pagina': p, 'variante': v[0], 'tipo': 'nueva', 'frac': 1.0})
                        continue
                    ruido = inest.get((p, v[0]), 0.0)
                    img = os.path.join(salida, 'cambios', '%s__%s.png' % (p[:-5], v[0]))
                    frac, n = diferencia(vieja, nueva, img)
                    if frac > UMBRAL + 4 * ruido and n >= MIN_PIXELES:
                        otra = nueva + '.otra.png'
                        web.abrir(p, v, captura=otra)
                        if os.path.isfile(otra):
                            recortar(otra)
                            f2, n2 = diferencia(vieja, otra)
                            os.remove(otra)
                            if not (f2 > UMBRAL + 4 * ruido and n2 >= MIN_PIXELES):
                                frac = 0.0
                    if frac > UMBRAL + 4 * ruido and n >= MIN_PIXELES:
                        cambios.append({'pagina': p, 'variante': v[0], 'tipo': 'cambia', 'frac': frac, 'imagen': os.path.relpath(img, salida), 'ruido': ruido})
                    elif os.path.isfile(img):
                        os.remove(img)
            if a.referencia and not a.paginas and not a.variantes:
                for v in variantes:
                    d = os.path.join(ref_dir, v[0])
                    if os.path.isdir(d):
                        for f in sorted(os.listdir(d)):
                            if f.endswith('.png') and f[:-4] + '.html' not in todas and v == variantes[0]:
                                general_err.append('`%s.html` estaba en la referencia y ya no está: los QR impresos apuntan a ese nombre' % f[:-4])
            if a.referencia and a.actualizar_referencia:
                for v in variantes:
                    src = os.path.join(salida, 'capturas', v[0])
                    dst = os.path.join(ref_dir, v[0])
                    if a.paginas or not os.path.isdir(src):
                        continue
                    shutil.rmtree(dst, ignore_errors=True)
                    shutil.copytree(src, dst)
            if web_antes and not a.referencia:
                shutil.rmtree(ref_dir, ignore_errors=True)

        hojas = []
        if capturar and not a.sin_capturas:
            for v in variantes:
                hojas += hojas_contacto(os.path.join(salida, 'capturas'), os.path.join(salida, 'hojas'), v, paginas)
        web.cerrar()
        if web_antes:
            web_antes.cerrar()
        nav.close()
    if tmp_antes:
        shutil.rmtree(tmp_antes, ignore_errors=True)

    # la web publicada
    if a.publicada:
        base = a.publicada.rstrip('/') + '/'
        for p in paginas:
            try:
                rq = urllib.request.Request(base + urllib.parse.quote(p), method='HEAD')
                with urllib.request.urlopen(rq, timeout=15) as resp:
                    if resp.status >= 400:
                        general_err.append('en la web publicada, `%s` responde %d' % (p, resp.status))
            except Exception as e:
                general_err.append('en la web publicada, `%s` no responde (%s)' % (p, str(e)[:80]))

    # informe
    def agrupar(campo):
        d = {}
        for r in res:
            for m in r[campo]:
                d.setdefault((r['pagina'], m), []).append(r['variante'])
        return d

    def donde(vs):
        vs = sorted(set(vs))
        if len(vs) == len(variantes):
            return ''
        if vs == sorted(v[0] for v in variantes if 'movil' in v[0]):
            return ' — solo en el móvil'
        if vs == sorted(v[0] for v in variantes if 'escritorio' in v[0]):
            return ' — solo en escritorio'
        return ' — en ' + ', '.join(vs)

    errores, avisos, info = agrupar('errores'), agrupar('avisos'), agrupar('info')
    n_err, n_avi = len(errores) + len(general_err), len(avisos) + len(general_avi)
    L = ['# Comprobación de «%s»' % nombre_web, '',
         '%s · %d páginas × %d variantes (%s)' % (datetime.datetime.now().strftime('%d/%m/%Y %H:%M'), len(paginas), len(variantes),
                                                  ', '.join(v[0] for v in variantes)), '',
         '**%d errores · %d avisos%s**' % (n_err, n_avi, (' · %d páginas con cambios de aspecto' % len({c['pagina'] for c in cambios})) if comparar else ''), '']
    L += ['## Errores', '']
    L += ['- ' + m for m in general_err]
    L += ['- `%s`: %s%s' % (p, m, donde(vs)) for (p, m), vs in sorted(errores.items())]
    if not n_err:
        L.append('Ninguno.')
    L += ['', '## Avisos', '']
    L += ['- ' + m for m in general_avi]
    L += ['- `%s`: %s%s' % (p, m, donde(vs)) for (p, m), vs in sorted(avisos.items())]
    if not n_avi:
        L.append('Ninguno.')
    if comparar:
        L += ['', '## Cambios de aspecto', '']
        if not cambios:
            L.append('Ninguna página se ve distinta que antes.')
        por = {}
        for c in cambios:
            por.setdefault(c['pagina'], []).append(c)
        for p in sorted(por):
            cs = por[p]
            if cs[0]['tipo'] == 'nueva':
                L.append('- `%s`: página nueva (no había referencia)' % p)
            else:
                L.append('- `%s`: cambia en %s · %s' % (p, ', '.join('%s (%s %%)' % (c['variante'], pct(c['frac'])) for c in cs),
                                                         ' · '.join(c['imagen'] for c in cs[:2])))
    L += ['', '## Para saber', '']
    L += ['- ' + m for m in general_info]
    vistos = set()
    for (p, m), vs in sorted(info.items()):
        clave = m if m.startswith('PDF') else (p, m)
        if clave in vistos:
            continue
        vistos.add(clave)
        L.append('- %s' % m if m.startswith('PDF') else '- `%s`: %s' % (p, m))
    if hojas:
        L += ['', '## Hojas de contacto (para mirarlas)', ''] + ['- ' + os.path.relpath(h, salida) for h in hojas]
    with open(os.path.join(salida, 'informe.md'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(L) + '\n')
    with open(os.path.join(salida, 'informe.json'), 'w', encoding='utf-8') as f:
        json.dump({'web': nombre_web, 'paginas': paginas, 'variantes': [v[0] for v in variantes], 'errores': n_err, 'avisos': n_avi,
                   'generales': {'errores': general_err, 'avisos': general_avi, 'info': general_info}, 'cambios': cambios,
                   'detalle': [{k: r[k] for k in ('pagina', 'variante', 'errores', 'avisos', 'info', 'redirige', 'inestable')} for r in res]},
                  f, ensure_ascii=False, indent=1)
    print('\n'.join(L[:5]))
    print('Informe: ' + os.path.join(salida, 'informe.md'))
    sys.exit(1 if n_err or (a.estricto and n_avi) else 0)


if __name__ == '__main__':
    main()
