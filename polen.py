#!/usr/bin/env python3
"""Tranquicasa · Polen
Descarga la previsión de polen de Copernicus (CAMS European air quality forecasts),
calcula el nivel diario en cada capital de provincia según los umbrales de la
Red Española de Aerobiología y guarda el resultado en polen.json.

Uso:
  python polen.py              -> descarga real (necesita ~/.cdsapirc con tu clave del ADS)
  python polen.py --prueba     -> genera datos de prueba sin descargar nada
"""
import json, os, sys, glob, zipfile, tempfile, datetime as dt
import numpy as np

SALIDA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'polen.json')

# Tipos de polen de CAMS -> nombre, palabras para reconocer la variable en el archivo, grupo REA
TIPOS = {
    'gramineas': dict(ads='grass_pollen', nombre='Gramíneas', claves=['grass', 'gpg'], grupo=2),
    'olivo': dict(ads='olive_pollen', nombre='Olivo', claves=['olive', 'opg'], grupo=4),
    'abedul': dict(ads='birch_pollen', nombre='Abedul', claves=['birch', 'bpg'], grupo=3),
    'aliso': dict(ads='alder_pollen', nombre='Aliso', claves=['alder', 'apg'], grupo=3),
    'artemisa': dict(ads='mugwort_pollen', nombre='Artemisa', claves=['mugwort', 'mpg'], grupo=2),
    'ambrosia': dict(ads='ragweed_pollen', nombre='Ambrosía', claves=['ragweed', 'rwpg'], grupo=2),
}
# Umbrales de la Red Española de Aerobiología (granos/m3, media diaria): límite superior de bajo y de moderado
UMBRALES = {2: (25, 50), 3: (30, 50), 4: (50, 200)}

# Capitales de provincia (Canarias queda fuera del dominio de CAMS Europa, que empieza en 30º N)
CAPITALES = {
 '01': ('Vitoria-Gasteiz', 42.85, -2.67), '02': ('Albacete', 38.99, -1.86), '03': ('Alicante', 38.35, -0.48),
 '04': ('Almería', 36.84, -2.46), '05': ('Ávila', 40.66, -4.70), '06': ('Badajoz', 38.88, -6.97),
 '07': ('Palma', 39.57, 2.65), '08': ('Barcelona', 41.39, 2.17), '09': ('Burgos', 42.34, -3.70),
 '10': ('Cáceres', 39.47, -6.37), '11': ('Cádiz', 36.53, -6.29), '12': ('Castellón de la Plana', 39.99, -0.05),
 '13': ('Ciudad Real', 38.98, -3.93), '14': ('Córdoba', 37.88, -4.78), '15': ('A Coruña', 43.36, -8.41),
 '16': ('Cuenca', 40.07, -2.13), '17': ('Girona', 41.98, 2.82), '18': ('Granada', 37.18, -3.60),
 '19': ('Guadalajara', 40.63, -3.17), '20': ('San Sebastián', 43.32, -1.98), '21': ('Huelva', 37.26, -6.95),
 '22': ('Huesca', 42.14, -0.41), '23': ('Jaén', 37.78, -3.79), '24': ('León', 42.60, -5.57),
 '25': ('Lleida', 41.62, 0.62), '26': ('Logroño', 42.47, -2.45), '27': ('Lugo', 43.01, -7.56),
 '28': ('Madrid', 40.42, -3.70), '29': ('Málaga', 36.72, -4.42), '30': ('Murcia', 37.99, -1.13),
 '31': ('Pamplona', 42.81, -1.64), '32': ('Ourense', 42.34, -7.86), '33': ('Oviedo', 43.36, -5.85),
 '34': ('Palencia', 42.01, -4.53), '36': ('Pontevedra', 42.43, -8.64), '37': ('Salamanca', 40.97, -5.66),
 '39': ('Santander', 43.46, -3.80), '40': ('Segovia', 40.95, -4.12), '41': ('Sevilla', 37.39, -5.98),
 '42': ('Soria', 41.76, -2.46), '43': ('Tarragona', 41.12, 1.25), '44': ('Teruel', 40.34, -1.11),
 '45': ('Toledo', 39.86, -4.02), '46': ('Valencia', 39.47, -0.38), '47': ('Valladolid', 41.65, -4.72),
 '48': ('Bilbao', 43.26, -2.93), '49': ('Zamora', 41.50, -5.75), '50': ('Zaragoza', 41.65, -0.88),
 '51': ('Ceuta', 35.89, -5.32), '52': ('Melilla', 35.29, -2.94),
}
AREA = [44.5, -10.0, 35.0, 4.6]  # Norte, Oeste, Sur, Este


