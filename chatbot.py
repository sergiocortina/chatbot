import streamlit as st
import pandas as pd
import os
import json
import io
import requests # Necesario para la conexión a la API
import re # Para procesar respuestas del LLM

# --- CONFIGURACIÓN GENERAL ---
st.set_page_config(page_title="Asesor Progob PBR/MML Veracruz", layout="wide")

# Nombres de archivo
USERS_FILE_NAME = "users.xlsx" 

# Clave API de Deepseek (¡REEMPLAZA ESTA CADENA CON TU CLAVE REAL!)
DEEPSEEK_API_KEY = "sk-266e71790bed476bb2c60a322090bf03" 

# Directorio de documentos de contexto
DOCS_DIR = "docs"
ACTIVIDADES_FILE = os.path.join(DOCS_DIR, "actividades_areas.csv") # Asumimos este CSV existe en docs/

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
# A. FUNCIONES CENTRALES
# --------------------------------------------------------------------------

def load_users():
    """Carga el listado de usuarios (Mismo código, ya corregido)."""
    # ... (El código de load_users() y authenticate() de la respuesta anterior se mantiene aquí)
    # [Mantener las funciones load_users y authenticate aquí sin cambios respecto a la versión anterior corregida]
    
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
    Carga el contexto específico del área del usuario (Atribuciones y Actividades previas).
    REQUIERE: Que el archivo ACTIVIDADES_FILE esté disponible en la carpeta DOCS_DIR.
    """
    context = {"atribuciones": "No encontradas.", "actividades_previas": "No disponibles."}

    # 1. Simulación de lectura de atribuciones (Idealmente desde un PDF/Reglamento)
    # Por ahora, usamos un placeholder basado en el área:
    context["atribuciones"] = f"Según el Reglamento Interior, la **Unidad Responsable ({user_area})** tiene la facultad de: [Atribuciones placeholder]. Por lo tanto, su alcance debe limitarse a estas funciones."

    # 2. Intentar cargar actividades previas desde un CSV
    if os.path.exists(ACTIVIDADES_FILE):
        try:
            df_actividades = pd.read_csv(ACTIVIDADES_FILE, encoding='utf-8')
            df_actividades.columns = df_actividades.columns.str.lower()
            
            # Asumimos que hay una columna 'area' y 'actividad'
            if 'area' in df_actividades.columns and 'actividad' in df_actividades.columns:
                area_actividades = df_actividades[df_actividades['area'].str.contains(user_area, case=False, na=False)]
                
                if not area_actividades.empty:
                    actividades_list = area_actividades['actividad'].tolist()
                    context["actividades_previas"] = "\n* " + "\n* ".join(actividades_list)
                    context["actividades_previas"] += "\n(Estas actividades son importantes para definir los Componentes/Productos)."
                else:
                    context["actividades_previas"] = f"No se encontraron actividades previas para el área '{user_area}' en el archivo de referencia."

        except Exception as e:
            context["actividades_previas"] = f"Error al leer el archivo de actividades: {e}"

    return context


def get_llm_response(system_prompt: str, user_query: str):
    """
    Función de conexión a la API (Renombrada de deepseek_response a llm_response).
    """
    global DEEPSEEK_API_KEY
    
    if DEEPSEEK_API_KEY == "sk-266e71790bed476bb2c60a322090bf03" or not DEEPSEEK_API_KEY:
        st.error("🚨 ERROR: Clave API no configurada.")
        return "❌ Conexión fallida. Por favor, configura tu clave API para continuar."
    
    API_URL = "https://api.deepseek.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
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
        "max_tokens": 2000 # Aumentamos tokens para respuestas detalladas
    }
    
    try:
        with st.spinner("🔍 Consultando la base de conocimiento Progob..."): # Nuevo mensaje
            response = requests.post(API_URL, headers=headers, json=payload, timeout=45)
            response.raise_for_status()
        
        data = response.json()
        
        if data and 'choices' in data and data['choices']:
            return data['choices'][0]['message']['content']
        else:
            st.warning(f"⚠️ Respuesta vacía o inesperada de la consulta. Código: {response.status_code}")
            return f"⚠️ Progob no pudo generar una respuesta. (Código: {response.status_code})"

    except requests.exceptions.HTTPError as e:
        st.error(f"❌ Error HTTP: {response.status_code} - {response.text}")
        return f"❌ Error en la comunicación con el servidor. Verifica tu clave API y saldo."
    except requests.exceptions.RequestException as e:
        st.error(f"❌ Error de red: {e}")
        return f"❌ Error de conexión. Asegúrate de tener acceso a internet."
    except Exception as e:
        st.error(f"❌ Error interno al procesar la respuesta: {e}")
        return "❌ Error interno. Revisa el código de procesamiento."


# --- PERSISTENCIA (PENDIENTE DE CONFIGURAR CON GOOGLE DRIVE/GSPREAD) ---
def save_pat_progress(user_id, pat_data):
    """Placeholder para guardar el avance del PAT en Drive/Archivo JSON."""
    # st.session_state['drive_status'] = "⚠️ Persistencia: Pendiente de configurar la conexión a Google Drive."
    # LOGICA DE GSPREAD O PYDRIVE VA AQUÍ
    pass

# --------------------------------------------------------------------------
# B. VISTA DEL ASESOR (CHAT INTERACTIVO)
# --------------------------------------------------------------------------

def chat_view(user_name, user_area):
    """Nueva interfaz principal basada en chat y flujo secuencial."""
    st.title(f"Asesor Metodológico Progob | {user_area}")
    st.subheader(f"Bienvenido(a), {user_name}.")
    
    # 1. Inicializar estados
    if 'messages' not in st.session_state:
        st.session_state.messages = []
    if 'current_phase' not in st.session_state:
        st.session_state.current_phase = 'inicio'
    if 'pat_data' not in st.session_state:
        st.session_state.pat_data = {"problema": None, "proposito": None, "componentes": []}
    if 'area_context' not in st.session_state:
        # Cargar contexto la primera vez que se entra al chat
        st.session_state.area_context = load_area_context(user_area)
        
        # Mensaje de bienvenida inicial (solo si es la primera vez)
        initial_message = f"""¡Hola, {user_name}! Soy tu Asesor Senior de Progob. 
        
        **Atribuciones de tu UR ({user_area}):** {st.session_state.area_context['atribuciones']}
        
        **Actividades Previas (Referencia):**
        {st.session_state.area_context['actividades_previas']}
        
        Comencemos con el primer paso de la Metodología de Marco Lógico (MML): **El Diagnóstico**.
        
        **FASE 1: DIAGNÓSTICO (PROBLEMA CENTRAL)**
        
        Por favor, ingresa el **Problema Central** que tu área busca resolver este año (el déficit o situación negativa principal). Por ejemplo: "Alto índice de quejas ciudadanas por trámites lentos."
        """
        st.session_state.messages.append({"role": "assistant", "content": initial_message})
        st.session_state.current_phase = 'Diagnostico_Problema'


    # 2. Mostrar Historial del Chat
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            # Aquí podríamos añadir la validación o botón de guardar si el mensaje lo requiere


    # 3. Manejar Entrada del Usuario y Lógica Secuencial
    if user_prompt := st.chat_input("Escribe aquí tu respuesta o propuesta..."):
        # Añadir prompt del usuario al historial
        st.session_state.messages.append({"role": "user", "content": user_prompt})
        
        # Lógica de procesamiento basada en la fase actual
        response_content = ""
        current_phase = st.session_state.current_phase
        
        # ----------------------------------------------------------------------
        # FASE: DIAGNÓSTICO DEL PROBLEMA
        # ----------------------------------------------------------------------
        if current_phase == 'Diagnostico_Problema':
            # 1. Definir Query para el LLM
            system_context_rag = f"Contexto de la UR ({user_area}): {st.session_state.area_context['atribuciones']}. Actividades: {st.session_state.area_context['actividades_previas']}"
            
            query_llm = f"""
            **FASE ACTUAL: Diagnóstico.**
            {system_context_rag}
            
            El usuario propone el siguiente Problema Central: "{user_prompt}".
            
            Como Enlace Senior de Progob:
            1. **Evalúa** si el problema es un déficit, no una solución, y si está dentro de las atribuciones de la UR.
            2. **Genera** 3 Causas Directas y 3 Efectos (para el Árbol de Problemas).
            3. **Propón** tres opciones de Propósito (Objetivo General) que se deriven de este problema (Opciones A, B, C).
            4. **Instruye** al usuario a seleccionar el Propósito que mejor se alinee a su Plan Anual.
            """
            response_content = get_llm_response(SYSTEM_PROMPT, query_llm)
            
            # 2. Actualizar Fase y Datos
            st.session_state.pat_data['problema'] = user_prompt
            st.session_state.current_phase = 'Propósito_Seleccion' # Siguiente fase
            save_pat_progress(st.session_state['user_area'], st.session_state.pat_data)


        # ----------------------------------------------------------------------
        # FASE: SELECCIÓN DEL PROPÓSITO
        # ----------------------------------------------------------------------
        elif current_phase == 'Propósito_Seleccion':
            # Asumimos que la respuesta del usuario es la selección de una opción (ej. "A")
            # En una implementación real, aquí se procesaría la opción A/B/C del usuario
            
            query_llm = f"""
            **FASE ACTUAL: Propósito (Selección).**
            El problema validado es: "{st.session_state.pat_data['problema']}".
            El usuario seleccionó: "{user_prompt}" como su Propósito/Objetivo General.
            
            Como Enlace Senior de Progob:
            1. **Valida** el Propósito seleccionado metodológicamente (Lógica Vertical).
            2. **Sugiere** un borrador de Indicador del Propósito (RMAE-T) y el Medio de Verificación.
            3. **Guía** al usuario a la siguiente fase: **Componentes**. Pídele que liste los 2 o 3 productos/servicios principales que su área debe entregar para alcanzar ese Propósito.
            """
            response_content = get_llm_response(SYSTEM_PROMPT, query_llm)
            
            st.session_state.pat_data['proposito'] = user_prompt
            st.session_state.current_phase = 'Componentes_Definicion' # Siguiente fase
            save_pat_progress(st.session_state['user_area'], st.session_state.pat_data)

        # ----------------------------------------------------------------------
        # FASE: DEFINICIÓN DE COMPONENTES
        # ----------------------------------------------------------------------
        elif current_phase == 'Componentes_Definicion':
             query_llm = f"""
            **FASE ACTUAL: Componentes.**
            Propósito: "{st.session_state.pat_data['proposito']}".
            El usuario propone Componentes/Productos: "{user_prompt}".
            
            Como Enlace Senior de Progob:
            1. **Separa** la lista de componentes del usuario.
            2. **Evalúa** su coherencia y suficiencia respecto al Propósito.
            3. **Genera** un borrador de Indicador (RMAE-T) y 3 Actividades clave para el primer Componente.
            4. **Instruye** al usuario sobre cómo pasar estas Actividades al Calendario de Trabajo Anual.
            """
             response_content = get_llm_response(SYSTEM_PROMPT, query_llm)
             
             # Aquí podríamos guardar los componentes en pat_data
             st.session_state.current_phase = 'Fin_MIR'
             save_pat_progress(st.session_state['user_area'], st.session_state.pat_data)
        
        # ----------------------------------------------------------------------
        # FASE: FIN DEL PROCESO
        # ----------------------------------------------------------------------
        else:
             response_content = "El proceso ha terminado. Si deseas iniciar un nuevo ciclo o afinar tu MIR, por favor, ingresa tu consulta o escribe 'INICIAR DE NUEVO'."

        # 4. Añadir respuesta del asistente al historial
        st.session_state.messages.append({"role": "assistant", "content": response_content})
        st.rerun()

# --------------------------------------------------------------------------
# C. VISTA DEL ADMINISTRADOR (Sin cambios en esta refactorización)
# --------------------------------------------------------------------------

def admin_view(user_name):
    """Interfaz de administración para la gestión de usuarios (Se mantiene por ahora)."""
    st.title(f"Panel de Administrador | {user_name}")
    st.subheader("Gestión de Usuarios y Supervisión de PATs")
    
    # ... (El código de admin_view() se mantiene aquí)
    st.markdown("---")
    st.warning("El panel de administración se mantiene. Las funciones de carga de PATs requieren la configuración de Google Drive.")


# --------------------------------------------------------------------------
# D. FUNCIÓN PRINCIPAL DE LA APP (Login)
# --------------------------------------------------------------------------

def main():
    """Función principal para manejar el login y enrutamiento."""
    df_users = load_users()
    
    # Manejar estado de sesión
    if 'authenticated' not in st.session_state:
        st.session_state['authenticated'] = False

    if st.session_state['authenticated']:
        # Usuario ya autenticado
        if st.session_state['role'] == 'admin':
            admin_view(st.session_state['user_name'])
        else:
            # CORRECCIÓN: Llamamos a la nueva vista de chat
            chat_view(st.session_state['user_name'], st.session_state['user_area'])
    else:
        # PANTALLA DE LOGIN
        st.sidebar.title("Bienvenido al Asesor PbR/MML")
        st.sidebar.markdown("---")
        username = st.sidebar.text_input("Usuario (Correo)", key="login_user")
        password = st.sidebar.text_input("Contraseña", type="password", key="login_pass")
        
        if st.sidebar.button("🔐 Ingresar"):
            if df_users.empty:
                st.sidebar.error("Error de carga. El listado de usuarios está vacío. Verifique el archivo y su formato.")
            else:
                role, name, area = authenticate(username, password, df_users)
                
                if role:
                    st.session_state['authenticated'] = True
                    st.session_state['role'] = role
                    st.session_state['user_name'] = name
                    st.session_state['user_area'] = area
                    st.sidebar.success(f"Acceso exitoso. Bienvenido(a), {name}.")
                    st.rerun() 
                else:
                    st.sidebar.error("Usuario o contraseña incorrectos. Verifique sus credenciales.")
        
        if df_users.empty:
            st.warning(f"⚠️ **ATENCIÓN:** El listado de usuarios no ha sido cargado. Asegúrese de que exista un archivo como `{USERS_FILE_NAME}` en su repositorio.")
    
    # Pie de página (Footer)
    st.markdown("---")
    st.markdown("<p style='text-align: right; color: gray; font-size: small;'>2026 * Sergio Cortina * Chatbot Asesor</p>", unsafe_allow_html=True)


if __name__ == "__main__":
    main()