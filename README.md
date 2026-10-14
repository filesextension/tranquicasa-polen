# Tranquicasa · Polen

Cada día, GitHub ejecuta `polen.py`. Descarga la previsión de polen de Copernicus, calcula el nivel en cada capital de provincia y guarda el resultado en `polen.json`. Tu web lee ese archivo y genera `tranquicasa.es/polen/`.

## Puesta en marcha (una sola vez)

1. Crea una cuenta gratis en el Atmosphere Data Store de Copernicus: https://ads.atmosphere.copernicus.eu
2. Entra en el conjunto de datos «CAMS European air quality forecasts», pestaña «Download», baja hasta «Terms of use» y acepta la licencia. Sin esto, la descarga da error.
3. En tu perfil del ADS, copia tu «Personal Access Token».
4. En este repositorio de GitHub: Settings → Secrets and variables → Actions → New repository secret. Nombre: `ADS_KEY`. Valor: el token.
5. Pestaña Actions → «Polen diario» → Run workflow (deja «no» en prueba). En unos minutos aparece `polen.json`.

Si quieres probar sin clave, ejecuta el workflow con «sí» en prueba. Genera datos inventados marcados como prueba, que la web nunca publica.

## Datos

- Fuente: Copernicus Atmosphere Monitoring Service (CAMS), previsión europea (ensemble). Licencia de Copernicus: uso libre, también comercial, citando la fuente.
- Pólenes: gramíneas, olivo, abedul, aliso, artemisa y ambrosía. Canarias queda fuera del dominio europeo de CAMS.
- Niveles: umbrales de la Red Española de Aerobiología sobre la media diaria (granos/m³).
- Fuera de la temporada de polen, Copernicus no publica estos datos y el archivo sale vacío. Es normal.

# Tranquicasa · Riesgo de incendio forestal

Tres veces al día, GitHub ejecuta `incendios.py`. Descarga la predicción de peligro meteorológico de incendios de AEMET (mapas de 1 km para hoy y los 7 días siguientes), calcula qué parte de los montes de cada provincia está en cada nivel y guarda el resultado en `incendios.json`. Tu web lee ese archivo y genera `tranquicasa.es/incendios/`.

- No necesita clave: la descarga de AEMET es pública.
- La primera vez descarga los límites de las provincias (Eurostat GISCO) y los guarda en `provincias.geojson`. Las siguientes veces usa ese archivo.
- AEMET publica una predicción al día. Si no hay una nueva, el workflow termina sin cambiar nada.
- Fuente: Agencia Estatal de Meteorología (AEMET). Su uso está autorizado citando a AEMET como autora.
