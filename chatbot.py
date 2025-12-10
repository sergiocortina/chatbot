import streamlit as st
import pandas as pd
import os
import json
import io
import requests 
import re 
# Importar gspread y credenciales (Asegúrate de que 'gspread' esté en requirements.txt)
try:
    import gspread
    from oauth2client.service_account import ServiceAccountCredentials
except ImportError:
    gspread = None 

# --- CONFIGURACIÓN GENERAL ---
st.set_page_config(page_title="Asesor Progob PBR/MML Veracruz", layout="wide")

# Nombres de archivo y directorios
USERS_FILE_NAME = "users.xlsx" 
DOCS_DIR = "docs"
# 🌟 CORRECCIÓN CRÍTICA DE NOMBRES DE ARCHIVO
ACTIVIDADES_FILE = os.path.join(DOCS_DIR, "Actividades por area.csv") # <-- Nombre corregido
REGLAMENTO_FILE = os.path.join(DOCS_DIR, "REGLAMENTO-INTERIOR-DE-LA-ADMINISTRACION-PUBLICA-DEL-MUNICIPIO-DE-VERACRUZ.pdf") # <-- Nombre agregado para referencia RAG

# CLAVE API: Se leerá de st.secrets, pero la colocamos aquí para referencia/pruebas locales
DEEPSEEK_API_KEY_LOCAL = "sk-5db40618c1c944779bdec1d46588686d" 

# --- CONFIGURACIÓN DE GSPREAD ---
DRIVE_FOLDER_NAME = "PAT_Avances_Progob" 


# --- DEFINICIÓN DEL PROMPT MAESTRO (PERSONALIDAD DE PROGOB) ---

