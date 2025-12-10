# ==============================================================================
# ASESOR METODOLÓGICO PBR/MML - OFICINA DE PROGRAMA DE GOBIERNO
# ==============================================================================

import streamlit as st
import requests
import os
import pypdf
import pandas as pd
import io 

# --- CONFIGURACIÓN DE LA API Y CONSTANTES DE SEGURIDAD ---

# 🚨 CAMBIO CLAVE: Lee la clave API de forma segura desde st.secrets
try:
    API_KEY = st.secrets["DEEPSEEK_API_KEY"]
except KeyError:
    API_KEY = "CLAVE_API_NO_CONFIGURADA" 

API_URL = "https://api.deepseek.com/chat/completions" 
MODEL_NAME = "deepseek-reasoner" 
USER_DATA_FILE = "users.xlsx - users.csv" # Nombre del archivo CSV subido

# ==============================================================================
# 1. IMPLEMENTACIÓN RAG (Generación Aumentada por Recuperación)
# ==============================================================================

@st.cache_resource
def load_pdf_knowledge(directory="docs"):
    """Carga el texto de todos los archivos PDF en el directorio especificado."""
    # ... (El código de carga de PDFs se mantiene igual, asumiendo la carpeta 'docs/')
    if not os.path.exists(directory):
        # En Streamlit Cloud, es común que la carpeta 'docs' no exista
        # si los archivos se subieron directamente al repo, no se mostrará este error,
        # pero es bueno mantenerlo para pruebas locales.
        st.warning(f"🚨 Advertencia: El directorio '{directory}' no existe. RAG inactivo.")
        return ""

    full_text = []
    
    for filename in os.listdir(directory):
        if filename.endswith(".pdf"):
            try:
                path = os.path.join(directory, filename)
                reader = pypdf.PdfReader(path)
                text = f"\n\n--- DOCUMENTO: {filename} ---\n"
                for page in reader.pages:
                    text += page.extract_text()
                full_text.append(text)
            except Exception as e:
                print(f"Error al leer el PDF {filename}: {e}")
                
    if full_text:
        # Se elimina el st.success para que no aparezca en la UI
        # st.success(f"✅ Documentación personalizada cargada ({len(full_text)} archivos).")
        return "\n\n".join(full_text)
    else:
        st.warning("⚠️ No se encontraron archivos PDF para cargar. Base de conocimiento limitada.")
        return ""

KNOWLEDGE_BASE_TEXT = load_pdf_knowledge()

# --- Reglamento Interior y Atribuciones (Instrucción Específica) ---

REGLAMENTO_TEXT = """
## ATRIBUCIONES INSTITUCIONALES Y REGLAMENTO INTERIOR
El **Asesor de Progob** debe recordar que la responsabilidad final del PAT recae **exclusivamente en la Unidad Responsable (UR)**. Tu rol es guiar, sugerir y revisar la coherencia con los documentos oficiales, no determinar metas.
"""

# --- Prompt de Sistema (Rol Corporativo y Restricción de Flujo) ---

SYSTEM_PROMPT_TEMPLATE = f"""
# ROL: ASESOR METODOLÓGICO PBR/MML DE LA OFICINA DE PROGRAMA DE GOBIERNO
Eres el **Asesor Metodológico PBR/MML de la Oficina de Programa de Gobierno y Mejora Regulatoria del H. Ayuntamiento de Veracruz**. 
Tu usuario es el Enlace de la Unidad Responsable: **{{area}}**.
Tu función es guiar al usuario paso a paso, utilizando la Metodología de Marco Lógico (MML) para elaborar su Programa Anual de Trabajo (PAT).

## INSTRUCCIONES DE FLUJO Y CONTROL
1.  **FLUJO ESTRICTO:** No avances al siguiente paso de la MML hasta que el usuario confirme su conformidad con una de las opciones numéricas que le presentes.
2.  **PRESENTACIÓN DE OPCIONES:** Al finalizar cada paso (Diagnóstico, Causas/Efectos, Objetivos, etc.), debes presentar opciones claras para avanzar, modificar o reiniciar.
    * Ejemplo de opciones (siempre al final del paso):
        "**Para continuar, por favor, indica tu opción:**"
        "**1. Confirmar y pasar a la siguiente fase (Árbol de Objetivos).**"
        "**2. Modificar el Problema Central (o la información actual).**"
        "**3. Reiniciar la Fase de Diagnóstico.**"
3.  **ESPERA DE RESPUESTA:** Si el usuario no ingresa 1, 2 o 3, recuérdale que debe seleccionar una opción numérica para continuar.
4.  **PERSONALIZACIÓN:** Usa el nombre de la Unidad Responsable ({{area}}) para hacer las sugerencias relevantes a su área de trabajo.

## BASE DE CONOCIMIENTO TÉCNICO
Tu respuesta debe ser profesional y **estrictamente basada** en los siguientes documentos de referencia oficiales del H. Ayuntamiento y el marco federal:

{REGLAMENTO_TEXT}

--- INICIO DE BASE DE CONOCIMIENTO TÉCNICO ---
{KNOWLEDGE_BASE_TEXT}
--- FIN DE BASE DE CONOCIMIENTO TÉCNICO ---

Instrucción de Respuesta: Responde siempre como **personal de la Oficina de Programa de Gobierno**.
"""


