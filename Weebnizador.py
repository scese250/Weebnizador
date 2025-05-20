import os
import subprocess
import pysubs2
import re
import json
from PyQt5 import QtWidgets, QtCore, QtGui
import google.generativeai as genai # Importar la librería de Gemini

# --- CONFIGURACIÓN DE API DE GEMINI ---
# ADVERTENCIA: Guardar tu API Key directamente en el código no es seguro para scripts compartidos o en producción.
# Considera usar variables de entorno o un archivo de configuración para mayor seguridad si distribuyes este script.
# Para obtener una API Key, visita: https://aistudio.google.com/app/apikey
GEMINI_API_KEY = "TU_API_KEY_DE_GEMINI_AQUI" # <-- ¡REEMPLAZA ESTO CON TU API KEY REAL!

# Lista de honoríficos comunes en japonés
honorificos = ["-san", "-chan", "-kun", "-sama", "-sensei", "-senpai", "-nee", "-nii", "-dono"]

# Combinaciones redundantes en español
palabras_redundantes = ["la señorita", "el señorito", "señorita", "señorito", "señor", "señora", "La señorita", "El señorito"]

mkvextract_path = r"C:\Program Files\MKVToolNix\mkvextract.exe"
mkvmerge_path = r"C:\Program Files\MKVToolNix\mkvmerge.exe"

def call_gemini_api(prompt_text, name_list_for_api):
    if not GEMINI_API_KEY or GEMINI_API_KEY == "TU_API_KEY_DE_GEMINI_AQUI":
        print("Error: API Key de Gemini no configurada. La inversión de nombres será omitida.")
        return None

    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel('gemini-1.5-flash')

        full_prompt = f"{prompt_text}\n\nLista de nombres:\n{name_list_for_api}"
        
        response = model.generate_content(full_prompt)
        return response.text
    except Exception as e:
        print(f"Error al llamar a la API de Gemini: {e}")
        return None

