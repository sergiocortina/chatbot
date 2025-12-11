import streamlit as st
import pandas as pd
import os
import json
import io
import requests 
import re 
import time # Necesario para la simulación de tecleo (streaming)
from fpdf import FPDF 

try:
    from unidecode import unidecode 
except ImportError:
    def unidecode(text):
        return text
    st.warning("Advertencia: La librería 'unidecode' no está disponible. La búsqueda de actividades por área podría ser menos precisa.")
    
# Importar librerías críticas para RAG.
try:
    import pypdf # Librería para leer PDFs
except ImportError:
    pypdf = None

# --- CONFIGURACIÓN GENERAL ---
st.set_page_config(page_title="Asesor Progob PBR/MML Veracruz", layout="wide")

# Nombres de archivo y directorios
USERS_FILE_NAME = "users.xlsx" 
DOCS_DIR = "docs"
ACTIVIDADES_FILE = os.path.join(DOCS_DIR, "Actividades por area.csv") 
REGLAMENTO_FILE = os.path.join(DOCS_DIR, "REGLAMENTO-INTERIOR-DE-LA-ADMINISTRACION-PUBLICA-DEL-MUNICIPIO-DE-VERACRUZ.pdf") 

# NUEVOS DOCUMENTOS DE ALINEAMIENTO ESTRATÉGICO
GUIDE_FILE = os.path.join(DOCS_DIR, "Modulo7_PbR (IA).pdf") 
GDM_FILE = os.path.join(DOCS_DIR, "Cuaderno de trabajo GDM 2025-2027.pdf")
ODS_FILE = os.path.join(DOCS_DIR, "Indicadores por Objetivo y Meta de los Objetivos de Desarrollo Sostenible.pdf")
MANUAL_INDICADORES_FILE = os.path.join(DOCS_DIR, "Manual_de_indicadores_para_municipios 20250415.pdf")

# CLAVE API: Se leerá de st.secrets["deepseek_api_key"]


# --- DEFINICIÓN DEL PROMPT MAESTRO (PERSONALIDAD DE PROGOB) ---

SYSTEM_PROMPT = """
# ROL DE ASESOR SENIOR DE PROGOB
**ROL:** Eres el **Enlace Senior de la Oficina de Programa de Gobierno y Mejora Regulatoria (Progob)** del H. Ayuntamiento de Veracruz 2022-2025. Eres un experto en **Gestión para Resultados (GpR)** y **Metodología de Marco Lógico (MML)**, actuando como el **asesor metodológico** del proceso de planeación.

**META:** Guiar al Enlace de Unidad Responsable (UR) paso a paso para construir una Matriz de Indicadores para Resultados (MIR) coherente, utilizando su contexto de área y asegurando la validación explícita de cada etapa por parte del usuario.

**REGLAS DE INTERACCIÓN (CHAT):**
1.  **Micro-Fases y Validación:** La conversación se basa en micro-fases didácticas. **No permitas avanzar a la siguiente etapa de la MIR (Problema final, Propósito final, Componentes finales) hasta que el usuario haya validado o confirmado el enunciado propuesto o ajustado.**
2.  **Validación Metodológica:** Cada respuesta que avance o valide un concepto debe incluir una explicación didáctica del concepto (ej. Lógica Vertical, RMAE-T) y, si es posible, opciones de redacción para que el usuario elija o proponga una propia.
3.  **Contexto Específico (RAG):** Usa las atribuciones y actividades de la Unidad Responsable del usuario ({user_area_context}) para contextualizar las propuestas y validaciones.
4.  **Alineación Estratégica:** En cada fase, asegúrate de que las propuestas estén alineadas con la **Ley Orgánica**, los **ODS** y los indicadores del **GDM/Manual de Indicadores** cargados en el contexto (RAG).
5.  **Formato:** Usa Markdown y Tablas para claridad y estructura.
6.  **Lenguaje Didáctico:** Siempre que introduzcas un concepto nuevo (ej. Causa Directa, Indicador RMAE-T, Lógica Vertical), **proporciona una breve explicación didáctica y un ejemplo práctico relacionado con un servicio público**, asumiendo que el usuario no es experto en metodología.
7.  **Lenguaje Progob:** Utiliza frases como "Consultando la base de conocimiento...", "Revisando el Reglamento Interior...", "Preguntando a Progob...", o "Según la Guía Técnica...". **Nunca menciones "Deepseek", "LLM" o "Modelo de Lenguaje".**
"""

# --------------------------------------------------------------------------
# A. FUNCIONES CENTRALES (Carga de Usuarios y Contexto)
# --------------------------------------------------------------------------

def load_users():
    """Carga el listado de usuarios, priorizando users.xlsx o secrets.toml."""
    # ... (Función load_users se mantiene igual) ...
    possible_names = [USERS_FILE_NAME, "users.csv", "usuarios.xlsx", "usuarios.csv"]
    found_file = None
    for name in possible_names:
        if os.path.exists(name.lower()):
            found_file = name.lower()
            break
        if os.path.exists(name):
             found_file = name
             break
    
    if found_file:
        try:
            if found_file.endswith(('.xlsx', '.xls')):
                 df = pd.read_excel(found_file, engine='openpyxl')
            else:
                try:
                    df = pd.read_csv(found_file, encoding='utf-8')
                    if len(df.columns) == 1: 
                        df = pd.read_csv(found_file, sep=';', encoding='utf-8')
                except:
                    df = pd.read_csv(found_file, sep=';', encoding='latin1')
                 
        except Exception as e:
            st.error(f"❌ Error al procesar el archivo '{found_file}'. Revise el formato. Error: {e}")
            return pd.DataFrame()

        try:
            df.columns = df.columns.astype(str).str.strip().str.lower()
        except Exception as e:
            st.error(f"❌ Error al normalizar nombres de columna: {e}. Asegúrese de que el archivo tenga encabezados válidos.")
            return pd.DataFrame()
        
        return df
    
    # Si no encuentra archivo local, intenta leer de secrets.toml
    try:
        if 'users' in st.secrets:
            df_secrets = pd.DataFrame({
                'username': st.secrets['users']['username'],
                'password': st.secrets['users']['password'],
                'role': st.secrets['users']['role'],
                'area': st.secrets['users']['area'],
                'nombre': st.secrets['users'].get('nombre', [f"Usuario {i+1}" for i in range(len(st.secrets['users']['username']))]) 
            })
            df_secrets.columns = df_secrets.columns.str.lower()
            return df_secrets
    except Exception as e:
        pass
        
    return pd.DataFrame() 

