import streamlit as st
import pandas as pd
import os
import json
import io
import requests 
import re 
# Importar librerías críticas para Persistencia (funcional) y RAG
try:
    import pypdf # Librería para leer PDFs
    import gspread
    from oauth2client.service_account import ServiceAccountCredentials
except ImportError:
    pypdf = None
    gspread = None
    ServiceAccountCredentials = None
    

# --- CONFIGURACIÓN GENERAL ---
st.set_page_config(page_title="Asesor Progob PBR/MML Veracruz", layout="wide")

# Nombres de archivo y directorios
USERS_FILE_NAME = "users.xlsx" 
DOCS_DIR = "docs"
ACTIVIDADES_FILE = os.path.join(DOCS_DIR, "Actividades por area.csv") 
REGLAMENTO_FILE = os.path.join(DOCS_DIR, "REGLAMENTO-INTERIOR-DE-LA-ADMINISTRACION-PUBLICA-DEL-MUNICIPIO-DE-VERACRUZ.pdf") 
GUIDE_FILE = os.path.join(DOCS_DIR, "Modulo7_PbR (IA).pdf") 

# CLAVE API: Se leerá de st.secrets["deepseek_api_key"]

# CLAVE DE HOJA DE CÁLCULO: Se lee SÓLO de st.secrets["spreadsheet_key"]
GOOGLE_SHEET_KEY = None
try:
    GOOGLE_SHEET_KEY = st.secrets["spreadsheet_key"]
except KeyError:
    pass

# Bandera para saber si la persistencia está activa
PERSISTENCE_ENABLED = gspread is not None and ServiceAccountCredentials is not None and GOOGLE_SHEET_KEY is not None


# --- DEFINICIÓN DEL PROMPT MAESTRO (PERSONALIDAD DE PROGOB) ---

SYSTEM_PROMPT = """
# ROL DE ASESOR SENIOR DE PROGOB
**ROL:** Eres el **Enlace Senior de la Oficina de Programa de Gobierno y Mejora Regulatoria (Progob)** del H. Ayuntamiento de Veracruz 2022-2025. Eres un experto en **Gestión para Resultados (GpR)** y **Metodología de Marco Lógico (MML)**, actuando como el **asesor metodológico** del proceso de planeación.

**META:** Guiar al Enlace de Unidad Responsable (UR) paso a paso para construir una Matriz de Indicadores para Resultados (MIR) coherente, utilizando su contexto de área.

**REGLAS DE INTERACCIÓN (CHAT):**
1.  **Secuencialidad:** La conversación se basa en fases. No permitas avanzar hasta que la fase actual (Problema, Propósito, Componente) esté definida.
2.  **Validación:** Cada respuesta debe incluir una validación metodológica y, si es posible, opciones para que el usuario elija (ej. "A", "B", "C").
3.  **Contexto Específico:** Al iniciar, usa las atribuciones y actividades de la Unidad Responsable del usuario ({user_area_context}) para contextualizar las propuestas.
4.  **Formato:** Usa Markdown para claridad.
5.  **Didáctica y Conversación:** Siempre que introduzcas un concepto nuevo (ej. Causa Directa, Indicador RMAE-T, Lógica Vertical), **proporciona una breve explicación didáctica y un ejemplo práctico relacionado con un servicio público**, asumiendo que el usuario no es experto en metodología.

**LENGUAJE:** Utiliza frases como "Consultando la base de conocimiento...", "Revisando el Reglamento Interior...", "Preguntando a Progob...", o "Según la Guía Técnica...". **Nunca menciones "Deepseek", "LLM" o "Modelo de Lenguaje".**
"""

# --------------------------------------------------------------------------
# A. FUNCIONES CENTRALES (Carga de Usuarios y Contexto)
# --------------------------------------------------------------------------

def load_users():
    """Carga el listado de usuarios, priorizando users.xlsx o secrets.toml."""
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
        return text[:15000] 
    except Exception as e:
        return f"ERROR al leer el PDF: {e}"