class ProcessingThread(QtCore.QThread):
    overall_progress_updated = QtCore.pyqtSignal(int)
    current_file_progress_updated = QtCore.pyqtSignal(int)
    current_file_changed = QtCore.pyqtSignal(str)
    log_message = QtCore.pyqtSignal(str)
    processing_finished_signal = QtCore.pyqtSignal()

    def __init__(self, files, mode, parent=None):
        super().__init__(parent)
        self.files = files
        self.mode = mode
        self.mkvextract_path = mkvextract_path
        self.mkvmerge_path = mkvmerge_path
        self.temp_sub_ingles = None
        self.temp_sub_espanol = None
        self.temp_sub_malayo = None

    def _emit_log(self, message):
        self.log_message.emit(message)

    def _emit_current_file_progress(self, value):
        value = max(0, min(100, value))
        self.current_file_progress_updated.emit(value)

    def _extract_subtitles_metadata(self, mkv_file):
        LANGUAGE_PRIORITY = {
            'spa': {
                'latam': {'title': ['latin_america', 'latam', 'cr_spanish(latin_america)'], 'lang': ['latin america', 'spanish (latin america)'], 'score': 3},
                'es': {'title': ['español', 'spanish'], 'lang': ['español', 'spanish'], 'score': 2},
                'default': {'score': 1}
            },
            'eng': {
                'default': {'score': 1}
            },
            'may': { 
                'default': {'title': ['cr_malay', 'malay'], 'lang': ['may', 'malay', 'bahasa melayu'], 'score': 1}
            }
        }

        def get_language_score(track):
            if 'properties' not in track: return 0
            lang = track['properties'].get('language', '').lower()
            title = track['properties'].get('track_name', '').lower()
            # Intenta hacer coincidir con 'may' usando language_ietf si 'language' es 'und' o genérico.
            base_lang_prop = track['properties'].get('language_ietf', '').lower() if track['properties'].get('language_ietf', '').lower() in LANGUAGE_PRIORITY else lang
            base_lang = next((k for k in LANGUAGE_PRIORITY if k in base_lang_prop), None) 
            
            if not base_lang: return 0
            # Si base_lang es 'may', prioriza las claves específicas de 'may' en LANGUAGE_PRIORITY
            if base_lang == 'may':
                variant_data = LANGUAGE_PRIORITY['may'].get('default', {}) # Asumiendo que 'may' solo tiene 'default' por ahora
                if 'title' in variant_data and any(pattern in title for pattern in variant_data['title']): return variant_data['score']
                if 'lang' in variant_data and any(pattern in lang for pattern in variant_data['lang']): return variant_data['score']
                return variant_data.get('score',0)

            # Lógica original para otros idiomas
            for variant, criteria in LANGUAGE_PRIORITY[base_lang].items():
                if variant == 'default': continue
                if 'title' in criteria and any(pattern in title for pattern in criteria['title']): return criteria['score']
                if 'lang' in criteria and any(pattern in lang for pattern in criteria['lang']): return criteria['score']
            return LANGUAGE_PRIORITY[base_lang]['default']['score']

        try:
            identify_command = [self.mkvmerge_path, "--identify", "-J", mkv_file]
            result = subprocess.run(identify_command, capture_output=True, text=True, encoding='utf-8', errors='replace', check=True)
            self._emit_current_file_progress(10)

            if not result.stdout:
                self._emit_log("Error: No output received from mkvmerge")
                return None, None, None
            try:
                json_output = json.loads(result.stdout)
            except json.JSONDecodeError as e:
                self._emit_log(f"Error decoding JSON from mkvmerge: {e}")
                return None, None, None

            best_subtitles = {'spa': None, 'eng': None, 'may': None}
            best_scores = {'spa': 0, 'eng': 0, 'may': 0}

            for track in json_output['tracks']:
                if track['type'] == 'subtitles':
                    score = get_language_score(track)
                    # Determinar a qué idioma base pertenece la pista para actualizar best_subtitles
                    lang_prop_track = track['properties'].get('language', '').lower()
                    ietf_lang_prop_track = track['properties'].get('language_ietf', '').lower()
                    
                    assigned_lang_key = None
                    if 'may' in ietf_lang_prop_track or ('may' in lang_prop_track and not ietf_lang_prop_track): # Prioridad a IETF para 'may'
                        assigned_lang_key = 'may'
                    elif 'eng' in lang_prop_track or 'eng' in ietf_lang_prop_track :
                         assigned_lang_key = 'eng'
                    elif 'spa' in lang_prop_track or 'spa' in ietf_lang_prop_track:
                         assigned_lang_key = 'spa'
                    # Add more specific language checks if needed before falling back to just 'in'
                    else: # Fallback general (podría ser menos preciso)
                        for key_lang_priority in LANGUAGE_PRIORITY.keys():
                            if key_lang_priority in lang_prop_track or key_lang_priority in ietf_lang_prop_track:
                                assigned_lang_key = key_lang_priority
                                break
                    
                    if assigned_lang_key and score > best_scores.get(assigned_lang_key, -1): # Usar .get con default para evitar KeyError
                        best_subtitles[assigned_lang_key] = track
                        best_scores[assigned_lang_key] = score
            
            self._emit_current_file_progress(20)
            base_name = os.path.splitext(os.path.basename(mkv_file))[0]
            output_dir = os.path.dirname(mkv_file)
            sub_paths = {}
            
            num_subs_to_extract = len([t for t in best_subtitles.values() if t])
            progress_per_sub = 30 / num_subs_to_extract if num_subs_to_extract > 0 else 0
            current_extraction_progress = 20

            for lang_key_extract, track_info_extract in best_subtitles.items():
                if track_info_extract is not None:
                    output_filename = f"{base_name}_{lang_key_extract}.ass" 
                    output_path = os.path.join(output_dir, output_filename)
                    
                    extract_command = [self.mkvextract_path, mkv_file, 'tracks', f'{track_info_extract["id"]}:{output_path}']
                    try:
                        subprocess.run(extract_command, check=True, capture_output=True)
                        sub_paths[lang_key_extract] = output_path
                        self._emit_log(f"Best {lang_key_extract} subtitle found (ID: {track_info_extract['id']}, Title: {track_info_extract['properties'].get('track_name', '')}, Lang: {track_info_extract['properties'].get('language', '')}, IETF: {track_info_extract['properties'].get('language_ietf', '')} Score: {best_scores[lang_key_extract]}): {output_path}")
                        current_extraction_progress += progress_per_sub
                        self._emit_current_file_progress(int(current_extraction_progress))
                    except subprocess.CalledProcessError as e:
                        self._emit_log(f"Error extracting {lang_key_extract} subtitle: {e.stderr.decode(errors='replace') if e.stderr else e}")
                        sub_paths[lang_key_extract] = None
            
            self._emit_current_file_progress(50)
            return sub_paths.get('eng'), sub_paths.get('spa'), sub_paths.get('may')

        except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
            self._emit_log(f"Error processing MKV file for subtitle extraction: {e}")
            return None, None, None
        except Exception as e:
            self._emit_log(f"Unexpected error during subtitle extraction: {e}")
            return None, None, None

    def _eliminar_creditos(self, subs):
        creditos_patron = re.compile(r"(Traducción|Edición|Control de calidad).*", re.IGNORECASE)
        for linea in subs:
            if creditos_patron.search(linea.text):
                linea.text = ""
        return subs

    def _invertir_nombres_via_gemini(self, subs_espanol):
        self._emit_log("Iniciando detección de Nombre-Apellido para inversión vía Gemini.")
        patron_nombre_apellido = re.compile(r"\b([A-Z][a-zÀ-ÖØ-öø-ÿ]+)\s+([A-Z][a-zÀ-ÖØ-öø-ÿ]+)\b") # Ampliado para más caracteres latinos
        nombres_detectados_unicos = set()

        for linea in subs_espanol:
            # Dividir la línea de texto por el código de salto de línea \N de ASS
            # Esto asegura que el regex solo opere en texto continuo dentro de cada "sub-línea" visual.
            segmentos = linea.text.split("\\N") 
            for segmento in segmentos:
                # Aplicar el regex a cada segmento individualmente
                coincidencias = patron_nombre_apellido.findall(segmento)
                for nombre, apellido in coincidencias:
                    nombres_detectados_unicos.add(f"{nombre} {apellido}")

        if not nombres_detectados_unicos:
            self._emit_log("No se detectaron patrones Nombre-Apellido para enviar a Gemini.")
            return subs_espanol

        self._emit_log(f"Nombres detectados para Gemini (hasta 5): {', '.join(list(nombres_detectados_unicos)[:5])}...")

        lista_nombres_para_api = "\n".join(sorted(list(nombres_detectados_unicos)))
        prompt_gemini = (
            "De la siguiente lista de pares de palabras, donde cada palabra inicia con mayúscula, "
            "identifica aquellos que son probablemente 'Nombre Apellido' de personas y cámbialos a 'Apellido Nombre'.\n"
            "Si un par de palabras no parece ser un nombre de persona (por ejemplo, 'Autos Locos', 'Casa Azul', 'Perro Azul'), omítelo y no lo incluyas en la respuesta. Si detectas palabras en español o inglés junto a un nombre OMÍTELO, ya que esta lista se obtuvo de una pista de subtítulos, por lo que podría por error contener palabras capitalizadas junto a un nombre; por ejemplo 'Soy Hisoka', 'Eres Naruto'.\n"
            "Si un par parece ser 'Título Nombre' (ej. 'Doctor Luis'), trátalo como 'Nombre Apellido' si 'Doctor' no es un nombre propio común; si 'Doctor' es el nombre, inviértelo. Usa tu mejor juicio para nombres comunes.\n"
            "Devuelve ÚNICAMENTE la lista con los cambios realizados, un par por línea. No incluyas los pares omitidos.\n\n"
            "Ejemplo de entrada:\n"
            "Naruto Uzumaki\n"
            "María García\n"
            "Autos Locos\n"
            "Perro Azul\n"
            "El Pepe\n" 
            "Ana López\n"
            "Juan Pabro\n"
            "Doctor Luis\n"
            "Javier Rodríguez\n"
            "Casa Azul\n\n"
            "Ejemplo de salida esperada para la entrada anterior:\n"
            "Uzumaki Naruto\n"
            "García María\n"
            "López Ana\n"
            "Pabro Juan\n" # Si Gemini lo considera un nombre
            "Luis Doctor\n" # O como lo interprete Gemini, podría ser Doctor Luis
            "Rodríguez Javier"
        )

        self._emit_log("Enviando solicitud a Gemini API para inversión de nombres...")
        respuesta_gemini_texto = call_gemini_api(prompt_gemini, lista_nombres_para_api)
        
        if not respuesta_gemini_texto:
            self._emit_log("No se recibió respuesta de Gemini o hubo un error. No se invertirán nombres.")
            return subs_espanol

        mapeo_nombres_invertidos = {}
        nombres_invertidos_de_api = [linea.strip() for linea in respuesta_gemini_texto.split('\n') if linea.strip()]
        
        for nombre_completo_original_str in nombres_detectados_unicos:
            partes_original = nombre_completo_original_str.split()
            if len(partes_original) != 2: continue

            nombre_orig = partes_original[0]
            apellido_orig = partes_original[1]

            for invertido_api_str in nombres_invertidos_de_api:
                partes_invertido_api = invertido_api_str.split()
                if len(partes_invertido_api) != 2: continue
                if partes_invertido_api[0] == apellido_orig and partes_invertido_api[1] == nombre_orig:
                    mapeo_nombres_invertidos[nombre_completo_original_str] = invertido_api_str
                    self._emit_log(f"Mapeo Gemini: '{nombre_completo_original_str}' -> '{invertido_api_str}'")
                    break 
        
        if not mapeo_nombres_invertidos:
            self._emit_log("Gemini no devolvió nombres invertidos en el formato esperado o no encontró coincidencias.")
            return subs_espanol

        self._emit_log("Aplicando nombres invertidos a los subtítulos...")
        for linea_idx, linea_obj in enumerate(subs_espanol): # Usar enumerate para tener índice si fuera necesario
            texto_modificado = linea_obj.text
            # Reemplazar usando los mapeos. Es importante el orden si hay solapamientos (poco probable aquí)
            # Se ordena por longitud del original para evitar reemplazar subcadenas primero, aunque con \b es más seguro.
            for original, invertido in sorted(mapeo_nombres_invertidos.items(), key=lambda x: len(x[0]), reverse=True):
                patron_reemplazo = r'\b' + re.escape(original) + r'\b'
                texto_modificado = re.sub(patron_reemplazo, invertido, texto_modificado)
            if linea_obj.text != texto_modificado: # Aplicar solo si hubo cambios
                 linea_obj.text = texto_modificado
        
        self._emit_log("Inversión de Nombre-Apellido completada.")
        return subs_espanol


    def _reemplazar_honorificos(self, sub_ingles_path, sub_espanol_path, sub_malayo_path, output_path, rango_segundos=5):
        subs_fuente_honorificos = None
        path_fuente_usado = None
        source_lang_name = ""

        if sub_ingles_path:
            try:
                subs_ingles_candidato = pysubs2.load(sub_ingles_path)
                tiene_honorificos_ingles = False
                for linea_ingles_candidata in subs_ingles_candidato:
                    for honorifico_item in honorificos:
                        patron_detect = re.compile(rf"\b[A-Za-zÀ-ÖØ-öø-ÿ]+{re.escape(honorifico_item)}\b", re.IGNORECASE)
                        if patron_detect.search(linea_ingles_candidata.text):
                            tiene_honorificos_ingles = True; break
                    if tiene_honorificos_ingles: break
                
                if tiene_honorificos_ingles:
                    subs_fuente_honorificos = subs_ingles_candidato
                    path_fuente_usado = sub_ingles_path
                    source_lang_name = "Inglés"
                    self._emit_log("Usando subtítulos en Inglés como fuente de honoríficos.")
                else:
                    self._emit_log("Subtítulos en Inglés encontrados, pero no contienen honoríficos. Comprobando Malayo.")
            except Exception as e:
                self._emit_log(f"Error cargando subtítulos en Inglés desde {sub_ingles_path}: {e}. Comprobando Malayo.")

        if subs_fuente_honorificos is None and sub_malayo_path:
            try:
                subs_malayo_candidato = pysubs2.load(sub_malayo_path)
                subs_fuente_honorificos = subs_malayo_candidato # Podríamos añadir chequeo de honoríficos aquí también
                path_fuente_usado = sub_malayo_path
                source_lang_name = "Malayo"
                self._emit_log("Usando subtítulos en Malayo como fuente de honoríficos.")
            except Exception as e:
                self._emit_log(f"Error cargando subtítulos en Malayo desde {sub_malayo_path}: {e}.")
        
        if sub_espanol_path is None:
            self._emit_log("No se proporcionó ruta para el subtítulo en Español. No se puede continuar.")
            return False
        try:
            subs_espanol = pysubs2.load(sub_espanol_path)
        except Exception as e:
            self._emit_log(f"Error crítico al cargar el subtítulo en Español desde {sub_espanol_path}: {e}")
            return False

        progress_base = 55 
        self._emit_current_file_progress(progress_base)
        subs_espanol = self._eliminar_creditos(subs_espanol)
        progress_base += 5 # 60%

        if subs_fuente_honorificos:
            self._emit_log(f"Procesando honoríficos usando: {os.path.basename(path_fuente_usado)} ({source_lang_name})")

            def buscar_linea_espanol(inicio_fuente, texto_fuente, subs_espanol_local, rango):
                rango_ms = rango * 1000; mejor_linea = None; mejor_puntaje = 0
                for linea_esp in subs_espanol_local:
                    diferencia = abs(linea_esp.start - inicio_fuente)
                    if diferencia <= rango_ms:
                        puntaje = 1.0 / (diferencia + 1)
                        if any(nombre in linea_esp.text for nombre in re.findall(r"\b[A-Za-zÀ-ÖØ-öø-ÿ]+\b", texto_fuente)): puntaje += 1.0
                        if puntaje > mejor_puntaje: mejor_linea = linea_esp; mejor_puntaje = puntaje
                return mejor_linea

            def detectar_duplicados_honorificos(texto):
                for honorifico_item_dup in honorificos:
                    patron = re.compile(rf"({re.escape(honorifico_item_dup)}){{2,}}")
                    while patron.search(texto): texto = patron.sub(honorifico_item_dup, texto)
                return texto

            num_lineas_fuente = len(subs_fuente_honorificos)
            if num_lineas_fuente > 0:
                for i, linea_fuente in enumerate(subs_fuente_honorificos):
                    processed_names = set()
                    found_honorifics_in_line = []
                    for honorifico_item_loop in honorificos:
                        patron = re.compile(rf"([A-Za-zÀ-ÖØ-öø-ÿ]+){re.escape(honorifico_item_loop)}(?:[!?\\.]*)", re.IGNORECASE)
                        coincidencias = patron.findall(linea_fuente.text)
                        if coincidencias:
                            for nombre_sin_honorifico in coincidencias:
                                if nombre_sin_honorifico.lower() not in processed_names:
                                    nombre_con_honorifico = f"{nombre_sin_honorifico}{honorifico_item_loop}"
                                    found_honorifics_in_line.append((nombre_sin_honorifico, nombre_con_honorifico, honorifico_item_loop))
                                    processed_names.add(nombre_sin_honorifico.lower())
                    
                    if found_honorifics_in_line:
                        linea_espanol_target = buscar_linea_espanol(linea_fuente.start, linea_fuente.text, subs_espanol, rango_segundos)
                        if linea_espanol_target:
                            original_spanish_text = linea_espanol_target.text
                            modified_spanish_text = original_spanish_text
                            redundantes_unicas = sorted({palabra.lower() for palabra in palabras_redundantes}, key=len, reverse=True)
                            for palabra in redundantes_unicas:
                                modified_spanish_text = re.sub(rf"(?i)\b{re.escape(palabra)}\b\s*", "", modified_spanish_text)

                            for nombre_sin_honorifico, nombre_con_honorifico, honorifico_val in found_honorifics_in_line:
                                if not re.search(rf"(?i)\b{re.escape(nombre_sin_honorifico)}{re.escape(honorifico_val)}\b", modified_spanish_text):
                                    modified_spanish_text = re.sub(
                                        rf"(?i)\b{re.escape(nombre_sin_honorifico)}\b(?!\W*{re.escape(honorifico_val)})",
                                        nombre_con_honorifico, modified_spanish_text, count=1 )
                            linea_espanol_target.text = detectar_duplicados_honorificos(
                                re.sub(r"\s{2,}", " ", modified_spanish_text).strip() )
                    
                    if i > 0 and i % 50 == 0 :
                        self._emit_current_file_progress(progress_base + int((i / num_lineas_fuente) * 20)) 
            progress_base = 80
        else:
            self._emit_log("No hay fuente de honoríficos (Inglés/Malayo) disponible. Solo se limpiarán créditos.")
            progress_base = 80

        self._emit_current_file_progress(progress_base)

        if GEMINI_API_KEY and GEMINI_API_KEY != "TU_API_KEY_DE_GEMINI_AQUI":
            try:
                subs_espanol = self._invertir_nombres_via_gemini(subs_espanol)
                progress_base = 90 
                self._emit_current_file_progress(progress_base)
            except Exception as e_gemini:
                self._emit_log(f"Error durante la inversión de nombres con Gemini: {e_gemini}")
        else:
            self._emit_log("API Key de Gemini no configurada, omitiendo inversión de nombres.")
            progress_base = 90 
        
        self._emit_current_file_progress(90) 
        try:
            subs_espanol.save(output_path)
            self._emit_log(f"Subtítulo en español modificado guardado en: {output_path}")
            self._emit_current_file_progress(100)
            return True
        except Exception as e:
            self._emit_log(f"Error guardando subtítulo modificado en Español: {e}")
            return False

    def _cleanup_temp_subs(self):
        for temp_sub_path_attr in ['temp_sub_ingles', 'temp_sub_espanol', 'temp_sub_malayo']:
            temp_sub_path = getattr(self, temp_sub_path_attr, None)
            if temp_sub_path and os.path.isfile(temp_sub_path):
                try:
                    os.remove(temp_sub_path)
                    self._emit_log(f"Archivo temporal eliminado: {temp_sub_path}")
                except OSError as e:
                    self._emit_log(f"Error eliminando archivo temporal {temp_sub_path}: {e}")
            setattr(self, temp_sub_path_attr, None)

    def _procesar_archivo_mkv_multisubs(self, mkv_file):
        self._emit_log(f"Modo: Multi-subs para {os.path.basename(mkv_file)}")
        self._emit_current_file_progress(5)
        base_name = os.path.splitext(os.path.basename(mkv_file))[0]
        dir_name = os.path.dirname(mkv_file)
        external_sub_path_ass = os.path.join(dir_name, f"{base_name}.ass")
        external_sub_path_srt = os.path.join(dir_name, f"{base_name}.srt")
        original_sub_espanol_path = os.path.join(dir_name, f"{base_name}_original.ass")
        output_path = os.path.join(dir_name, f"{base_name}.ass")
        sub_espanol_path_for_process = None
        using_external_sub = False
        self._cleanup_temp_subs()

        try:
            if os.path.isfile(external_sub_path_ass):
                os.replace(external_sub_path_ass, original_sub_espanol_path)
                sub_espanol_path_for_process = original_sub_espanol_path; using_external_sub = True
            elif os.path.isfile(external_sub_path_srt):
                os.replace(external_sub_path_srt, original_sub_espanol_path)
                sub_espanol_path_for_process = original_sub_espanol_path; using_external_sub = True
        except OSError as e: self._emit_log(f"Error al renombrar subtítulo externo: {e}.")

        extracted_eng, extracted_spa, extracted_may = self._extract_subtitles_metadata(mkv_file)
        self.temp_sub_ingles = extracted_eng
        self.temp_sub_malayo = extracted_may

        if not sub_espanol_path_for_process: 
            if extracted_spa:
                self.temp_sub_espanol = extracted_spa 
                sub_espanol_path_for_process = extracted_spa
                self._emit_log("Usando subtítulo en Español extraído del MKV.")
            else:
                self._emit_log("No se encontraron subtítulos en español. No se puede procesar."); self._cleanup_temp_subs(); return
        else: self._emit_log(f"Usando subtítulo en Español externo: {original_sub_espanol_path}")
        
        success = self._reemplazar_honorificos(self.temp_sub_ingles, sub_espanol_path_for_process, self.temp_sub_malayo, output_path)
        if success:
            self._emit_log(f"Proceso completado para {base_name}.mkv.")
            if using_external_sub: self._emit_log(f"Subtítulo original respaldado: {original_sub_espanol_path}")
        else: self._emit_log(f"Falló el proceso para {base_name}.mkv.")
        self._cleanup_temp_subs()

    def _procesar_archivo_mkv_extrasub(self, mkv_file):
        self._emit_log(f"Modo: Extra-sub para {os.path.basename(mkv_file)}")
        self._emit_current_file_progress(5)
        base_name = os.path.splitext(os.path.basename(mkv_file))[0]
        dir_name = os.path.dirname(mkv_file)
        sub_espanol_path_external_ass = os.path.join(dir_name, f"{base_name}.ass")
        sub_espanol_path_external_srt = os.path.join(dir_name, f"{base_name}.srt")
        original_sub_espanol_path = os.path.join(dir_name, f"{base_name}_original.ass")
        output_path = os.path.join(dir_name, f"{base_name}.ass")
        sub_espanol_path_for_process = None
        self._cleanup_temp_subs()

        try:
            if os.path.isfile(sub_espanol_path_external_ass):
                os.replace(sub_espanol_path_external_ass, original_sub_espanol_path)
                sub_espanol_path_for_process = original_sub_espanol_path
            elif os.path.isfile(sub_espanol_path_external_srt):
                os.replace(sub_espanol_path_external_srt, original_sub_espanol_path)
                sub_espanol_path_for_process = original_sub_espanol_path
            else: self._emit_log(f"No se encontró subtítulo externo {base_name}.ass/srt."); return
        except OSError as e: self._emit_log(f"Error al renombrar subtítulo externo: {e}."); return

        extracted_eng, _, extracted_may = self._extract_subtitles_metadata(mkv_file)
        self.temp_sub_ingles = extracted_eng
        self.temp_sub_malayo = extracted_may
        
        if sub_espanol_path_for_process: 
            success = self._reemplazar_honorificos(self.temp_sub_ingles, sub_espanol_path_for_process, self.temp_sub_malayo, output_path)
            if success:
                self._emit_log(f"Proceso completado para {base_name}.mkv.")
                self._emit_log(f"Subtítulo original respaldado: {original_sub_espanol_path}")
            else: self._emit_log(f"Falló el proceso para {base_name}.mkv.")
        else: self._emit_log("Error: no hay subtítulo en español para procesar.")
        self._cleanup_temp_subs()

    def run(self):
        total_files = len(self.files)
        for i, file_path in enumerate(self.files):
            self.current_file_num = i + 1
            self.current_file_total = total_files
            if not (file_path and os.path.isfile(file_path) and file_path.endswith('.mkv')):
                self._emit_log(f"Archivo no válido, omitiendo: {file_path}")
                self.overall_progress_updated.emit(int(((i + 1) / total_files) * 100))
                continue
            base_name = os.path.splitext(os.path.basename(file_path))[0]
            self.current_file_name_for_label = f"{base_name}.mkv"
            self.current_file_changed.emit(f"Procesando: {self.current_file_name_for_label}")
            self._emit_current_file_progress(0)
            if self.mode == 'multi': self._procesar_archivo_mkv_multisubs(file_path)
            else: self._procesar_archivo_mkv_extrasub(file_path)
            self._emit_current_file_progress(100) 
            self.overall_progress_updated.emit(int(((i + 1) / total_files) * 100))
            self._emit_log(f"Procesamiento de {base_name}.mkv completado.")
        self.processing_finished_signal.emit()