def authenticate(username, password, df_users):
    """Verifica credenciales y devuelve el rol, nombre y área del usuario."""
    # ... (Función authenticate se mantiene igual) ...
    clean_username = username.strip().lower()
    user = df_users[(df_users['username'] == clean_username) & (df_users['password'] == password)]
    
    if not user.empty:
        role = str(user['role'].iloc[0]).strip().lower() if 'role' in user.columns else 'enlace' 
        name = str(user['nombre'].iloc[0]).strip() if 'nombre' in user.columns else 'Usuario'
        area = str(user['area'].iloc[0]).strip() if 'area' in user.columns else 'Sin Área'
        return role, name, area
    return None, None, None


def extract_text_from_pdf(pdf_path):
    """Extrae texto de un archivo PDF si pypdf está instalado."""
    if not pypdf:
        return "ERROR: Librería 'pypdf' no instalada."
    if not os.path.exists(pdf_path):
        return f"ERROR: Archivo no encontrado en {pdf_path}"
        
    try:
        reader = pypdf.PdfReader(pdf_path)
        text = ""
        for page in reader.pages:
            text += page.extract_text() or ""
        return text # Devolvemos el texto completo para el RAG
    except Exception as e:
        return f"ERROR al leer el PDF: {e}"


def load_area_context(user_area):
    """
    Carga el contexto específico del área del usuario, leyendo PDF y CSV (RAG).
    Ajustado para cargar múltiples documentos y generar resúmenes legibles.
    """
    context = {
        "atribuciones": "Contexto no cargado.", 
        "atribuciones_resumen": "No disponible.",
        "actividades_previas": "No disponibles.", 
        "actividades_resumen": "No disponibles.",
        "guia_metodologica": "Guía no cargada.",
        "guia_resumen": "No disponible.",
        # Nuevas claves de contexto (se guardan para la bienvenida y RAG)
        "ods_content": "", "ods_resumen": "No cargado.",
        "gdm_content": "", "gdm_resumen": "No cargado.",
        "manual_ind_content": "", "manual_ind_resumen": "No cargado.",
    }

    # --- 1. CARGA DE ATRIBUCIONES (REGLAMENTO PDF) ---
    reglamento_text = extract_text_from_pdf(REGLAMENTO_FILE)
    
    if "ERROR" in reglamento_text:
        context["atribuciones"] = f"ADVERTENCIA (Reglamento): {reglamento_text}"
        context["atribuciones_resumen"] = f"ADVERTENCIA: Error al cargar el Reglamento. ({reglamento_text})"
    else:
        context["atribuciones"] = reglamento_text
        # Intento simplificado para encontrar la sección de atribuciones de la UR
        search_key = user_area.strip().upper()
        # Busca un patrón típico de atribuciones (Artículos, Secciones, Títulos)
        # Se usará un LLM o una búsqueda heurística más simple en un entorno real. Aquí usamos una heurística.
        match = re.search(r'(TÍTULO|CAPÍTULO|ARTÍCULO)\s+.*' + re.escape(search_key) + r'.*?(ARTÍCULO|CAPÍTULO|TÍTULO|REFORMADO)', reglamento_text, re.DOTALL | re.IGNORECASE)
        
        if match:
             # Si encuentra un fragmento específico, lo resume.
             fragment = match.group(0)
             context["atribuciones_resumen"] = f"Fragmento Clave encontrado (Art. o Cap.): {fragment[:250].strip()}..."
        else:
             # Validación general si no encuentra un artículo específico.
             context["atribuciones_resumen"] = f"Reglamento Interior cargado. El asesor lo usará para validar su competencia legal y alineación a la Ley Orgánica."
        
        st.session_state['reglamento_content'] = reglamento_text 
        
    # --- 2. CARGA DE GUÍA METODOLÓGICA (PDF) ---
    guia_text = extract_text_from_pdf(GUIDE_FILE)
    if "ERROR" not in guia_text:
        context["guia_metodologica"] = guia_text 
        context["guia_resumen"] = f"Guía Metodológica de PbR/MML cargada."
        st.session_state['guia_content'] = guia_text 

    # --- 3. CARGA DE DOCUMENTOS ESTRATÉGICOS (RAG) ---
    docs_to_load = {
        "ods": (ODS_FILE, "Objetivos de Desarrollo Sostenible (ODS)"),
        "gdm": (GDM_FILE, "Cuaderno de Trabajo Guía Desempeño Municipal (GDM)"),
        "manual_ind": (MANUAL_INDICADORES_FILE, "Manual de Indicadores para Municipios")
    }
    
    for key, (path, name) in docs_to_load.items():
        content = extract_text_from_pdf(path)
        if "ERROR" not in content:
            context[f"{key}_content"] = content
            context[f"{key}_resumen"] = f"Documento de {name} cargado ({len(content)} caracteres)."
            st.session_state[f"{key}_content"] = content
        else:
             context[f"{key}_resumen"] = f"ADVERTENCIA: {name} no encontrado o con error."

    # --- 4. CARGA DE ACTIVIDADES PREVIAS (CSV) ---
    if os.path.exists(ACTIVIDADES_FILE):
        try:
            df_actividades = pd.read_csv(ACTIVIDADES_FILE, encoding='utf-8')
            # ... (Lógica de filtrado y resumen de actividades) ...
            df_actividades.columns = df_actividades.columns.str.lower()
            
            if 'area' in df_actividades.columns and 'actividad' in df_actividades.columns:
                clean_user_area_norm = unidecode(user_area.strip()).replace('.', '').upper()
                area_keys = [clean_user_area_norm]
                if "SIPINNA" in clean_user_area_norm:
                     area_keys.append('SIPINNA')
                
                filtered_df = df_actividades[
                    df_actividades['area'].astype(str).str.upper().apply(
                        lambda x: any(key in unidecode(x) for key in area_keys)
                    )
                ]
                
                if not filtered_df.empty:
                    # Almacenamos el contenido completo para el RAG
                    actividades_list = filtered_df['actividad'].tolist()
                    context["actividades_previas"] = "\n* " + "\n* ".join(actividades_list)
                    st.session_state['actividades_content'] = context["actividades_previas"] # Para RAG completo

                    # Resumen para la bienvenida
                    top_activities = "\n".join([f"* {a}" for a in actividades_list]) # Listamos TODAS para el inicio
                    context["actividades_resumen"] = f"Se encontraron **{len(actividades_list)} actividades** previas. Listado Completo:\n{top_activities}"

                else:
                    context["actividades_resumen"] = f"ADVERTENCIA: No se encontraron actividades previas para la UR '{user_area}'."
            else:
                context["actividades_resumen"] = f"ADVERTENCIA: Archivo de actividades cargado, pero faltan columnas 'area' o 'actividad'."

        except Exception as e:
            context["actividades_resumen"] = f"Error al procesar el archivo de actividades: {e}"
    else:
        context["actividades_resumen"] = f"ADVERTENCIA: Archivo de actividades no encontrado."


    return context


