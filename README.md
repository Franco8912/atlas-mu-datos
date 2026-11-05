# Atlas MU para PC

El listado general muestra una ficha por proyecto. Las distintas opciones de EXP aparecen juntas. Los proyectos oficiales iniciales son MU Online y MU MAX Age.

El programa toma anuncios de MU Online List y MU Online Top 100, y usa las fichas nuevas de TopG para encontrar proyectos y opciones de EXP. Las fechas publicadas en directorios se muestran como anuncios. Una fecha pasada se muestra como tal. Los títulos oficiales iniciales enlazan a sus anuncios y se mantienen en `data/base.json`.

## Ver la prueba en tu PC

Extraé el ZIP y abrí `muestra/index.html`. La muestra se generó con datos recogidos de los tres listados. Es un corte del 4 de noviembre de 2026.

## Activar la publicación automática

1. Creá un repositorio público en GitHub con el nombre `atlas-mu-datos` y subí el contenido de la carpeta, incluida la carpeta `.github`.
2. En el repositorio, abrí **Settings → Pages** y elegí **GitHub Actions** como origen.
3. Andá a **Actions → Actualizar Atlas MU → Run workflow** para la primera prueba.
4. Cuando termine, abrí la URL que muestra la publicación. La misma dirección con `/servidores.json` al final es la que usará la APK.

El flujo se ejecuta una vez al día a las **10:17 de Argentina**. Lee la última lista publicada para conservar los proyectos cuando un directorio falla. Si ninguna fuente responde con fichas, el flujo conserva la publicación anterior. Las fuentes pueden cambiar su formato o limitar las lecturas automáticas.

La APK necesita una actualización por única vez para leer esa dirección cuando ya esté publicada.