# ==============================================================================
# 2. FUNCIÓN DE CONEXIÓN Y UTILIDADES
# ==============================================================================

@st.cache_data
def load_user_data(file_path=USER_DATA_FILE):
    """Carga y cachea los datos de usuario para el login."""
    try:
        # Intenta leer el archivo subido
        return pd.read_csv(file_path)
    except FileNotFoundError:
        st.error(f"❌ Error fatal: El archivo de usuarios '{file_path}' no fue encontrado.")
        # Devuelve un DataFrame vacío si no se encuentra
        return pd.DataFrame() 

def authenticate(username, password, df_users):
    """Verifica credenciales y devuelve rol, nombre y área."""
    user = df_users[(df_users['username'] == username) & (df_users['password'] == password)]
    if not user.empty:
        role = user.iloc[0]['role']
        name = user.iloc[0]['nombre']
        area = user.iloc[0]['area']
        return role, name, area
    return None, None, None

def get_llm_response(area: str, user_query: str):
    """
    Conecta al motor de IA, inyectando el prompt con la info del área.
    """
    if API_KEY == "CLAVE_API_NO_CONFIGURADA":
        st.error("🚨 ERROR: Debes configurar tu clave API en el archivo .streamlit/secrets.toml.")
        return "❌ Conexión fallida. Clave API no configurada."

    # 1. Personalizar el SYSTEM_PROMPT con el área
    system_prompt = SYSTEM_PROMPT_TEMPLATE.replace("{{area}}", area)
    
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    
    messages = [
        {"role": "system", "content": system_prompt},
    ]
    # Añadir historial de chat para contexto (evitando reinyectar el system prompt completo)
    # Se envía la historia previa para que el LLM sepa qué ha respondido y qué fase sigue.
    for role, text in st.session_state.chat_history:
        messages.append({"role": "user" if role == "user" else "assistant", "content": text})
    
    # Añadir el último query del usuario
    messages.append({"role": "user", "content": user_query})

    payload = {
        "model": MODEL_NAME, 
        "messages": messages,
        "temperature": 0.5,
        "max_tokens": 4096
    }
    
    try:
        # 🚨 CAMBIO CLAVE: Mensaje de carga personalizado (Progob)
        with st.spinner("Revisando mi banco de datos y preguntando a Progob..."): 
            response = requests.post(API_URL, headers=headers, json=payload, timeout=90)
            response.raise_for_status()
        
        data = response.json()
        
        if data and 'choices' in data and data['choices']:
            return data['choices'][0]['message']['content']
        else:
            return f"⚠️ Respuesta vacía o inesperada. JSON: {data}"

    except requests.exceptions.HTTPError as e:
        return f"❌ Error de la API: {e}. Verifica la URL y el modelo."
    except Exception as e:
        return f"❌ Error de conexión o procesamiento: {e}"


# ==============================================================================
# 3. INTERFAZ DE STREAMLIT (Vista de Enlace)
# ==============================================================================

