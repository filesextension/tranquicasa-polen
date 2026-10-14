#!/usr/bin/env python3
"""Tranquicasa · Riesgo de incendio forestal
Descarga la predicción de peligro meteorológico de incendios de AEMET (GeoTIFF de 1 km),
calcula para cada provincia qué parte de su superficie forestal está en cada nivel
y guarda el resultado en incendios.json.

Uso:
  python incendios.py             -> descarga real de AEMET
  python incendios.py --local DIR -> usa los .tif ya descargados en DIR (para pruebas)
  python incendios.py --forzar    -> regenera aunque AEMET no haya publicado nada nuevo
"""
import io, os, sys, json, glob, html, re, tarfile, tempfile, urllib.request, datetime as dt
import numpy as np
from PIL import Image

AQUI = os.path.dirname(os.path.abspath(__file__))
SALIDA = os.path.join(AQUI, 'incendios.json')
LIMITES = os.path.join(AQUI, 'provincias.geojson')
URL_AEMET = 'https://www.aemet.es/es/api-eltiempo/incendios/download'
URLS_LIMITES = [
    'https://gisco-services.ec.europa.eu/distribution/v2/nuts/geojson/NUTS_RG_03M_2024_4326_LEVL_3.geojson',
    'https://gisco-services.ec.europa.eu/distribution/v2/nuts/geojson/NUTS_RG_10M_2024_4326_LEVL_3.geojson',
    'https://gisco-services.ec.europa.eu/distribution/v2/nuts/geojson/NUTS_RG_10M_2021_4326_LEVL_3.geojson',
]
NIVELES = ['Muy bajo', 'Bajo', 'Moderado', 'Alto', 'Muy alto', 'Extremo']
PCT_DESTACADO = 5.0   # nivel destacado: el más alto que cubre al menos este % de la superficie forestal

# NUTS 3 (Eurostat) -> provincia INE. Baleares y Canarias están divididas por islas en NUTS 3.
NUTS = {
 'ES111': '15', 'ES112': '27', 'ES113': '32', 'ES114': '36', 'ES120': '33', 'ES130': '39',
 'ES211': '01', 'ES212': '20', 'ES213': '48', 'ES220': '31', 'ES230': '26',
 'ES241': '22', 'ES242': '44', 'ES243': '50', 'ES300': '28',
 'ES411': '05', 'ES412': '09', 'ES413': '24', 'ES414': '34', 'ES415': '37', 'ES416': '40', 'ES417': '42', 'ES418': '47', 'ES419': '49',
 'ES421': '02', 'ES422': '13', 'ES423': '16', 'ES424': '19', 'ES425': '45',
 'ES431': '06', 'ES432': '10',
 'ES511': '08', 'ES512': '17', 'ES513': '25', 'ES514': '43',
 'ES521': '03', 'ES522': '12', 'ES523': '46',
 'ES531': '07', 'ES532': '07', 'ES533': '07',
 'ES611': '04', 'ES612': '11', 'ES613': '14', 'ES614': '18', 'ES615': '21', 'ES616': '23', 'ES617': '29', 'ES618': '41',
 'ES620': '30', 'ES630': '51', 'ES640': '52',
 'ES703': '38', 'ES704': '35', 'ES705': '35', 'ES706': '38', 'ES707': '38', 'ES708': '35', 'ES709': '38',
}