def nivel(valor, grupo):
    """0 nulo, 1 bajo, 2 moderado, 3 alto (criterios de la Red Española de Aerobiología)."""
    if valor is None or not np.isfinite(valor) or valor < 1:
        return 0
    bajo, mod = UMBRALES[grupo]
    if valor <= bajo:
        return 1
    if valor <= mod:
        return 2
    return 3


def hora_local_madrid(t_utc):
    """Hora oficial peninsular: UTC+2 de último domingo de marzo a último domingo de octubre, UTC+1 el resto."""
    y = t_utc.year
    def ultimo_domingo(mes):
        d = dt.datetime(y, mes, 31) if mes in (3, 10) else None
        while d.weekday() != 6:
            d -= dt.timedelta(days=1)
        return d.replace(hour=1)
    verano = ultimo_domingo(3) <= t_utc < ultimo_domingo(10)
    return t_utc + dt.timedelta(hours=2 if verano else 1)


def procesar(campos, base_utc):
    """campos: {tipo: (horas_desde_base[], lats[], lons[], datos[t, lat, lon])} -> diccionario de salida."""
    provincias = {}
    for cod, (ciudad, la, lo) in CAPITALES.items():
        dias = {}
        for tipo, (horas, lats, lons, datos) in campos.items():
            i = int(np.abs(lats - la).argmin())
            j = int(np.abs(lons - lo).argmin())
            serie = datos[:, i, j]
            for h, v in zip(horas, serie):
                t = base_utc + dt.timedelta(hours=float(h))
                dia = hora_local_madrid(t).strftime('%Y-%m-%d')
                dias.setdefault(dia, {}).setdefault(tipo, []).append(float(v))
        lista = []
        for dia in sorted(dias):
            pol = {}
            for tipo, vals in dias[dia].items():
                if len(vals) < 12:  # día incompleto: no lo publicamos
                    continue
                media = float(np.nanmean(vals))
                pol[tipo] = {'v': round(media, 1), 'n': nivel(media, TIPOS[tipo]['grupo'])}
            if pol:
                lista.append({'fecha': dia, 'polen': pol, 'max': max(p['n'] for p in pol.values())})
        provincias[cod] = {'ciudad': ciudad, 'dias': lista}
    return {
        'version': 1,
        'generado': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'base': base_utc.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'fuente': 'Copernicus Atmosphere Monitoring Service (CAMS), European air quality forecasts (ensemble)',
        'tipos': {k: {'nombre': v['nombre'], 'grupo': v['grupo'], 'umbrales': UMBRALES[v['grupo']]} for k, v in TIPOS.items()},
        'provincias': provincias,
    }