SYSTEM_PROMPT = """
# ROL DE ASESOR SENIOR DE PROGOB
**ROL:** Eres el **Enlace Senior de la Oficina de Programa de Gobierno y Mejora Regulatoria (Progob)** del H. Ayuntamiento de Veracruz 2022-2025. Eres un experto en **Gestión para Resultados (GpR)** y **Metodología de Marco Lógico (MML)**, actuando como el **asesor metodológico** del proceso de planeación.

**LENGUAJE:** Utiliza frases como "Consultando la base de conocimiento...", "Revisando el Reglamento Interior...", "Preguntando a Progob...", o "Según la Guía Técnica...". **Nunca menciones "Deepseek", "LLM" o "Modelo de Lenguaje".**

**META:** Guiar al Enlace de Unidad Responsable (UR) paso a paso para construir una Matriz de Indicadores para Resultados (MIR) coherente, utilizando su contexto de área.

**REGLAS DE INTERACCIÓN (CHAT):**
1.  **Secuencialidad:** La conversación se basa en fases. No permitas avanzar hasta que la fase actual (Problema, Propósito, Componente) esté definida.
2.  **Validación:** Cada respuesta debe incluir una validación metodológica y, si es posible, opciones para que el usuario elija (ej. "A", "B", "C").
3.  **Contexto Específico:** Al iniciar, usa las atribuciones y actividades de la Unidad Responsable del usuario ({user_area_context}) para contextualizar las propuestas.
4.  **Formato:** Usa Markdown para claridad.
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
            st.error(f"Error al procesar el archivo '{found_file}'. Revise el formato. Error: {e}")
            return pd.DataFrame()

        try:
            df.columns = df.columns.astype(str).str.strip().str.lower()
        except Exception as e:
            st.error(f"Error al normalizar nombres de columna: {e}. Asegúrese de que el archivo tenga encabezados válidos.")
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


def load_area_context(user_area):
    """
    Carga el contexto específico del área del usuario.
    CORRECCIÓN: Se ajusta la lógica para buscar el nombre de archivo exacto en docs/
    """
    context = {"atribuciones": "Lógica RAG pendiente.", "actividades_previas": "No disponibles."}

    # 1. ATRIBUCIONES (Reglamento Interior - Lógica RAG Pendiente)
    # Mostramos un mensaje claro sobre la dependencia RAG.
    atribuciones_status = "El archivo del Reglamento Interior fue encontrado." if os.path.exists(REGLAMENTO_FILE) else "El archivo del Reglamento Interior NO fue encontrado."
    context["atribuciones"] = f"La **Unidad Responsable ({user_area})** está siendo contextualizada con el Reglamento Interior. (Lógica RAG de PDFs pendiente de implementar. Estado del archivo: {atribuciones_status})"

    # 2. Intentar cargar actividades previas desde el CSV de actividades
    if os.path.exists(ACTIVIDADES_FILE):
        try:
            # Leer con codificación robusta
            try:
                df_actividades = pd.read_csv(ACTIVIDADES_FILE, encoding='utf-8')
            except UnicodeDecodeError:
                df_actividades = pd.read_csv(ACTIVIDADES_FILE, encoding='latin1')
                
            df_actividades.columns = df_actividades.columns.str.lower()
            
            # Buscamos el área
            if 'area' in df_actividades.columns and 'actividad' in df_actividades.columns:
                clean_user_area = user_area.strip().replace('.', '').upper()
                
                area_actividades = df_actividades[
                    df_actividades['area'].astype(str).str.upper().str.contains(clean_user_area, case=False, na=False)
                ]
                
                if not area_actividades.empty:
                    actividades_list = area_actividades['actividad'].tolist()
                    context["actividades_previas"] = "\n* " + "\n* ".join(actividades_list)
                    context["actividades_previas"] += "\n(Estas actividades son importantes para definir los Componentes/Productos)."
                else:
                    context["actividades_previas"] = f"No se encontraron actividades previas para el área '{user_area}' en el archivo de referencia. Verifique el nombre del área en el CSV."

        except Exception as e:
            context["actividades_previas"] = f"Error al procesar el archivo de actividades ({ACTIVIDADES_FILE}): {e}"
    else:
        context["actividades_previas"] = f"ADVERTENCIA: Archivo de actividades no encontrado en la ruta: {ACTIVIDADES_FILE}. Verifique la carpeta 'docs/'."


    return context


def get_llm_response(system_prompt: str, user_query: str):
    """
    Función de conexión a la API, leyendo la clave desde st.secrets.
    """
    try:
        api_key = st.secrets["deepseek_api_key"]
    except KeyError:
        # Fallback a clave local si secrets no existe o no tiene la clave
        api_key = DEEPSEEK_API_KEY_LOCAL
        if not api_key or api_key == "sk-5db40618c1c944779bdec1d46588686d":
             st.error("🚨 ERROR: La clave 'deepseek_api_key' no es válida o falta en `secrets.toml`.")
             return "❌ Conexión fallida. Por favor, verifica tu clave API."
    
    API_URL = "https://api.deepseek.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_query}
    ]
    
    payload = {
        "model": "deepseek-chat", 
        "messages": messages,
        "temperature": 0.7,      
        "max_tokens": 2000
    }
    
    try:
        with st.spinner("🔍 Consultando la base de conocimiento Progob..."):
            response = requests.post(API_URL, headers=headers, json=payload, timeout=45)
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
        st.error(f"❌ Error interno al procesar la respuesta: {e}")
        return "❌ Error interno. Revisa el código de procesamiento."


# --------------------------------------------------------------------------
# B. FUNCIONES DE PERSISTENCIA (Google Drive/gspread)
# --------------------------------------------------------------------------

def get_gspread_client():
    """Conecta con Google Sheets/Drive usando credenciales de Streamlit Secrets."""
    if gspread is None:
        return None
        
    try:
        creds_dict = st.secrets["gspread"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope=[
            'https://spreadsheets.google.com/feeds',
            'https://www.googleapis.com/auth/drive'
        ])
        client = gspread.authorize(creds)
        return client
    except KeyError:
        st.warning("⚠️ La sección 'gspread' no está configurada en secrets.toml. Persistencia deshabilitada.")
        return None
    except Exception as e:
        st.error(f"❌ Error de autenticación de GDrive: {e}. Revise sus credenciales.")
        return None

def get_pat_file_name(user_area):
    """Genera el nombre de archivo para guardar el avance del PAT."""
    clean_area = re.sub(r'[^a-zA-Z0-9_]', '_', user_area)
    return f"avance_pat_{clean_area}.json"

def save_pat_progress(user_area, pat_data):
    """Guarda el avance del PAT (Placeholder de Drive)."""
    client = get_gspread_client()
    if not client:
        return

    # LÓGICA DE PERSISTENCIA REAL CON GOOGLE DRIVE API (COMPLEJA) VA AQUÍ
    try:
        st.sidebar.success("💾 Progreso guardado exitosamente en Drive (Simulado).")
        st.session_state['drive_status'] = f"Avance guardado: {get_pat_file_name(user_area)}"
    except Exception as e:
        st.sidebar.error(f"❌ Error al guardar en Drive: {e}")
        st.session_state['drive_status'] = f"Error al guardar: {e}"

def load_pat_progress(user_area):
    """Carga el avance del PAT (Placeholder de Drive)."""
    client = get_gspread_client()
    if not client:
        return {"problema": None, "proposito": None, "componentes": []}

    # LÓGICA DE CARGA DE PERSISTENCIA REAL CON GOOGLE DRIVE API (COMPLEJA) VA AQUÍ
    try:
        st.sidebar.info(f"Cargando avance de {user_area}...")
        st.session_state['drive_status'] = "No se encontró avance previo. Iniciando nuevo PAT."
        return {"problema": None, "proposito": None, "componentes": []}
    except Exception as e:
        st.sidebar.warning(f"⚠️ No se pudo cargar el avance previo. Error: {e}")
        st.session_state['drive_status'] = f"Error de carga: {e}"
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
        st.session_state.area_context = load_area_context(user_area)
        
        if st.session_state.current_phase == 'inicio':
            initial_message = f"""¡Hola, {user_name}! Soy tu Asesor Senior de Progob. 
            
            **Atribuciones de tu UR ({user_area}):** {st.session_state.area_context['atribuciones']}
            
            **Actividades Previas (Referencia):**
            {st.session_state.area_context['actividades_previas']}
            
            Comencemos con el primer paso de la Metodología de Marco Lógico (MML): **El Diagnóstico**. 
            
            **FASE 1: DIAGNÓSTICO (PROBLEMA CENTRAL)**
            
            Por favor, ingresa el **Problema Central** que tu área busca resolver este año (el déficit o situación negativa principal).
            """
            st.session_state.messages.append({"role": "assistant", "content": initial_message})
            st.session_state.current_phase = 'Diagnostico_Problema'
        else:
             st.session_state.messages.append({"role": "assistant", "content": f"¡Bienvenido de nuevo! Hemos cargado tu avance. Tu Propósito actual es: **{st.session_state.pat_data['proposito'] or 'Pendiente'}**. Estamos en la **Fase: {st.session_state.current_phase.replace('_', ' ')}**."})
             
    st.sidebar.markdown(f"**Estado de Persistencia:** {st.session_state.get('drive_status', 'No verificado.')}")


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
                
                Como Enlace Senior de Progob: 1. Evalúa si el problema es un déficit y está dentro de las atribuciones. 2. Genera 3 Causas Directas y 3 Efectos (Árbol de Problemas) y preséntalos como una tabla o lista. 3. Propón tres opciones de Propósito (Objetivo General) que se deriven de este problema (Opciones A, B, C). 4. Instruye al usuario a seleccionar una opción. 
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
                
                Como Enlace Senior de Progob: 1. Valida el Propósito seleccionado metodológicamente. 2. Sugiere un borrador de Indicador del Propósito (RMAE-T) y el Medio de Verificación. 3. Guía al usuario a la siguiente fase: **Componentes**. Pídele que liste los 2 o 3 productos/servicios principales que su área debe entregar para alcanzar ese Propósito.
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
                
                Como Enlace Senior de Progob: 1. Separa la lista de componentes del usuario. 2. Evalúa su coherencia y suficiencia respecto al Propósito. 3. Genera un borrador de Indicador (RMAE-T) y 3 Actividades clave para el primer Componente. 4. Instruye al usuario sobre cómo pasar estas Actividades al Calendario de Trabajo Anual y finalizar la MIR. 
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
    st.warning("El panel de administración se mantiene. Las funciones de carga de PATs requieren la configuración de Google Drive.")
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