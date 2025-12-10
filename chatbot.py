# ==============================================================================
# ASESOR METODOLÓGICO PBR/MML - OFICINA DE PROGRAMA DE GOBIERNO
# Versión: FINAL y SEGURA (Lectura de credenciales y datos de usuario desde st.secrets)
# ==============================================================================

import streamlit as st
import requests
import os
import pypdf # Asegúrate de tener 'pypdf' en requirements.txt
import pandas as pd
import io # Necesario para leer la cadena de texto CSV desde secrets

# --- CONFIGURACIÓN INICIAL DE LA PÁGINA ---
st.set_page_config(page_title="Asesoría Progob PbR/MML", layout="wide")

# --- CONFIGURACIÓN DE LA API Y SEGURIDAD ---

# 🚨 CLAVE API: Lee la clave API de forma segura desde st.secrets
try:
    API_KEY = st.secrets["DEEPSEEK_API_KEY"]
except KeyError:
    API_KEY = None 
    st.error("🚨 ERROR FATAL: La clave DEEPSEEK_API_KEY no se encontró en secrets.toml.")

API_URL = "https://api.deepseek.com/chat/completions" 
MODEL_NAME = "deepseek-reasoner" 

# ==============================================================================
# 1. FUNCIÓN DE CARGA SEGURA DE DATOS DE USUARIO
#    (Resuelve el error FileNotFoundError y la privacidad)
# ==============================================================================

@st.cache_data
def load_user_data():
    """Carga y cachea los datos de usuario de forma segura desde st.secrets."""
    try:
        # Intenta leer el contenido CSV de la sección [user_data] en secrets
        csv_string = st.secrets["user_data"]["csv_content"]
        
        # Usa io.StringIO para que Pandas pueda leer el string como si fuera un archivo
        return pd.read_csv(io.StringIO(csv_string))
        
    except KeyError:
        st.error("❌ Error de configuración de Login: Asegúrate de tener las secciones [user_data] y 'csv_content' en secrets.toml.")
        return pd.DataFrame() 
    except Exception as e:
        st.error(f"❌ Error al procesar los datos de usuario desde secrets: {e}")
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

# ==============================================================================
# 2. IMPLEMENTACIÓN RAG (Generación Aumentada por Recuperación)
#    (Asegura que se usen tus PDFs en la carpeta 'docs/')
# ==============================================================================

@st.cache_resource
def load_pdf_knowledge(directory="docs"):
    """Carga el texto de todos los archivos PDF en el directorio especificado."""
    # En Streamlit Cloud, si la carpeta 'docs' no se subió a GitHub, esto fallará silenciosamente
    if not os.path.exists(directory):
        # st.warning(f"🚨 Advertencia: El directorio '{directory}' no existe. Base de conocimiento limitada (RAG inactivo).")
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
        st.sidebar.success(f"✅ Documentación personalizada cargada ({len(full_text)} archivos).")
        return "\n\n".join(full_text)
    else:
        # st.warning("⚠️ No se encontraron archivos PDF para cargar. Base de conocimiento limitada.")
        return ""

KNOWLEDGE_BASE_TEXT = load_pdf_knowledge()

# --- Reglamento Interior y Atribuciones (Instrucción Específica) ---

REGLAMENTO_TEXT = """
## ATRIBUCIONES INSTITUCIONALES Y REGLAMENTO INTERIOR
El **Asesor de Progob** debe recordar que la responsabilidad final del PAT recae **exclusivamente en la Unidad Responsable (UR)**. Tu rol es guiar, sugerir y revisar la coherencia con los documentos oficiales, no determinar metas.
"""

# --- Prompt de Sistema (Rol Corporativo y Restricción de Flujo) ---
# **Importante:** Este prompt controla el comportamiento de la IA.