def descargar(base_utc):
    import cdsapi
    import xarray as xr
    tmp = tempfile.mkdtemp()
    destino = os.path.join(tmp, 'cams.zip')
    peticion = {
        'variable': [t['ads'] for t in TIPOS.values()],
        'model': 'ensemble',
        'level': '0',
        'type': 'forecast',
        'date': f"{base_utc:%Y-%m-%d}/{base_utc:%Y-%m-%d}",
        'time': '00:00',
        'leadtime_hour': [str(h) for h in range(97)],
        'data_format': 'netcdf_zip',
        'area': AREA,
    }
    cdsapi.Client().retrieve('cams-europe-air-quality-forecasts', peticion, destino)
    ficheros = []
    if zipfile.is_zipfile(destino):
        with zipfile.ZipFile(destino) as z:
            z.extractall(tmp)
        ficheros = glob.glob(os.path.join(tmp, '**', '*.nc'), recursive=True)
    else:
        ficheros = [destino]
    campos = {}
    for fn in ficheros:
        ds = xr.open_dataset(fn)
        lat = 'latitude' if 'latitude' in ds.coords else 'lat'
        lon = 'longitude' if 'longitude' in ds.coords else 'lon'
        lats = np.asarray(ds[lat].values, dtype=float)
        lons = np.asarray(ds[lon].values, dtype=float)
        lons = np.where(lons > 180, lons - 360, lons)
        for nombre, var in ds.data_vars.items():
            texto = (nombre + ' ' + str(var.attrs.get('long_name', '')) + ' ' + str(var.attrs.get('species', ''))).lower()
            tipo = next((k for k, t in TIPOS.items() if any(c in texto for c in t['claves'])), None)
            if not tipo:
                continue
            d = var.squeeze()
            tdim = [x for x in d.dims if x not in (lat, lon)]
            if len(tdim) != 1:
                raise SystemExit(f'Dimensiones inesperadas en {nombre}: {d.dims}')
            tv = d[tdim[0]].values
            if np.issubdtype(tv.dtype, np.timedelta64):
                horas = tv / np.timedelta64(1, 'h')
            elif np.issubdtype(tv.dtype, np.datetime64):
                horas = (tv - np.datetime64(base_utc.replace(tzinfo=None))) / np.timedelta64(1, 'h')
            else:
                horas = np.asarray(tv, dtype=float)
            datos = np.asarray(d.transpose(tdim[0], lat, lon).values, dtype=float)
            campos[tipo] = (np.asarray(horas, dtype=float), lats, lons, datos)
    falta = [k for k in TIPOS if k not in campos]
    if len(falta) == len(TIPOS):
        print('El archivo de Copernicus no trae polen: probablemente estamos fuera de temporada.')
        return {}
    if falta:
        print('Aviso: no vienen estas variables:', ', '.join(falta))
    return campos


def datos_prueba(base_utc):
    lats = np.arange(35.0, 44.6, 0.1)
    lons = np.arange(-10.0, 4.7, 0.1)
    horas = np.arange(0, 97)
    rng = np.random.default_rng(1)
    campos = {}
    escala = {'gramineas': 60, 'olivo': 150, 'abedul': 20, 'aliso': 10, 'artemisa': 8, 'ambrosia': 2}
    for k in TIPOS:
        ciclo = 0.5 + 0.5 * np.sin((horas - 8) / 24 * 2 * np.pi)
        sur = np.clip((44.5 - lats) / 9.5, 0, 1)
        campo = escala[k] * ciclo[:, None, None] * sur[None, :, None] * (0.6 + 0.8 * rng.random((1, 1, lons.size)))
        campos[k] = (horas, lats, lons, campo)
    return campos


def main():
    hoy = dt.datetime.now(dt.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    if '--prueba' in sys.argv:
        campos, base = datos_prueba(hoy), hoy
    else:
        base, campos, error = hoy, None, None
        for intento in (0, 1):  # si la pasada de hoy aún no está publicada, usa la de ayer
            base = hoy - dt.timedelta(days=intento)
            try:
                campos = descargar(base)
                break
            except SystemExit:
                raise
            except Exception as e:  # noqa: BLE001
                error = e
                print(f'No se pudo descargar la previsión del {base:%Y-%m-%d}: {e}')
        if campos is None:
            texto = str(error).lower()
            if any(x in texto for x in ('licen', '401', '403', 'unauthor', 'key')):
                raise SystemExit(f'Error de acceso a Copernicus (revisa la clave y la licencia): {error}')
            print('Sin datos de polen en Copernicus para hoy (fuera de temporada o datos no publicados).')
            campos = {}
    salida = procesar(campos, base.replace(tzinfo=None))
    salida['prueba'] = '--prueba' in sys.argv
    with open(SALIDA, 'w', encoding='utf-8') as f:
        json.dump(salida, f, ensure_ascii=False, separators=(',', ':'))
    print('polen.json actualizado:', len(salida['provincias']), 'provincias')


if __name__ == '__main__':
    main()