def bajar(url, timeout=120):
    req = urllib.request.Request(url, headers={'User-Agent': 'Tranquicasa-Incendios/1.0 (+https://tranquicasa.es/incendios/)'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def limites():
    if not os.path.exists(LIMITES):
        ultimo = None
        for u in URLS_LIMITES:
            try:
                datos = json.loads(bajar(u))
                feats = [f for f in datos['features'] if str(f['properties'].get('NUTS_ID', '')).startswith('ES')]
                with open(LIMITES, 'w', encoding='utf-8') as f:
                    json.dump({'type': 'FeatureCollection', 'fuente': u, 'features': feats}, f)
                print('Límites descargados de', u)
                break
            except Exception as e:  # noqa: BLE001
                ultimo = e
                print('No se pudo descargar', u, '->', e)
        else:
            raise SystemExit(f'No se pudieron descargar los límites provinciales: {ultimo}')
    with open(LIMITES, encoding='utf-8') as f:
        return json.load(f)['features']


def anillos(geom):
    t, c = geom['type'], geom['coordinates']
    polis = [c] if t == 'Polygon' else c if t == 'MultiPolygon' else []
    return polis  # cada polígono: [exterior, hueco1, ...]


def mascaras(features, lon0, lat0, paso, ancho, alto):
    """Devuelve {provincia: array booleano (alto, ancho)} con los píxeles cuyo centro cae dentro."""
    from matplotlib.path import Path
    lons = lon0 + paso * (np.arange(ancho) + 0.5)
    lats = lat0 - paso * (np.arange(alto) + 0.5)
    out = {}
    for f in features:
        cod = NUTS.get(f['properties'].get('NUTS_ID'))
        if not cod:
            continue
        for poli in anillos(f['geometry']):
            ext = np.asarray(poli[0], dtype=float)
            x0, y0 = ext.min(axis=0); x1, y1 = ext.max(axis=0)
            cj = np.where((lons >= x0) & (lons <= x1))[0]
            ci = np.where((lats >= y0) & (lats <= y1))[0]
            if not len(cj) or not len(ci):
                continue
            gx, gy = np.meshgrid(lons[cj], lats[ci])
            pts = np.column_stack([gx.ravel(), gy.ravel()])
            dentro = Path(ext).contains_points(pts)
            for hueco in poli[1:]:
                dentro &= ~Path(np.asarray(hueco, dtype=float)).contains_points(pts)
            if not dentro.any():
                continue
            m = out.setdefault(cod, np.zeros((alto, ancho), dtype=bool))
            sub = dentro.reshape(len(ci), len(cj))
            m[np.ix_(ci, cj)] |= sub
    return out


def leer_tif(ruta):
    im = Image.open(ruta)
    a = np.array(im, dtype=np.float32)
    tie = im.tag_v2[33922]
    esc = im.tag_v2[33550]
    meta = html.unescape(html.unescape(str(im.tag_v2.get(42112, ''))))
    vt = re.search(r'name="valid_time">([^<]+)<', meta)
    mt = re.search(r'name="model_time">([^<]+)<', meta)
    return a, float(tie[3]), float(tie[4]), float(esc[0]), (vt.group(1) if vt else None), (mt.group(1) if mt else None)


def descargar_aemet():
    tmp = tempfile.mkdtemp()
    bin_ = bajar(URL_AEMET, timeout=180)
    with tarfile.open(fileobj=io.BytesIO(bin_), mode='r:*') as t:
        for m in t.getmembers():
            if m.isfile() and m.name.endswith('.tif') and '/' not in m.name.strip('./'):
                t.extract(m, tmp)
    return tmp


def main():
    if '--local' in sys.argv:
        carpeta = sys.argv[sys.argv.index('--local') + 1]
    else:
        carpeta = descargar_aemet()
    tifs = sorted(glob.glob(os.path.join(carpeta, '*peligro_*_D*.tif')))
    previo = {}
    if os.path.exists(SALIDA):
        try:
            with open(SALIDA, encoding='utf-8') as f:
                previo = json.load(f)
        except Exception:  # noqa: BLE001
            previo = {}
    if not tifs:
        raise SystemExit('El archivo de AEMET no trae ningún .tif de peligro')
    feats = limites()
    cache_masc = {}
    dias = {}
    modelo = None
    for ruta in tifs:
        region = 'c' if '_c_D' in os.path.basename(ruta) else 'p'
        a, lon0, lat0, paso, vt, mt = leer_tif(ruta)
        modelo = mt or modelo
        if not vt:
            continue
        fecha = vt[:10]
        clave = (region, a.shape, round(lon0, 3), round(lat0, 3))
        if clave not in cache_masc:
            cache_masc[clave] = mascaras(feats, lon0, lat0, paso, a.shape[1], a.shape[0])
        for cod, m in cache_masc[clave].items():
            v = a[m]
            v = v[np.isfinite(v) & (v >= 1) & (v <= 6)].astype(int)
            if v.size == 0:
                continue
            cuenta = np.bincount(v, minlength=7)[1:7]
            pct = (cuenta / v.size * 100).round(1).tolist()
            maximo = int(v.max())
            dest = 1
            for n in range(6, 0, -1):
                if sum(pct[n - 1:]) >= PCT_DESTACADO:
                    dest = n
                    break
            dias.setdefault(cod, {})[fecha] = {'fecha': fecha, 'max': maximo, 'dest': dest, 'pct': pct,
                                                'alto': round(sum(pct[3:]), 1), 'px': int(v.size)}
    if previo.get('modelo') and previo.get('modelo') == modelo and '--forzar' not in sys.argv:
        print('AEMET aún no ha publicado una predicción nueva (sigue la del', modelo, '). No se cambia nada.')
        return
    if not dias:
        raise SystemExit('No se pudo asignar ningún píxel a ninguna provincia: revisa los límites')
    provincias = {cod: {'dias': [d[k] for k in sorted(d)]} for cod, d in dias.items()}
    salida = {
        'version': 1,
        'generado': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'modelo': modelo,
        'fuente': 'AEMET: predicción de peligro meteorológico de incendios forestales (nivel diario, 1 km)',
        'niveles': NIVELES,
        'pct_destacado': PCT_DESTACADO,
        'provincias': provincias,
    }
    with open(SALIDA, 'w', encoding='utf-8') as f:
        json.dump(salida, f, ensure_ascii=False, separators=(',', ':'))
    falta = sorted(set(NUTS.values()) - set(provincias))
    print('incendios.json actualizado:', len(provincias), 'provincias', ('(sin datos: ' + ', '.join(falta) + ')') if falta else '')


if __name__ == '__main__':
    main()