def get_llm_response(system_prompt: str, user_query: str):
    """
    Función de conexión a la API, leyendo la clave **SÓLO** desde st.secrets e inyectando contexto RAG.
    Devuelve la respuesta como un generador de texto para el streaming.
    """
    try:
        # Lectura exclusiva de la clave desde Streamlit Secrets
        api_key = st.secrets["deepseek_api_key"]
    except KeyError:
        return iter(["❌ Conexión fallida. Por favor, verifica tu clave API."])
    
    # --- INYECCIÓN RAG CRÍTICA (Añadimos los nuevos contenidos) ---
    rag_context = ""
    if 'reglamento_content' in st.session_state: rag_context += f"\n\n--- CONTEXTO RAG (REGLAMENTO INTERIOR) ---\n{st.session_state['reglamento_content']}"
    if 'guia_content' in st.session_state: rag_context += f"\n\n--- CONTEXTO RAG (GUÍA METODOLÓGICA) ---\n{st.session_state['guia_content']}"
    if 'actividades_content' in st.session_state: rag_context += f"\n\n--- CONTEXTO RAG (ACTIVIDADES PREVIAS DEL ÁREA) ---\n{st.session_state['actividades_content']}"
    
    # Nuevos documentos RAG
    if 'ods_content' in st.session_state: rag_context += f"\n\n--- CONTEXTO RAG (ODS) ---\n{st.session_state['ods_content']}"
    if 'gdm_content' in st.session_state: rag_context += f"\n\n--- CONTEXTO RAG (GDM) ---\n{st.session_state['gdm_content']}"
    if 'manual_ind_content' in st.session_state: rag_context += f"\n\n--- CONTEXTO RAG (MANUAL INDICADORES) ---\n{st.session_state['manual_ind_content']}"
    
    # Documentos personalizados
    if 'custom_docs_content' in st.session_state:
        for doc_name, doc_content in st.session_state['custom_docs_content'].items():
            rag_context += f"\n\n--- CONTEXTO RAG (DOCUMENTO PERSONALIZADO: {doc_name}) ---\n{doc_content}"


    final_system_prompt = system_prompt.replace("{user_area_context}", st.session_state['area_context']['atribuciones_resumen'])
    final_system_prompt += rag_context
    # -----------------------------
    
    API_URL = "https://api.deepseek.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    messages = [
        {"role": "system", "content": final_system_prompt},
        {"role": "user", "content": user_query}
    ]
    
    payload = {
        "model": "deepseek-chat", 
        "messages": messages,
        "temperature": 0.3, 
        "max_tokens": 4000
    }
    
    # Usamos la conexión síncrona, pero con manejo de errores más específico.
    try:
        # Nota: quitamos st.spinner de aquí para que Streamlit se sienta más rápido.
        response = requests.post(API_URL, headers=headers, json=payload, timeout=60)
        
        # Manejo específico del error 400
        if response.status_code == 400:
             # Intentamos leer el mensaje de error de Deepseek
             try:
                 error_data = response.json()
                 error_message = error_data.get('error', {}).get('message', 'Solicitud incorrecta (400 Bad Request).')
                 return iter([f"❌ Error en la comunicación con la API. Detalle: {error_message}"])
             except:
                 return iter([f"❌ Error en la comunicación con la API. Detalle: 400 Client Error: Bad Request."])

        response.raise_for_status() # Lanza excepción para otros errores HTTP 4xx/5xx
        
        data = response.json()
        
        if data and 'choices' in data and data['choices']:
            # Devolvemos la respuesta completa como un iterador (generador de palabras)
            full_response = data['choices'][0]['message']['content']
            
            # Generador para simular el tecleo (devuelve fragmentos)
            def stream_generator():
                for char in full_response:
                    yield char
                    time.sleep(0.005) # Pequeña pausa para el efecto visual
            
            return stream_generator()
        else:
            return iter([f"⚠️ Progob no pudo generar una respuesta. (Código: {response.status_code})"])

    except requests.exceptions.RequestException as e:
        # Errores de red o timeout
        return iter([f"❌ Error en la comunicación con la API. Detalle: {e}"])
    except Exception as e:
        # Error interno
        return iter([f"❌ Error interno al procesar la respuesta. Detalle: {e}"])


# --------------------------------------------------------------------------
# B. FUNCIONES DE PERSISTENCIA (LOCAL: DESCARGA/CARGA JSON)
# --------------------------------------------------------------------------

def get_pat_file_name(user_area):
    """Genera el nombre de archivo para guardar el avance del PAT."""
    clean_area = re.sub(r'[^\w\s-]', '', user_area.replace(' ', '_'))
    return f"avance_pat_{clean_area}.json"

def save_pat_progress(user_area, pat_data):
    """
    PERSISTENCIA LOCAL: Genera el botón de descarga del archivo JSON. 
    INCLUYE TODO EL ESTADO DE LA SESIÓN (MENSAJES Y DATOS METODOLÓGICOS).
    """
    file_name = get_pat_file_name(user_area)
    
    # Preparamos el estado completo a guardar
    full_state = {
        "pat_data": pat_data,
        "messages": st.session_state.get('messages', []),
        "current_phase": st.session_state.get('current_phase', 'inicio')
    }
    
    # 1. Convertir datos a JSON y luego a bytes
    pat_json_data = json.dumps(full_state, indent=4, ensure_ascii=False)
    data_to_download = pat_json_data.encode('utf-8')
    
    # 2. Renderizar el botón de descarga en el sidebar
    st.sidebar.download_button(
        label="⬇️ Descargar Avance Completo (.json)",
        data=data_to_download,
        file_name=file_name,
        mime='application/json',
        help="Guarda tu progreso (incluyendo historial de chat y fase actual)."
    )
    
    # 3. Actualizar estado (simulación de guardado exitoso)
    st.session_state['drive_status'] = f"✅ Avance listo para descargar: {file_name}"
    
