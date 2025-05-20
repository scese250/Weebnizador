# Weebnizador 

Weebnizador es un script de Python diseñado para aquellos de la vieja escuela les gusta mirar anime con honoríficos. Esto está diseñado principalmente para versiones piratas de grupos como "Erai-raws", pero en teoría debería servir con cualquier release de un grupo siempre y cuando los idiomas de los subtítulos estén bien configurados.

También funciona en situaciones donde, descargas un release en inglés y tiene los subtítulos en españos afuera del MKV, puedes usar la función de "Extra-Sub" para weebficar el sub en español. 

Tanto el script como este readme ESTÁN HECHOS CON IA. Yo no toqué ni una sola línea de código.

## ¿Qué hace? ✨

*   **Honoríficos Japoneses:** Cambia "el señor Naruto" por "Naruto-kun" en tus subtítulos en español, usando el inglés (o malayo) como referencia.
*   **Nombres al Estilo Japonés:** Invierte "Naruto Uzumaki" a "Uzumaki Naruto" usando la magia de la IA de Google Gemini (¡necesitas una API Key!).
*   **Fácil de Usar:** Arrastra tus archivos MKV y deja que el script haga el trabajo.
*   **Dos Modos:**
    *   **Multi-Sub:** Carga los subtítulos del MKV.
    *   **Extra-Sub:** Procesa un subtítulo español externo (debe tener el mismo nombre del MKV).
*   **Procesa Varios Videos:** Puedes arrastrar múltiples archivos a la vez.

## Primeros Pasos 🚀

1.  **Necesitas:**
    *   Python 3
    *   [MKVToolNix](https://mkvtoolnix.download/) (asegúrate que `mkvextract` y `mkvmerge` estén accesibles).
    *   Librerías de Python:
        ```bash
        pip install PyQt5 pysubs2 google-generativeai
        ```
2.  **Configura el Script (`Weebnizador.py`):**
    *   **API Key de Google Gemini:**
        *   Consigue una clave en [Google AI Studio](https://aistudio.google.com/app/apikey).
        *   Abre `Weebnizador.py` y reemplaza `"TU_API_KEY_DE_GEMINI_AQUI"` con tu clave real.
        ```python
        GEMINI_API_KEY = "TU_API_KEY_DE_GEMINI_AQUI" # <-- ¡PON TU CLAVE AQUÍ!
        ```
        *   _(Si no pones la clave, la inversión de nombres no funcionará, ¡pero el resto sí!)_
    *   **(Opcional) Rutas de MKVToolNix:** Si no están en la ruta por defecto (`C:\Program Files\MKVToolNix\`), ajusta `mkvextract_path` y `mkvmerge_path` en el script.

## ¿Cómo Usarlo? 👇

1.  Ejecuta `python Weebnizador.py`.
2.  Elige un modo ("Multi-Sub" o "Extra-Sub").
3.  Arrastra tus archivos `.mkv` a la nueva ventana.
4.  ¡Listo! Los subtítulos modificados se guardarán como `.ass` junto a tus videos.

## Importante ⚠️

*   La inversión de nombres con Gemini es experimental y depende de la IA.
*   Si compartes este script, ¡cuidado con exponer tu API Key!