def enlace_view(user_name, area):
    """Vista principal para el enlace de la Unidad Responsable (Chat Style)."""
    
    st.title("Asesoría PbR/MML")
    st.subheader(f"Asistente de la Oficina de Programa de Gobierno para: **{area}**")

    # Mensaje inicial que se muestra solo una vez
    if not st.session_state.chat_history:
        initial_message = (
            f"¡Bienvenido(a), {user_name}! Soy el **Asesor Metodológico de la Oficina de Programa de Gobierno**.\n\n"
            f"Mi función es guiar a su Unidad Responsable (**{area}**) paso a paso en la elaboración del Programa Anual de Trabajo (PAT) con base en la Metodología de Marco Lógico (MML) y la documentación oficial del Ayuntamiento.\n\n"
            "**Fase 1: Diagnóstico - Problema Central**\n"
            "Por favor, ingresa el **Problema Central** que tu Unidad busca resolver. Debe ser un déficit o una situación negativa en una o dos oraciones."
        )
        st.session_state.chat_history.append(("assistant", initial_message))

    # Nuevo estilo de chat (display del historial)
    st.markdown("---")
    
    # Mostrar el historial con st.chat_message
    for role, text in st.session_state.chat_history:
        # Determinar el nombre a mostrar en el chat
        display_name = "Asesor Progob" if role == "assistant" else user_name
        
        with st.chat_message(role, avatar="🧑‍💼" if role == "assistant" else "👤"):
            st.markdown(text)

    # st.chat_input (Se ubica al final de la página, reemplazando el text_area)
    user_input = st.chat_input("Escribe tu Problema Central o tu opción (1, 2 o 3) para continuar...")

    if user_input:
        # 1. Agregar la consulta del usuario al historial primero
        st.session_state.chat_history.append(("user", user_input))
        
        # 2. Generar respuesta (con el historial completo)
        response_text = get_llm_response(area, user_input)
        
        # 3. Agregar la respuesta del asistente al historial
        st.session_state.chat_history.append(("assistant", response_text))
        
        # 4. Forzar re-ejecución para mostrar los nuevos mensajes en el chat
        st.rerun()

def admin_view(user_name):
    """Vista para el administrador."""
    st.title("Vista de Administrador - Oficina de Programa de Gobierno")
    st.info(f"Bienvenido, {user_name}. Aquí podrías gestionar usuarios, reportes o la base de conocimiento.")

# ==============================================================================
# 4. PUNTO DE ENTRADA (Manejo de Sesión y Login)
# ==============================================================================

def main():
    
    df_users = load_user_data()
    
    if df_users.empty:
        st.stop()
    
    if 'authenticated' not in st.session_state:
        st.session_state.authenticated = False
        st.session_state.user_name = None
        st.session_state.user_area = None

    if st.session_state.authenticated:
        # Barra lateral de información y cierre de sesión
        st.sidebar.image("https://upload.wikimedia.org/wikipedia/commons/2/2c/Escudo_de_Veracruz.svg", width=100)
        st.sidebar.title("Asesor Progob")
        st.sidebar.markdown(f"**Usuario:** {st.session_state.user_name}")
        st.sidebar.markdown(f"**Área:** {st.session_state.user_area}")
        st.sidebar.markdown("---")
        
        if st.session_state.role == "admin":
            admin_view(st.session_state.user_name)
        else:
            enlace_view(st.session_state.user_name, st.session_state.user_area)
            
        if st.sidebar.button("🔒 Cerrar Sesión"):
            st.session_state.clear()
            st.rerun()
            
    else:
        # Vista de Login (en el sidebar)
        st.sidebar.image("https://upload.wikimedia.org/wikipedia/commons/2/2c/Escudo_de_Veracruz.svg", width=100)
        st.sidebar.title("Asesor PbR/MML Veracruz")
        st.sidebar.markdown("---")
        username = st.sidebar.text_input("Correo institucional")
        password = st.sidebar.text_input("Contraseña", type="password")

        if st.sidebar.button("Ingresar"):
            role, name, area = authenticate(username, password, df_users)
            if role:
                st.session_state.authenticated = True
                st.session_state.role = role
                st.session_state.user_name = name
                st.session_state.user_area = area
                st.rerun()
            else:
                st.sidebar.error("Credenciales incorrectas.")

if __name__ == "__main__":
    main()