def generate_pdf_conversation(messages, user_area):
    """Genera un PDF con la transcripción de la conversación, usando codificación UTF-8."""
    
    # FIX FPDF: Eliminamos 'font_directory=None'
    pdf = FPDF(unit="mm", format="A4", orientation="P", encoding='utf-8') 
    
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    
    pdf.set_font("Arial", "B", 16)
    pdf.cell(0, 10, "Transcripción de la Asesoría Progob (MIR)", 0, 1, "C")
    pdf.set_font("Arial", "", 10)
    pdf.cell(0, 5, f"Unidad Responsable: {user_area}", 0, 1, "C")
    pdf.cell(0, 5, f"Fecha de Exportación: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}", 0, 1, "C")
    pdf.ln(5)

    for msg in messages:
        role = msg["role"].upper()
        content = msg["content"]
        
        pdf.set_font("Arial", "B", 10)
        pdf.set_fill_color(200, 220, 255) if role == "ASSISTANT" else pdf.set_fill_color(240, 240, 240)
        role_title = f"--- {role} ---"
        pdf.cell(0, 7, role_title, 0, 1, 'L', 1)
        
        pdf.set_font("Arial", "", 10)
        
        # Limpiamos el contenido de markdown y caracteres que fpdf no maneja bien
        content_clean = content.replace('>', '').replace('*', '').replace('•', '-')
        
        # Usamos .encode('latin1', 'replace') para manejar cualquier caracter que FPDF no pueda, 
        # y luego lo decodificamos de vuelta para pasarlo a multi_cell.
        try:
            pdf.multi_cell(0, 5, content_clean.encode('latin1', 'replace').decode('latin1'))
        except Exception as e:
            pdf.multi_cell(0, 5, "ERROR: Contenido con caracteres no compatibles para PDF.")
            
        pdf.ln(2)

    return pdf.output(dest='S').encode('utf-8') 

def load_pat_progress(user_area):
    """
    PERSISTENCIA LOCAL: Muestra el uploader y carga el JSON si se proporciona.
    RECUPERA EL AVANCE METODOLÓGICO Y EL HISTORIAL DE MENSAJES.
    """
    
    st.sidebar.markdown("---")
    uploaded_file = st.sidebar.file_uploader(
        "⬆️ Cargar Avance de PAT (.json)",
        type=['json'],
        key="pat_file_uploader",
        help="Sube el archivo JSON de avance guardado previamente."
    )
    
    # Definición del estado inicial vacío
    empty_state = {
        "problema": None, "problema_borrador": None,
        "proposito": None, "proposito_borrador": None,
        "componentes_final": None, "componentes_borrador": None,
        "componentes_actividades": []
    }

    if uploaded_file is not None:
        try:
            bytes_data = uploaded_file.getvalue()
            full_state = json.loads(bytes_data.decode('utf-8'))
            
            # Validar y cargar el avance metodológico
            pat_data = full_state.get('pat_data', empty_state)
            
            # Cargar el historial de mensajes
            messages = full_state.get('messages', [])
            
            if not pat_data or pat_data.get('problema') is None and not messages:
                 st.sidebar.error("❌ El archivo JSON está vacío o es inválido.")
                 return empty_state, []
                 
            # Si la carga es exitosa, restauramos los mensajes y la fase actual en la sesión
            st.session_state['messages'] = messages
            st.session_state['current_phase'] = full_state.get('current_phase', 'inicio')
            
            st.session_state['drive_status'] = f"✅ Avance '{uploaded_file.name}' cargado exitosamente."
            return pat_data, messages
            
        except Exception as e:
            st.sidebar.error(f"❌ Error al cargar el archivo: {e}")
            return empty_state, []
    
    st.session_state['drive_status'] = "⚠️ Persistencia: Esperando que cargue un avance o inicie un nuevo PAT."
    # Si no hay archivo subido, retorna el estado vacío y una lista de mensajes vacía
    return empty_state, []


# --------------------------------------------------------------------------
# Z. LÓGICA DE FASES (Maneja el flujo secuencial y didáctico)
# --------------------------------------------------------------------------