class DragAndDropWindow(QtWidgets.QWidget):
    def __init__(self, mode):
        super().__init__(); self.mode = mode; self.thread = None
        self.files_to_process_list = []; self.current_file_name_display = ""
        self.current_file_num_display = 0; self.total_files_display = 0
        self.initUI()
    def initUI(self):
        self.setWindowTitle(f'Weebanizador - Modo: {"Multi-Sub" if self.mode == "multi" else "Extra-Sub"}')
        self.setGeometry(100, 100, 450, 250) 
        self.setStyleSheet("QWidget{background-color:#F0F0F0}QLabel#dropAreaLabel{border:2px dashed #4CAF50;border-radius:8px;padding:20px;color:#4CAF50;font-size:12px;min-height:60px;word-wrap:break-word}QLabel#dropAreaLabel:hover{border-color:#45a049;color:#45a049}QPushButton{background-color:#4CAF50;color:white;padding:8px 16px;border-radius:4px;font-size:14px;min-width:150px}QPushButton:hover{background-color:#45a049}QProgressBar{text-align:center}")
        self.setAcceptDrops(True); main_layout = QtWidgets.QVBoxLayout()
        self.drop_area = QtWidgets.QLabel(); self.drop_area.setObjectName("dropAreaLabel") 
        self.drop_area.setAlignment(QtCore.Qt.AlignCenter); self.drop_area.setText('Suelta tus archivos .MKV aquí')
        main_layout.addWidget(self.drop_area)
        self.progress_bar = QtWidgets.QProgressBar(); self.progress_bar.setVisible(False)
        main_layout.addWidget(self.progress_bar)
        button_layout = QtWidgets.QHBoxLayout(); self.cancel_button = QtWidgets.QPushButton('Cerrar')
        self.cancel_button.clicked.connect(self.close); button_layout.addWidget(self.cancel_button)
        main_layout.addLayout(button_layout); self.setLayout(main_layout)
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls(): self.drop_area.setStyleSheet("border:2px dashed #45a049;border-radius:8px;padding:20px;color:#45a049;font-size:12px"); event.acceptProposedAction()
        else: event.ignore()
    def dragLeaveEvent(self, event): self.drop_area.setStyleSheet("border:2px dashed #4CAF50;border-radius:8px;padding:20px;color:#4CAF50;font-size:12px")
    def dropEvent(self, event):
        self.drop_area.setStyleSheet("border:2px dashed #4CAF50;border-radius:8px;padding:20px;color:#4CAF50;font-size:12px")
        mimeData = event.mimeData()
        if mimeData.hasUrls():
            self.files_to_process_list = [url.toLocalFile() for url in mimeData.urls() if url.toLocalFile().lower().endswith('.mkv')]
            if self.files_to_process_list:
                self.total_files_display=len(self.files_to_process_list);self.progress_bar.setValue(0);self.progress_bar.setVisible(True)
                self.drop_area.setText(f"Iniciando lote de {self.total_files_display} archivo(s)...");self.setAcceptDrops(False);self.cancel_button.setEnabled(False)
                self.thread=ProcessingThread(self.files_to_process_list,self.mode)
                self.thread.overall_progress_updated.connect(self.update_overall_progress)
                self.thread.current_file_changed.connect(self.update_current_file_label_text)
                self.thread.current_file_progress_updated.connect(self.update_current_file_progress_in_label)
                self.thread.log_message.connect(self.log_message_received)
                self.thread.processing_finished_signal.connect(self.on_batch_processing_finished)
                self.thread.finished.connect(self.thread.deleteLater);self.thread.start()
            else: QtWidgets.QMessageBox.warning(self,'Error','No se seleccionaron archivos .MKV válidos.');self.drop_area.setText('Suelta tus archivos .MKV aquí')
        event.acceptProposedAction()
    def update_overall_progress(self,value): self.progress_bar.setValue(value)
    def update_current_file_label_text(self,filename_message):
        self.current_file_name_display=filename_message.split(":",1)[1].strip() if ":" in filename_message else "desconocido"
        if self.thread:self.current_file_num_display=self.thread.current_file_num
        self.drop_area.setText(f"Archivo {self.current_file_num_display}/{self.total_files_display}: {filename_message} (0%)")
    def update_current_file_progress_in_label(self,progress_value):
        base_text = f"Archivo {self.current_file_num_display}/{self.total_files_display}: Procesando: {self.current_file_name_display}"
        self.drop_area.setText(f"{base_text} ({progress_value}%)")
    def log_message_received(self,message): print(message) 
    def on_batch_processing_finished(self):
        self.drop_area.setText(f"¡Lote completado! ({self.total_files_display} archivo(s) procesados)");self.progress_bar.setValue(100)
        self.setAcceptDrops(True);self.cancel_button.setEnabled(True);QtCore.QTimer.singleShot(3000,self.close)

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self): super().__init__(); self.drag_window_instance = None; self.initUI()
    def initUI(self):
        self.setWindowTitle('Weebanizador'); self.setGeometry(100,100,400,200)
        self.setStyleSheet("QMainWindow{background-color:#F0F0F0}QPushButton{background-color:#4CAF50;color:white;padding:8px 16px;border-radius:4px;font-size:14px;min-width:150px}QPushButton:hover{background-color:#45a049}")
        central_widget=QtWidgets.QWidget();self.setCentralWidget(central_widget)
        layout=QtWidgets.QVBoxLayout();layout.setContentsMargins(20,20,20,20);layout.setSpacing(15)
        multi_subs_button=QtWidgets.QPushButton('Modo Multi-Sub');multi_subs_button.clicked.connect(lambda:self.open_drag_drop_window('multi'))
        layout.addWidget(multi_subs_button)
        extra_sub_button=QtWidgets.QPushButton('Modo Extra-Sub');extra_sub_button.clicked.connect(lambda:self.open_drag_drop_window('extra'))
        layout.addWidget(extra_sub_button)
        central_widget.setLayout(layout);self.setMinimumSize(400,200)
    def open_drag_drop_window(self,mode):
        if self.drag_window_instance is None or not self.drag_window_instance.isVisible():
            self.drag_window_instance=DragAndDropWindow(mode);self.drag_window_instance.show()
        else:self.drag_window_instance.activateWindow()

if __name__ == "__main__":
    import sys
    if not GEMINI_API_KEY or GEMINI_API_KEY == "TU_API_KEY_DE_GEMINI_AQUI":
        print("ADVERTENCIA: API Key de Gemini no configurada. La inversión de Nombre-Apellido será omitida.")
        print("Edita Weebnizador.py y reemplaza 'TU_API_KEY_DE_GEMINI_AQUI'.")
    app = QtWidgets.QApplication(sys.argv)
    main_window = MainWindow()
    main_window.show()
    sys.exit(app.exec_())