SYSTEM_PROMPT_TEMPLATE = f"""
# ROL: ASESOR METODOLÓGICO PBR/MML DE LA OFICINA DE PROGRAMA DE GOBIERNO
Eres el **Asesor Metodológico PBR/MML de la Oficina de Programa de Gobierno y Mejora Regulatoria del H. Ayuntamiento de Veracruz**. 
Tu usuario es el Enlace de la Unidad Responsable: **{{area}}**.
Tu función es guiar al usuario paso a paso, utilizando la Metodología de Marco Lógico (MML) para elaborar su Programa Anual de Trabajo (PAT).

## INSTRUCCIONES DE FLUJO Y CONTROL (Estricto)
1.  **FLUJO ESTRICTO:** No avances al siguiente paso de la MML hasta que el usuario confirme su conformidad con una de las opciones numéricas que le presentes.
2.  **PRESENTACIÓN DE OPCIONES:** Al finalizar cada fase o sub-paso importante (Problema, Causas/Efectos, Medios/Fines, etc.), debes presentar opciones claras para avanzar, modificar o reiniciar.
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
# 3. FUNCIÓN PRINCIPAL DE CONEXIÓN CON LA IA
# ==============================================================================

def get_llm_response(area: str, user_query: str):
    """
    Conecta al motor de IA, inyectando el prompt con la info del área y el historial.
    """
    if not API_KEY:
        return "❌ Conexión fallida. Clave API no configurada correctamente en secrets.toml."

    # 1. Personalizar el SYSTEM_PROMPT con el área
    system_prompt = SYSTEM_PROMPT_TEMPLATE.replace("{{area}}", area)
    
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    
    # Se añade el System Prompt como primer mensaje
    messages = [
        {"role": "system", "content": system_prompt},
    ]
    
    # Añadir historial de chat previo para contexto (excluyendo el System Prompt del asistente)
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
        # 🚨 MENSAJE PERSONALIZADO: Reemplaza "Deepseek"
        with st.spinner("Revisando mi banco de datos y preguntando a Progob..."): 
            response = requests.post(API_URL, headers=headers, json=payload, timeout=90)
            response.raise_for_status()
        
        data = response.json()
        
        if data and 'choices' in data and data['choices']:
            return data['choices'][0]['message']['content']
        else:
            return f"⚠️ Respuesta vacía o inesperada. JSON: {data}"

    except requests.exceptions.HTTPError as e:
        return f"❌ Error de la API: {e}. Verifica la URL y la clave API."
    except Exception as e:
        return f"❌ Error de conexión o procesamiento: {e}"


# ==============================================================================
# 4. INTERFAZ DE STREAMLIT (Vista de Enlace y Admin)
# ==============================================================================

def enlace_view(user_name, area):
    """Vista principal para el enlace de la Unidad Responsable (Chat Style)."""
    
    st.title("Asesoría PbR/MML")
    st.subheader(f"Asistente de la Oficina de Programa de Gobierno para: **{area}**")

    # Mensaje inicial que se muestra solo una vez
    if 'chat_history' not in st.session_state:
        st.session_state.chat_history = []
        # Mensaje de bienvenida del personal de Progob
        initial_message = (
            f"¡Bienvenido(a), {user_name}! Soy el **Asesor Metodológico de la Oficina de Programa de Gobierno**.\n\n"
            f"Mi función es guiar a su Unidad Responsable (**{area}**) paso a paso en la elaboración del Programa Anual de Trabajo (PAT) con base en la Metodología de Marco Lógico (MML) y la documentación oficial del Ayuntamiento.\n\n"
            "**Fase 1: Diagnóstico - Problema Central**\n"
            "Por favor, ingresa el **Problema Central** que tu Unidad busca resolver. Recuerda que debe ser un déficit o una situación negativa, en una o dos oraciones."
        )
        st.session_state.chat_history.append(("assistant", initial_message))

    # Display del historial de chat
    st.markdown("---")
    for role, text in st.session_state.chat_history:
        display_name = "Asesor Progob" if role == "assistant" else user_name
        
        with st.chat_message(role, avatar="🧑‍💼" if role == "assistant" else "👤"):
            st.markdown(text)

    # st.chat_input (Cuadro de texto en la parte inferior)
    user_input = st.chat_input("Escribe tu Problema Central o tu opción (1, 2 o 3) para continuar...")

    if user_input:
        # 1. Agregar la consulta del usuario al historial primero
        st.session_state.chat_history.append(("user", user_input))
        
        # 2. Generar respuesta
        response_text = get_llm_response(area, user_input)
        
        # 3. Agregar la respuesta del asistente al historial
        st.session_state.chat_history.append(("assistant", response_text))
        
        # 4. Forzar re-ejecución para mostrar los nuevos mensajes
        st.rerun()

def admin_view(user_name):
    """Vista para el administrador."""
    st.title("Vista de Administrador - Oficina de Programa de Gobierno")
    st.info(f"Bienvenido, {user_name}. Aquí podrías gestionar usuarios, reportes o la base de conocimiento.")

# ==============================================================================
# 5. PUNTO DE ENTRADA (Manejo de Sesión y Login)
# ==============================================================================

def main():
    
    df_users = load_user_data()
    
    # Si la carga de usuarios falló o el DataFrame está vacío, no se puede continuar.
    if df_users.empty:
        st.stop()
    
    # Inicialización del estado de sesión
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
        # Vista de Login
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
                # Inicializa el historial solo al autenticar
                st.session_state.chat_history = [] 
                st.rerun()
            else:
                st.sidebar.error("Credenciales incorrectas.")

if __name__ == "__main__":
    main()