def load_area_context(user_area):
    """
    Carga el contexto específico del área del usuario, leyendo PDF y CSV (RAG).
    """
    context = {"atribuciones": "Contexto no cargado.", "actividades_previas": "No disponibles.", "guia_metodologica": "Guía no cargada."}

    # --- 1. CARGA DE ATRIBUCIONES (REGLAMENTO PDF) ---
    reglamento_text = extract_text_from_pdf(REGLAMENTO_FILE)
    
    if "ERROR" in reglamento_text:
        context["atribuciones"] = f"ADVERTENCIA (Reglamento): {reglamento_text}"
    else:
        context["atribuciones"] = f"El Reglamento Interior ha sido cargado ({len(reglamento_text)} caracteres). El Asesor utilizará este texto para validar las facultades de {user_area}."
        st.session_state['reglamento_content'] = reglamento_text 
        
    # --- 2. CARGA DE GUÍA METODOLÓGICA (PDF) ---
    guia_text = extract_text_from_pdf(GUIDE_FILE)
    if "ERROR" in guia_text:
        context["guia_metodologica"] = f"ADVERTENCIA (Guía): {guia_text}"
    else:
        context["guia_metodologica"] = f"La Guía Metodológica ha sido cargada ({len(guia_text)} caracteres). El Asesor debe usar esta guía para formular sus preguntas y validaciones metodológicas."
        st.session_state['guia_content'] = guia_text 

    # --- 3. CARGA DE ACTIVIDADES PREVIAS (CSV) ---
    if os.path.exists(ACTIVIDADES_FILE):
        try:
            try:
                df_actividades = pd.read_csv(ACTIVIDADES_FILE, encoding='utf-8')
            except UnicodeDecodeError:
                df_actividades = pd.read_csv(ACTIVIDADES_FILE, sep=';', encoding='latin1') 
                
            df_actividades.columns = df_actividades.columns.str.lower()
            
            if 'area' in df_actividades.columns and 'actividad' in df_actividades.columns:
                clean_user_area_upper = user_area.strip().replace('.', '').upper()
                
                area_keys = [clean_user_area_upper]
                if "SIPINNA" in clean_user_area_upper:
                     area_keys.append('SIPINNA')
                
                filtered_df = df_actividades[
                    df_actividades['area'].astype(str).str.upper().apply(
                        lambda x: any(key in x for key in area_keys)
                    )
                ]
                
                if not filtered_df.empty:
                    actividades_text = "\n* " + "\n* ".join(filtered_df['actividad'].tolist())
                    context["actividades_previas"] = f"Actividades encontradas: ({len(filtered_df)} registros). Estas serán usadas para sugerir Componentes."
                    st.session_state['actividades_content'] = actividades_text
                else:
                    context["actividades_previas"] = f"ADVERTENCIA: No se encontraron actividades previas para la UR '{user_area}' en el CSV. El LLM procederá sin esta referencia. Verifique que el nombre del área en el CSV coincida con una palabra clave clave."

        except Exception as e:
            context["actividades_previas"] = f"Error al procesar el archivo de actividades ({ACTIVIDADES_FILE}): {e}"
    else:
        context["actividades_previas"] = f"ADVERTENCIA: Archivo de actividades no encontrado en la ruta: {ACTIVIDADES_FILE}. Verifique la carpeta 'docs/'."


    return context


def get_llm_response(system_prompt: str, user_query: str):
    """
    Función de conexión a la API, leyendo la clave **SÓLO** desde st.secrets e inyectando contexto RAG.
    """
    try:
        # 🌟 Lectura exclusiva de la clave desde Streamlit Secrets
        api_key = st.secrets["deepseek_api_key"]
    except KeyError:
        st.error("🚨 ERROR: La clave 'deepseek_api_key' no se encuentra en `secrets.toml`.")
        return "❌ Conexión fallida. Por favor, verifica tu clave API."
    
    # --- INYECCIÓN RAG CRÍTICA ---
    rag_context = ""
    if 'reglamento_content' in st.session_state:
        rag_context += f"\n\n--- CONTEXTO RAG (REGLAMENTO INTERIOR) ---\n{st.session_state['reglamento_content']}"
    if 'guia_content' in st.session_state:
        rag_context += f"\n\n--- CONTEXTO RAG (GUÍA METODOLÓGICA) ---\n{st.session_state['guia_content']}"
    if 'actividades_content' in st.session_state:
        rag_context += f"\n\n--- CONTEXTO RAG (ACTIVIDADES PREVIAS DEL ÁREA) ---\n{st.session_state['actividades_content']}"

    final_system_prompt = system_prompt.replace("{user_area_context}", st.session_state['area_context']['atribuciones'])
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
    
    try:
        with st.spinner("🔍 Consultando la base de conocimiento Progob..."):
            response = requests.post(API_URL, headers=headers, json=payload, timeout=60)
            response.raise_for_status()
        
        data = response.json()
        
        if data and 'choices' in data and data['choices']:
            return data['choices'][0]['message']['content']
        else:
            st.warning(f"⚠️ Respuesta vacía o inesperada de la consulta. Código: {response.status_code}")
            return f"⚠️ Progob no pudo generar una respuesta. (Código: {response.status_code})"

    except requests.exceptions.RequestException as e:
        st.error(f"❌ Error en la comunicación con la API. Detalle: {e}")
        return f"❌ Error de comunicación. Detalle: {e}"
    except Exception as e:
        st.error(f"❌ Error interno al procesar la respuesta. Detalle: {e}")
        return "❌ Error interno. Revisa el código de procesamiento."