def handle_phase_logic(user_prompt: str, user_area: str):
    """Maneja la lógica de avance por fases, haciendo hincapié en la validación."""
    
    current_phase = st.session_state.current_phase
    
    # La respuesta ya no es un string, sino un generador (iterable)
    response_generator = None 
    
    # Contexto RAG para simplificar los prompts internos. Usamos el resumen de atribuciones.
    system_context_rag = f"Contexto de la UR ({user_area}): {st.session_state.area_context['atribuciones_resumen']}. Actividades: {st.session_state.area_context['actividades_resumen']}"
    
    # ----------------------------------------------------------------------
    # FASE 1: DIAGNÓSTICO (PROBLEMA CENTRAL) - DEFINICIÓN/PROPUESTA INICIAL
    # ----------------------------------------------------------------------
    if current_phase == 'Diagnostico_Problema_Definicion':
        # 1. Guarda la propuesta del usuario como borrador
        st.session_state.pat_data['problema_borrador'] = user_prompt
        
        # Prompt basado en la Guía Metodológica para validación (Módulo 7)
        query_llm = f"""
        **FASE ACTUAL: Problema (Propuesta).** {system_context_rag}
        El usuario propone el Problema Central: "{user_prompt}".
        
        Como Enlace Senior de Progob: 
        1.  **Explica didácticamente** qué es el Problema Central y su estructura (población + situación no deseada).
        2.  Usando el Reglamento Interior (RAG), **valida brevemente** si el problema está dentro de las atribuciones de la UR.
        3.  Usando la Guía Metodológica (RAG), evalúa el enunciado. Si la redacción del usuario es correcta, **confirma que es una redacción válida y ajusta la sintaxis si es necesario**. Si el enunciado incumple reglas (es ausencia de servicio, o incluye soluciones), propón una redacción ajustada (Opción A, B).
        4.  **Pregunta al usuario** si está de acuerdo con la validación y la redacción final, o si desea modificarla. **IMPORTANTE: El Problema Central definitivo DEBE ser copiado y pegado o redactado por el usuario en su próxima respuesta.**
        5.  Instrucción de Respuesta: Responde con la redacción completa elegida o propuesta. **NO AVANCES A CAUSAS/EFECTOS.**
        """
        response_generator = get_llm_response(SYSTEM_PROMPT, query_llm)
        st.session_state.current_phase = 'Diagnostico_Problema_Validacion'
        
    # ----------------------------------------------------------------------
    # FASE 2: PROBLEMA CENTRAL - VALIDACIÓN FINAL Y GENERACIÓN DE ÁRBOL
    # ----------------------------------------------------------------------
    elif current_phase == 'Diagnostico_Problema_Validacion':
        
        # Si llegamos aquí, asumimos que el usuario proporcionó la redacción completa o la corrigió.
        st.session_state.pat_data['problema'] = user_prompt
            
        # Pasamos a la siguiente fase real de generación de árbol
        query_llm = f"""
        **FASE ACTUAL: Problema Central (Confirmado).** {system_context_rag}
        El Problema Central FINAL confirmado es: "{user_prompt}".
        
        Como Enlace Senior de Progob: 
        1.  **Confirma la recepción** del Problema Central definitivo de manera didáctica, citándolo.
        2.  **Explica didácticamente** qué es el Análisis Causal / Árbol de Problemas y la diferencia entre Causas Directas e Indirectas.
        3.  Usando el Problema Central confirmado y la Guía Metodológica (RAG), **genera** 3 Causas Directas y al menos 2 Causas Indirectas por cada una, explorando enfoques diferentes (social, institucional, operativo, etc.). Preséntalos en una tabla estructurada y clara.
        4.  **Pregunta al usuario** si está de acuerdo con la lógica causal del Árbol propuesto (Causas y Efectos) antes de avanzar a la transformación en Propósito/Objetivos. (Ej: Responde 'Acepto el Árbol' o 'Propongo la siguiente modificación a la causa 2...'). **NO AVANCES A PROPÓSITO.**
        """
        response_generator = get_llm_response(SYSTEM_PROMPT, query_llm)
        # TRANSICIÓN A LA FASE: VALIDACIÓN DEL ÁRBOL
        st.session_state.current_phase = 'Diagnostico_Arbol_Validacion'
        
    # ----------------------------------------------------------------------
    # FASE 3: ÁRBOL DE PROBLEMAS - VALIDACIÓN FINAL Y PROPUESTAS DE PROPÓSITO
    # ----------------------------------------------------------------------
    elif current_phase == 'Diagnostico_Arbol_Validacion':
        # El prompt del usuario es la confirmación/corrección del Árbol de Problemas.
        
        problema_final = st.session_state.pat_data.get('problema', 'Problema no definido')
        
        query_llm = f"""
        **FASE ACTUAL: Árbol de Problemas (Confirmado).** {system_context_rag}
        Problema Central: "{problema_final}".
        El usuario ha validado o ajustado el Árbol de Problemas (su última respuesta fue: "{user_prompt}").
        
        Como Enlace Senior de Progob: 
        1.  **Felicita al usuario** por completar el Análisis Causal.
        2.  **Guía al usuario** a la siguiente fase: **Propósito**. Explica que el Propósito es la imagen en positivo del Problema Central (Objetivo General) y la importancia de la Lógica Vertical.
        3.  Usando el Problema Central ("{problema_final}") y las Actividades Previas (RAG), **propón tres opciones de Propósito** que se deriven directamente de la superación del problema validado (Opciones A, B, C). Deben seguir la sintaxis de la MIR (Beneficiario + verbo en presente + resultado).
        4.  Instruye al usuario a seleccionar una opción. **IMPORTANTE: El Propósito definitivo DEBE ser copiado y pegado o redactado por el usuario en su próxima respuesta.**
        5.  Instrucción de Respuesta: Responde con la redacción completa elegida o propuesta.
        """
        response_generator = get_llm_response(SYSTEM_PROMPT, query_llm)
        # TRANSICIÓN A LA FASE: DEFINICIÓN DEL PROPÓSITO
        st.session_state.current_phase = 'Proposito_Definicion'
        
    # ----------------------------------------------------------------------
    # FASE 4: PROPÓSITO - DEFINICIÓN Y VALIDACIÓN METODOLÓGICA
    # ----------------------------------------------------------------------
    elif current_phase == 'Proposito_Definicion':
        # 1. Guarda la propuesta del usuario como borrador
        st.session_state.pat_data['proposito_borrador'] = user_prompt
        problema_final = st.session_state.pat_data.get('problema', 'Problema no definido')
        
        query_llm = f"""
        **FASE ACTUAL: Propósito (Borrador).** {system_context_rag}
        Problema Central (Para validar la coherencia): "{problema_final}".
        El usuario propone el Propósito: "{user_prompt}".
        
        Como Enlace Senior de Progob: 
        1.  **Define brevemente** el Propósito según la MML (RAG).
        2.  **Valida** si el Propósito cumple con la **Lógica Vertical** (ser la solución directa al Problema) y las reglas de sintaxis de la MIR (Beneficiario + verbo en presente + resultado). Si no lo está, **propónle una redacción ajustada** que cumpla el criterio (Opción A, B).
        3.  **Pregunta al usuario** si está de acuerdo con la validación y la redacción final, o si desea modificarla. (Ej: Responde 'Acepto la opción A' o 'Propongo la siguiente corrección...').
        """
        response_generator = get_llm_response(SYSTEM_PROMPT, query_llm)
        st.session_state.current_phase = 'Proposito_Validacion'

    # ----------------------------------------------------------------------
    # FASE 5: PROPÓSITO - CONFIRMACIÓN E INDICADOR RMAE-T
    # ----------------------------------------------------------------------
    elif current_phase == 'Proposito_Validacion':
        # 1. El prompt del usuario es la validación final del propósito
        st.session_state.pat_data['proposito'] = user_prompt
        
        query_llm = f"""
        **FASE ACTUAL: Propósito (Confirmado).** {system_context_rag}
        Propósito FINAL confirmado: "{user_prompt}".
        
        Como Enlace Senior de Progob: 
        1.  **Explica didácticamente** qué es un Indicador RMAE-T (Resultado, Medición, Alcance, Escala, Temporalidad) y por qué los indicadores de Propósito deben ser Estratégicos.
        2.  **Genera** un borrador de Indicador del Propósito (RMAE-T) y el Medio de Verificación.
        3.  **Guía al usuario** a la siguiente fase: **Componentes**. Explica que los Componentes son los productos/servicios que la UR debe entregar (imagen en positivo de las causas directas).
        4.  Pídele al usuario que, basado en sus Actividades Previas (RAG), **liste los 2 o 3 productos/servicios principales** que su área debe entregar para alcanzar ese Propósito.
        """
        response_generator = get_llm_response(SYSTEM_PROMPT, query_llm)
        st.session_state.current_phase = 'Componentes_Definicion'


    # ----------------------------------------------------------------------
    # FASE 6: DEFINICIÓN DE COMPONENTES
    # ----------------------------------------------------------------------
    elif current_phase == 'Componentes_Definicion':
         
         # 1. Guardamos la propuesta de Componentes del usuario como borrador
         st.session_state.pat_data['componentes_borrador'] = user_prompt
         proposito_final = st.session_state.pat_data.get('proposito', 'Propósito no definido')
         
         query_llm = f"""
        **FASE ACTUAL: Componentes (Borrador).** {system_context_rag}
        Propósito (Para validar coherencia): "{proposito_final}".
        El usuario propone Componentes/Productos: "{user_prompt}".
        
        Como Enlace Senior de Progob: 
        1.  **Define brevemente** qué es un Componente según la MML (RAG).
        2.  **Evalúa** la lista del usuario (separa la lista en 2 o 3 elementos) y valida su coherencia con el Propósito (Lógica Vertical).
        3.  Usando la regla de sintaxis de la MIR (Bien / servicio entregado + verbo en pasado participio), **propón** una lista final ajustada.
        4.  **Pregunta al usuario** si está de acuerdo con la lista final o si desea modificarla. (Ej: Responde 'Acepto la lista' o 'Propongo la siguiente lista corregida...').
        """
         response_generator = get_llm_response(SYSTEM_PROMPT, query_llm)
         st.session_state.current_phase = 'Componentes_Validacion'
         
    # ----------------------------------------------------------------------
    # FASE 7: VALIDACIÓN DE COMPONENTES Y CIERRE DE MIR
    # ----------------------------------------------------------------------
    elif current_phase == 'Componentes_Validacion':
        
        # 1. El prompt del usuario es la validación final de los componentes
        # Dividimos la respuesta en una lista de componentes (asumiendo que vienen separados por lista, coma o nueva línea)
        componentes_list = [c.strip() for c in re.split(r'[\n\r\t*•-]', user_prompt) if c.strip()]
        st.session_state.pat_data['componentes_final'] = componentes_list
        
        primer_componente = componentes_list[0] if componentes_list else "Componente no definido"
        
        query_llm = f"""
        **FASE ACTUAL: Componentes (Confirmados).** {system_context_rag}
        Propósito: "{st.session_state.pat_data.get('proposito', 'Propósito no definido')}".
        Componentes FINALES confirmados: "{', '.join(componentes_list)}".
        
        Como Enlace Senior de Progob: 
        1.  **Felicita al usuario** por completar la Lógica Vertical (Fin, Propósito, Componentes).
        2.  **Explica** la fase de **Actividades** (imagen en positivo de las Causas Indirectas).
        3.  Usando la Guía Metodológica (RAG), genera:
            a) Un borrador de Indicador de Gestión (RMAE-T) para el Componente: "{primer_componente}".
            b) Un borrador de Indicador de Gestión para la Actividad (Sustantivo derivado de un verbo + complemento) que se requeriría para producir ese componente.
        4.  Instruye al usuario sobre cómo estos Componentes y Actividades deben pasar al Calendario de Trabajo Anual (PAT) y finalizar la MIR.
        5.  Declara el proceso de la Lógica Vertical como 'COMPLETADO' y recuérdale al usuario la importancia de la **Lógica Horizontal** (Indicadores, Medios de Verificación y Supuestos) para finalizar la MIR.
        """
        response_generator = get_llm_response(SYSTEM_PROMPT, query_llm)
        st.session_state.current_phase = 'Fin_MIR'


    # ----------------------------------------------------------------------
    # FASE CERO: Manejo de Preguntas Conceptuales / Errores
    # ----------------------------------------------------------------------
    else:
        # Lógica para manejar preguntas que no son de avance (si el usuario pide ayuda)
        
        # Mapeo de fases y progreso para dar contexto a la IA
        fase_map = {
            'Diagnostico_Problema_Validacion': f"Validación del Problema: **{st.session_state.pat_data.get('problema_borrador', 'N/A')}**",
            'Diagnostico_Arbol_Validacion': f"Validación del Árbol de Problemas con Problema: **{st.session_state.pat_data.get('problema', 'N/A')}**",
            'Proposito_Validacion': f"Validación del Propósito: **{st.session_state.pat_data.get('proposito_borrador', 'N/A')}**",
            'Componentes_Validacion': f"Validación de Componentes: **{st.session_state.pat_data.get('componentes_borrador', 'N/A')}**"
        }
        
        progreso_actual = fase_map.get(current_phase, "Fase: Inicio")

        query_llm = f"""
        **FASE ACTUAL: {current_phase.replace('_', ' ')}.** {system_context_rag}
        
        El usuario está actualmente en la fase: **{current_phase.replace('_', ' ')}**.
        Progreso Pendiente: {progreso_actual}.
        
        El usuario pregunta o comenta: "{user_prompt}".
        
        Como Enlace Senior de Progob: 
        1.  **Responde directamente** la pregunta conceptual del usuario usando el tono didáctico y el RAG (Reglamento/Guía) si es necesario.
        2.  **NO AVANCES DE FASE.**
        3.  Recuérdale, de manera cortés, el paso pendiente que debe completar para avanzar en la fase **{current_phase.replace('_', ' ')}**.
        """
        response_generator = get_llm_response(SYSTEM_PROMPT, query_llm)
    
    # 2. Obtener el contenido completo del generador
    response_content = "".join(list(response_generator))

    # 3. Guardar avance después de cada paso lógico y actualizar el estado de descarga
    save_pat_progress(user_area, st.session_state.pat_data)
    
    return response_content

# --------------------------------------------------------------------------
# C. VISTA DEL ASESOR (CHAT INTERACTIVO)
# --------------------------------------------------------------------------

def chat_view(user_name, user_area):
    """Nueva interfaz principal basada en chat y flujo secuencial."""
    st.title(f"Asesor Metodológico Progob | {user_area}")
    st.subheader(f"Bienvenido(a), {user_name}.")
    
    # --- 1. Inicializar/Cargar estados ---
    # La función load_pat_progress ahora devuelve pat_data y messages
    if 'pat_data' not in st.session_state:
        st.session_state.pat_data, initial_messages = load_pat_progress(user_area)
        st.session_state.messages = initial_messages
    
    # Determinar la fase actual basado en los datos cargados
    if 'current_phase' not in st.session_state:
        if st.session_state.pat_data.get('proposito'):
            st.session_state.current_phase = 'Componentes_Definicion'
        elif st.session_state.pat_data.get('problema'):
            # Si solo hay problema, lo más probable es que tenga que validar el árbol o definir el propósito.
            st.session_state.current_phase = 'Diagnostico_Arbol_Validacion'
        else:
            st.session_state.current_phase = 'inicio'

    if 'area_context' not in st.session_state:
        # 🌟 CARGA CRÍTICA DEL CONTEXTO (RAG) - USAMOS LOS RESÚMENES AQUÍ
        st.session_state.area_context = load_area_context(user_area)
        
        # Inicializamos el contenedor de documentos personalizados si no existe
        if 'custom_docs_content' not in st.session_state:
            st.session_state['custom_docs_content'] = {}
        
        # Generar el mensaje de bienvenida completo SÓLO si la conversación es nueva
        if not st.session_state.messages or st.session_state.current_phase == 'inicio':
            
            if st.session_state.pat_data.get('problema'):
                 # Mensaje para cargar avance (se mantiene)
                 next_phase_text = st.session_state.current_phase.replace('_', ' ')
                 initial_message = f"""
                 ¡Bienvenido de nuevo, **{user_name}**! Hemos cargado tu avance.

                 * **Problema Confirmado:** *{st.session_state.pat_data.get('problema', 'N/A')}*
                 * **Propósito Confirmado:** *{st.session_state.pat_data.get('proposito', 'N/A')}*
                 
                 Continúa en la fase de **{next_phase_text}**. Ingresa tu siguiente propuesta para avanzar.
                 """
            else:
                 # Mensaje de inicio de PAT vacío (Mensaje de diagnóstico completo)
                 
                 # Nuevo Prompt para generar el Diagnóstico Inicial Detallado (puntos 1-5)
                 initial_query = f"""
                 Genera el mensaje de diagnóstico inicial para la Unidad Responsable '{user_area}'. 
                 Debes cumplir **estrictamente** los siguientes puntos usando el RAG:
                 1.  Identifica y explica el ODS (Objetivo de Desarrollo Sostenible) principal al que debe contribuir la UR, basándote en su área y documentos cargados (ODS).
                 2.  Explica las atribuciones de la UR, citando el Reglamento Interior y la Ley Orgánica (simulada por RAG).
                 3.  Presenta el LISTADO COMPLETO de sus actividades previas (del CSV).
                 4.  Identifica y lista 3 indicadores aplicables del GDM y 3 del Manual de Indicadores para Municipios que debe considerar la UR.
                 5.  Explica brevemente qué es la Metodología de Marco Lógico (MML), que su primer paso es el **Problema Central**, qué es el Problema Central y su estructura, y el por qué usaremos **microfases** (validación obligatoria del usuario).
                 """
                 # Ejecutamos el LLM para obtener el generador de respuesta
                 response_generator = get_llm_response(SYSTEM_PROMPT, initial_query)
                 
                 # Usamos Streamlit para escribir la respuesta en el chat en tiempo real
                 with st.chat_message("assistant"):
                     # El generador devuelve los trozos de la respuesta.
                     full_response_content = st.write_stream(response_generator)
                 
                 # Guardamos la respuesta COMPLETA (ya streameada) en el historial de mensajes
                 st.session_state.messages.append({"role": "assistant", "content": full_response_content})
                 st.session_state.current_phase = 'Diagnostico_Problema_Definicion'
                 # No hacemos rerun aquí, ya que la respuesta se escribió con st.write_stream
                 
                 # Salimos de la función para esperar la entrada del usuario
                 return 
    
    # -----------------------------------------------------------------
    # SIDEBAR: BOTONES DE PERSISTENCIA Y CARGA DE DOCUMENTOS
    # -----------------------------------------------------------------
    
    st.sidebar.markdown("---")
    # Botón de Descarga JSON (Persistencia de la sesión)
    if st.session_state.pat_data.get('problema') is not None or st.session_state.pat_data.get('proposito') is not None:
         save_pat_progress(user_area, st.session_state.pat_data)

    # Botón de Descarga PDF (Artefacto legible)
    if st.session_state.messages:
        pdf_bytes = generate_pdf_conversation(st.session_state.messages, user_area)
        st.sidebar.download_button(
            label="📄 Exportar Conversación a PDF",
            data=pdf_bytes,
            file_name=f"conversacion_progob_{user_area}.pdf",
            mime='application/pdf',
            help="Descarga una transcripción de la conversación actual."
        )
        
    st.sidebar.markdown("---")

    # UPLOADER DE DOCUMENTOS PERSONALIZADOS (Se mantiene)
    uploaded_custom_file = st.sidebar.file_uploader(
        "📂 Subir Documento Personalizado (PDF/TXT)",
        type=['pdf', 'txt'],
        key="custom_doc_uploader",
        help="Sube su reglamento o lineamientos internos (se usará como contexto RAG)."
    )
    
    if uploaded_custom_file is not None:
        file_name = uploaded_custom_file.name
        
        # Lógica para extraer contenido (se mantiene)
        content = ""
        try:
            if file_name.endswith('.pdf'):
                tfile = uploaded_custom_file
                pdf_reader = pypdf.PdfReader(tfile)
                for page in pdf_reader.pages:
                    content += page.extract_text() or ""
            else: # Asumir .txt
                 content = uploaded_custom_file.getvalue().decode('utf-8')
        except Exception as e:
            st.sidebar.error(f"Error al procesar el archivo: {e}")
            content = ""

        
        if content and len(content) > 50:
            if 'custom_docs_content' not in st.session_state:
                st.session_state['custom_docs_content'] = {}
            
            st.session_state['custom_docs_content'][file_name] = content
            st.sidebar.success(f"✅ Documento '{file_name}' cargado al contexto RAG.")
            # Reforzamos el mensaje de bienvenida con el nuevo contexto
            st.session_state.messages.append({"role": "assistant", "content": f"**Progob Nota:** El documento '{file_name}' ha sido incorporado al contexto de conocimiento. Lo usaré para alinear mis respuestas a sus lineamientos internos."})
            # Limpiamos el uploader para permitir otra subida
            uploaded_custom_file = None
        else:
             st.sidebar.error(f"❌ Error al leer o contenido vacío del documento.")

    st.sidebar.markdown(f"**Documentos Personalizados Cargados:** {len(st.session_state.get('custom_docs_content', []))}")
    st.sidebar.markdown("---")
    # Muestra el estado de la persistencia (descarga)
    st.sidebar.markdown(f"**Estado de Avance:** {st.session_state.get('drive_status', 'No verificado.')}")


    # --- 2. Mostrar Historial del Chat ---
    # Este loop muestra el historial y es crucial
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    
    # --- 3. Manejar Entrada del Usuario y Lógica Secuencial ---
    if st.session_state.current_phase != 'Fin_MIR':
        if user_prompt := st.chat_input("Escribe aquí tu respuesta o propuesta..."):
            
            # Mostrar la entrada del usuario inmediatamente
            st.session_state.messages.append({"role": "user", "content": user_prompt})
            
            # 3.2 Llamar a la nueva lógica de fases y obtener el contenido completo
            # La función devuelve el string completo, pero se genera con delay en el LLM.
            response_content = handle_phase_logic(user_prompt, user_area)
            
            # 3.3 Añadir respuesta del asistente con streaming simulado
            with st.chat_message("assistant"):
                # Generamos el efecto de tecleo aquí
                # Usamos un generador más simple basado en caracteres si la división por palabras es muy rápida
                def stream_simulator(text):
                    for char in text:
                        yield char
                        # Controlamos la velocidad: más lento para saltos de línea/puntuación
                        if char in ['.', '!', '?']:
                             time.sleep(0.1)
                        elif char in [',', ';', ':']:
                             time.sleep(0.05)
                        else:
                             time.sleep(0.005)
                
                # Streamlit escribe la respuesta simulada
                st.write_stream(stream_simulator(response_content))

            # 3.4 Guardar la respuesta completa (ya streameada) en el historial
            st.session_state.messages.append({"role": "assistant", "content": response_content})
            
            st.rerun()

    else:
        st.markdown(f"**✅ PROCESO COMPLETADO (LÓGICA VERTICAL):** La lógica vertical de la MIR (Problema, Propósito y Componentes) ha sido validada y el avance ha sido guardado. Escribe 'INICIAR DE NUEVO' para limpiar el historial y comenzar un nuevo ciclo.")
        if st.chat_input("Escribe 'INICIAR DE NUEVO' para reiniciar..."):
             st.session_state.clear()
             st.session_state['authenticated'] = True 
             st.rerun()