# --------------------------------------------------------------------------
# B. FUNCIONES DE PERSISTENCIA (Google Drive/gspread - REAL)
# --------------------------------------------------------------------------

def get_gspread_client():
    """Conecta con Google Sheets/Drive usando credenciales de Streamlit Secrets."""
    # Verificación de librerías y clave de hoja de cálculo
    if not PERSISTENCE_ENABLED:
        return None
        
    try:
        creds_dict = st.secrets["gspread"]
        
        # CORRECCIÓN: Usar 'scopes' en plural
        creds = ServiceAccountCredentials.from_json_keyfile_dict(
            creds_dict, 
            scopes=['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        )
        client = gspread.authorize(creds)
        return client
        
    except KeyError as e:
        st.error(f"❌ Error de configuración: Falta la sección {e} en secrets.toml.")
        return None
    except Exception as e:
        # Esto captura errores de conexión o autenticación de Google
        st.error(f"❌ Error de autenticación de GDrive: {e}. Revise sus credenciales y permisos de Drive.")
        return None

def get_pat_file_name(user_area):
    """Genera el nombre de archivo para guardar el avance del PAT."""
    clean_area = re.sub(r'[^a-zA-Z0-9_]', '_', user_area)
    return f"avance_pat_{clean_area}" # Usaremos el nombre de la UR como clave

def save_pat_progress(user_area, pat_data):
    """REAL: Guarda el avance del PAT en Google Sheets (Hoja 'PAT_Data')."""
    client = get_gspread_client()
    if not client:
        st.session_state['drive_status'] = "⚠️ Persistencia: Deshabilitada o error de conexión."
        return

    try:
        # Abre la hoja por la clave definida en secrets.toml y usa la pestaña 'PAT_Data'
        sheet = client.open_by_key(GOOGLE_SHEET_KEY).worksheet("PAT_Data") 
        
        pat_json_data = json.dumps(pat_data, ensure_ascii=False)
        area_names = sheet.col_values(1)
        
        # 1. Buscar si el usuario (UR) ya existe
        try:
            row_index = area_names.index(user_area) + 1 
            # Si existe, actualiza la columna B (Datos JSON)
            sheet.update_cell(row_index, 2, pat_json_data) 
            st.session_state['drive_status'] = f"✅ Persistencia: Avance actualizado para {user_area}."
        except ValueError:
             # 2. Si no existe, añade una nueva fila
             sheet.append_row([user_area, pat_json_data], value_input_option='USER_ENTERED')
             st.session_state['drive_status'] = f"✅ Persistencia: Nuevo PAT guardado para {user_area}."
        
    except Exception as e:
        st.session_state['drive_status'] = f"❌ Error de Persistencia (Guardar): {e}. Asegura que la hoja 'PAT_Data' existe y tiene permisos."

def load_pat_progress(user_area):
    """REAL: Carga el avance del PAT desde Google Sheets."""
    client = get_gspread_client()
    if not client:
        st.session_state['drive_status'] = "⚠️ Persistencia: Deshabilitada o error de conexión."
        return {"problema": None, "proposito": None, "componentes": []}

    try:
        sheet = client.open_by_key(GOOGLE_SHEET_KEY).worksheet("PAT_Data") 
        
        area_names = sheet.col_values(1)
        
        # Buscar la fila del usuario
        try:
            row_index = area_names.index(user_area) + 1 
            pat_json = sheet.cell(row_index, 2).value
            
            if pat_json:
                pat_data = json.loads(pat_json)
                st.session_state['drive_status'] = f"✅ Persistencia: Avance cargado para {user_area}."
                return pat_data
            else:
                st.session_state['drive_status'] = f"⚠️ Persistencia: Fila encontrada, pero sin datos de PAT para {user_area}."
                return {"problema": None, "proposito": None, "componentes": []}
        
        except ValueError:
             st.session_state['drive_status'] = f"⚠️ Persistencia: No se encontró la UR '{user_area}' en la hoja 'PAT_Data'. Se iniciará un nuevo PAT."
             return {"problema": None, "proposito": None, "componentes": []}
        
    except Exception as e:
        st.session_state['drive_status'] = f"❌ Error de Persistencia (Cargar): {e}. Asegura que la hoja 'PAT_Data' existe y tiene permisos."
        return {"problema": None, "proposito": None, "componentes": []}


# --------------------------------------------------------------------------
# C. VISTA DEL ASESOR (CHAT INTERACTIVO)
# --------------------------------------------------------------------------

def chat_view(user_name, user_area):
    """Nueva interfaz principal basada en chat y flujo secuencial."""
    st.title(f"Asesor Metodológico Progob | {user_area}")
    st.subheader(f"Bienvenido(a), {user_name}.")
    
    # --- 1. Inicializar/Cargar estados ---
    if 'pat_data' not in st.session_state:
        st.session_state.pat_data = load_pat_progress(user_area)
    
    if 'messages' not in st.session_state:
        st.session_state.messages = []
    if 'current_phase' not in st.session_state:
        if st.session_state.pat_data.get('proposito'):
            st.session_state.current_phase = 'Componentes_Definicion'
        elif st.session_state.pat_data.get('problema'):
            st.session_state.current_phase = 'Propósito_Seleccion'
        else:
            st.session_state.current_phase = 'inicio'

    if 'area_context' not in st.session_state:
        # 🌟 CARGA CRÍTICA DEL CONTEXTO (RAG)
        st.session_state.area_context = load_area_context(user_area)
        
        if st.session_state.current_phase == 'inicio':
            initial_message = f"""¡Hola, {user_name}! Soy tu Asesor Senior de Progob. 
            
            **Atribuciones de tu UR ({user_area}):** {st.session_state.area_context['atribuciones']}
            
            **Actividades Previas (Referencia):**
            {st.session_state.area_context['actividades_previas']}
            
            **Guía Metodológica:** {st.session_state.area_context['guia_metodologica']}
            
            Comencemos con el primer paso de la Metodología de Marco Lógico (MML): **El Diagnóstico**. 
            
            **FASE 1: DIAGNÓSTICO (PROBLEMA CENTRAL)**
            
            Por favor, ingresa el **Problema Central** que tu área busca resolver este año (el déficit o situación negativa principal).
            """
            st.session_state.messages.append({"role": "assistant", "content": initial_message})
            st.session_state.current_phase = 'Diagnostico_Problema'
        else:
             st.session_state.messages.append({"role": "assistant", "content": f"¡Bienvenido de nuevo! Hemos cargado tu avance. Tu Propósito actual es: **{st.session_state.pat_data['proposito'] or 'Pendiente'}**. Estamos en la **Fase: {st.session_state.current_phase.replace('_', ' ')}**."})
             
    st.sidebar.markdown(f"**Estado de Persistencia:** {st.session_state.get('drive_status', 'No verificado.')}")
    if not PERSISTENCE_ENABLED:
        st.sidebar.error("⚠️ **Persistencia Deshabilitada** (Faltan librerías o claves en secrets.toml).")


    # --- 2. Mostrar Historial del Chat ---
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    
    # --- 3. Manejar Entrada del Usuario y Lógica Secuencial ---
    if st.session_state.current_phase != 'Fin_MIR':
        if user_prompt := st.chat_input("Escribe aquí tu respuesta o propuesta..."):
            st.session_state.messages.append({"role": "user", "content": user_prompt})
            
            response_content = ""
            current_phase = st.session_state.current_phase
            system_context_rag = f"Contexto de la UR ({user_area}): {st.session_state.area_context['atribuciones']}. Actividades: {st.session_state.area_context['actividades_previas']}"
            
            # ----------------------------------------------------------------------
            # FASE: DIAGNÓSTICO DEL PROBLEMA
            # ----------------------------------------------------------------------
            if current_phase == 'Diagnostico_Problema':
                query_llm = f"""
                **FASE ACTUAL: Diagnóstico.** {system_context_rag}
                El usuario propone el siguiente Problema Central: "{user_prompt}".
                
                Como Enlace Senior de Progob: 1. Usando el Reglamento Interior (RAG), **valida** si el problema está dentro de las atribuciones de la UR. 2. Usando la Guía Metodológica (RAG), **genera** 3 Causas Directas y 3 Efectos (Árbol de Problemas) y preséntalos como una tabla. 3. Usando las Actividades Previas (RAG) y la validación anterior, **propón** tres opciones de Propósito (Objetivo General) que se deriven de este problema (Opciones A, B, C). 4. Instruye al usuario a seleccionar una opción. 
                """
                response_content = get_llm_response(SYSTEM_PROMPT, query_llm)
                
                st.session_state.pat_data['problema'] = user_prompt
                st.session_state.current_phase = 'Propósito_Seleccion'
                save_pat_progress(user_area, st.session_state.pat_data)


            # ----------------------------------------------------------------------
            # FASE: SELECCIÓN DEL PROPÓSITO
            # ----------------------------------------------------------------------
            elif current_phase == 'Propósito_Seleccion':
                query_llm = f"""
                **FASE ACTUAL: Propósito (Selección).**
                El problema validado es: "{st.session_state.pat_data['problema']}".
                El usuario seleccionó/propuso: "{user_prompt}" como su Propósito/Objetivo General.
                
                Como Enlace Senior de Progob: 1. Usando la Guía Metodológica (RAG), **valida** el Propósito seleccionado metodológicamente (Lógica Vertical). 2. Sugiere un borrador de Indicador del Propósito (RMAE-T) y el Medio de Verificación. 3. Guía al usuario a la siguiente fase: **Componentes**. Pídele que liste los 2 o 3 productos/servicios principales que su área debe entregar para alcanzar ese Propósito, basados en las Actividades Previas (RAG).
                """
                response_content = get_llm_response(SYSTEM_PROMPT, query_llm)
                
                st.session_state.pat_data['proposito'] = user_prompt
                st.session_state.current_phase = 'Componentes_Definicion'
                save_pat_progress(user_area, st.session_state.pat_data)

            # ----------------------------------------------------------------------
            # FASE: DEFINICIÓN DE COMPONENTES
            # ----------------------------------------------------------------------
            elif current_phase == 'Componentes_Definicion':
                 query_llm = f"""
                **FASE ACTUAL: Componentes.** {system_context_rag}
                Propósito: "{st.session_state.pat_data['proposito']}".
                El usuario propone Componentes/Productos: "{user_prompt}".
                
                Como Enlace Senior de Progob: 1. Usando las Actividades Previas (RAG), **separa** la lista de componentes del usuario. 2. **Evalúa** su coherencia y suficiencia respecto al Propósito (Lógica Horizontal/Vertical). 3. Genera un borrador de Indicador (RMAE-T) y 3 Actividades clave para el primer Componente. 4. Instruye al usuario sobre cómo pasar estas Actividades al Calendario de Trabajo Anual y finalizar la MIR. 
                """
                 response_content = get_llm_response(SYSTEM_PROMPT, query_llm)
                 
                 st.session_state.pat_data['componentes'].append(user_prompt)
                 st.session_state.current_phase = 'Fin_MIR'
                 save_pat_progress(user_area, st.session_state.pat_data)
            
            # 4. Añadir respuesta del asistente al historial y re-ejecutar
            st.session_state.messages.append({"role": "assistant", "content": response_content})
            st.rerun()

    else:
        st.markdown(f"**✅ PROCESO COMPLETADO (FASE MIR):** La lógica vertical ha sido validada. El avance ha sido guardado. Escribe 'INICIAR DE NUEVO' para limpiar el historial y comenzar un nuevo ciclo.")
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
    if not PERSISTENCE_ENABLED:
        st.warning("El panel de administración se mantiene. La persistencia está deshabilitada.")
    else:
        st.info("La persistencia está activa y funcionando.")
        
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
    
    # Muestra la advertencia si faltan los requisitos de persistencia
    if not PERSISTENCE_ENABLED:
         if gspread is None or ServiceAccountCredentials is None:
              st.warning("⚠️ **Advertencia:** Persistencia deshabilitada. Asegúrese de haber instalado las librerías `gspread` y `oauth2client`.")
         elif GOOGLE_SHEET_KEY is None:
              st.warning("⚠️ **Advertencia:** Persistencia deshabilitada. Falta la clave `spreadsheet_key` en su `secrets.toml`.")


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
                    st.session_state.clear()
                    st.session_state['authenticated'] = True
                    st.session_state['role'] = role
                    st.session_state['user_name'] = name
                    st.session_state['user_area'] = area
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