# --------------------------------------------------------------------------
# D. VISTA DEL ADMINISTRADOR (Se mantiene)
# --------------------------------------------------------------------------

def admin_view(user_name):
    """Interfaz de administración para la gestión de usuarios (Se mantiene por ahora)."""
    st.title(f"Panel de Administrador | {user_name}")
    st.subheader("Gestión de Usuarios y Supervisión de PATs")
    st.warning("La persistencia de Drive fue deshabilitada. El avance se guarda por descarga JSON.")
    st.markdown("---")
    df_users = load_users()
    if not df_users.empty:
        st.markdown("**Vista Previa de Usuarios**")
        cols_to_show = [col for col in ['nombre', 'area', 'role', 'username'] if col in df_users.columns]
        if cols_to_show:
            st.dataframe(df_users[cols_to_show].sort_values('role', ascending=False), height=200)


# --------------------------------------------------------------------------
# E. FUNCIÓN PRINCIPAL DE LA APP (Login)
# --------------------------------------------------------------------------

def main():
    """Función principal para manejar el login y enrutamiento."""
    df_users = load_users()
    
    if 'authenticated' not in st.session_state:
        st.session_state['authenticated'] = False

    if st.session_state['authenticated']:
        if st.session_state['role'] == 'admin':
            admin_view(st.session_state['user_name'])
        else:
            chat_view(st.session_state['user_name'], st.session_state['user_area'])
    else:
        st.sidebar.title("Bienvenido al Asesor PbR/MML")
        st.sidebar.markdown("---")
        username = st.sidebar.text_input("Usuario (Correo)", key="login_user")
        password = st.sidebar.text_input("Contraseña", type="password", key="login_pass")
        
        if st.sidebar.button("🔐 Ingresar"):
            if df_users.empty:
                st.sidebar.error("Error de carga. El listado de usuarios está vacío. Verifique el archivo users.xlsx o la sección [users] en secrets.toml.")
            else:
                role, name, area = authenticate(username, password, df_users)
                
                if role:
                    # Almacenamos los mensajes iniciales cargados (si aplica)
                    temp_messages = st.session_state.get('messages', [])
                    temp_current_phase = st.session_state.get('current_phase', 'inicio')
                    
                    st.session_state.clear()
                    
                    st.session_state['authenticated'] = True
                    st.session_state['role'] = role
                    st.session_state['user_name'] = name
                    st.session_state['user_area'] = area
                    st.session_state['messages'] = temp_messages # Restauramos los mensajes si existían (cargados del JSON)
                    st.session_state['current_phase'] = temp_current_phase
                    
                    st.sidebar.success(f"Acceso exitoso. Bienvenido(a), {name}.")
                    st.rerun() 
                else:
                    st.sidebar.error("Usuario o contraseña incorrectos. Verifique sus credenciales.")
        
        if df_users.empty:
            st.warning(f"⚠️ **ATENCIÓN:** El listado de usuarios no ha sido cargado. Asegúrese de que exista un archivo como `{USERS_FILE_NAME}` o la sección `[users]` en su `secrets.toml`.")
    
    # Pie de página (Footer)
    st.markdown("---")
    st.markdown("<p style='text-align: right; color: gray; font-size: small;'>2026 * Sergio Cortina * Chatbot Asesor</p>", unsafe_allow_html=True)


if __name__ == "__main__":
    main()