# chatbot.py
# Asesor PbR/MML - H. Ayuntamiento de Veracruz 2022-2025
# Versión FINAL para Streamlit Cloud (con credenciales en secrets.toml)

import streamlit as st
import pandas as pd
import requests
import json
import os # Importar para referencia futura si se requieren otras variables de entorno

# --- CONFIGURACIÓN GENERAL ---
st.set_page_config(page_title="Asesor PbR/MML Veracruz", layout="wide")

# --- CLAVE API DE DEEPSEEK ---
# Lee la clave API de forma segura desde st.secrets
if "DEEPSEEK_API_KEY" not in st.secrets:
    # Esta parte se mantiene para dar una pista o fallback si falta la clave en Cloud
    DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "TU_CLAVE_DE_PRUEBA_O_ERROR")
else:
    DEEPSEEK_API_KEY = st.secrets["DEEPSEEK_API_KEY"]

# --- PROMPT MAESTRO (PERSONALIDAD DEL ASESOR) ---
SYSTEM_PROMPT = """
# ROL DE ASESOR METODOLÓGICO PBR/MML
**ROL:** Eres el **Asesor Metodológico PBR/MML del H. Ayuntamiento de Veracruz 2022-2025**. Eres experto en Gestión para Resultados (GpR), Metodología de Marco Lógico (MML), Indicadores de Desempeño (Módulo V), Transversalidad (Módulo VI) y Evaluación (Módulo VIII), conforme al Diplomado SHCP y Guía Técnica Municipal.

**META:** Guiar al Enlace paso a paso hasta obtener una Matriz de Indicadores para Resultados (MIR) coherente y un Calendario de Actividades, asegurando siempre la Lógica Vertical (Fin → Propósito → Componente → Actividad).

**REGLAS:**
1. Siempre cordial, profesional y alentador.
2. Valida checkpoints antes de avanzar (ej. no pases a Componentes sin Propósito validado).
3. Usa tablas Markdown claras y listas numeradas.
4. Todos los indicadores deben cumplir R-M-A-E-T (Relevante, Medible, Alcanzable, Específico, con Tiempo).
"""

# ----------------------------------------------------------------------
# 1. CARGA DE USUARIOS DESDE secrets.toml (Streamlit Cloud)
# ----------------------------------------------------------------------
def load_users():
    """Carga los usuarios desde secrets.toml (seguro y sin archivos)"""
    try:
        # Aseguramos que se lee la sección [users] del archivo secrets.toml
        df = pd.DataFrame({
            "username": st.secrets["users"]["username"],
            "password": st.secrets["users"]["password"],
            "role":     st.secrets["users"]["role"],
            "area":     st.secrets["users"]["area"],
            "nombre":   st.secrets["users"]["nombre"]
        })
        df["username"] = df["username"].str.strip().str.lower()
        # Nota: Ya no se eliminan las listas aquí, se asume que vienen del secrets.toml
        return df
    except KeyError:
        # Esto ocurre si falta la sección [users] o el archivo secrets.toml no existe/está mal formado
        st.error("Error al cargar usuarios. Verifique que exista la sección [users] en .streamlit/secrets.toml y que tenga las columnas correctas (username, password, role, area, nombre).")
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Error inesperado al cargar usuarios: {e}")
        return pd.DataFrame()

# ----------------------------------------------------------------------
# 2. AUTENTICACIÓN
# ----------------------------------------------------------------------
def authenticate(username, password, df_users):
    clean_user = username.strip().lower()
    user = df_users[(df_users['username'] == clean_user) & (df_users['password'] == password)]
    if not user.empty:
        return (
            user['role'].iloc[0].strip().lower(),
            user['nombre'].iloc[0].strip(),
            user['area'].iloc[0].strip()
        )
    return None, None, None

# ----------------------------------------------------------------------
# 3. CONEXIÓN A DEEPSEEK (API real)
# ----------------------------------------------------------------------
def get_deepseek_response(user_query: str):
    # Ya no se comprueba "TU_CLAVE_AQUI" aquí, solo si el valor es utilizable.
    if not DEEPSEEK_API_KEY or DEEPSEEK_API_KEY == "TU_CLAVE_DE_PRUEBA_O_ERROR":
        return "Error: Configura tu clave API de Deepseek en secrets.toml como `DEEPSEEK_API_KEY = \"sk-...\"`"

    url = "https://api.deepseek.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    
    # Se añade el historial de mensajes de la sesión para dar contexto al LLM
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    
    # Recuperar historial si existe (Opcional, si quieres que la conversación sea continua)
    # for msg in st.session_state.get('history', []):
    #     messages.append({"role": msg["role"], "content": msg["content"]})
    
    messages.append({"role": "user", "content": user_query})
    
    payload = {
        "model": "deepseek-chat",
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 1800
    }

    try:
        with st.spinner("Consultando a Deepseek…"):
            response = requests.post(url, headers=headers, json=payload, timeout=40)
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        return f"Error al conectar con Deepseek: {str(e)}"

# ----------------------------------------------------------------------
# 4. VISTA ENLACE (USUARIO NORMAL)
# ----------------------------------------------------------------------
def enlace_view(user_name, user_area):
    st.title(f"Asesoría PbR/MML | {user_area}")
    st.subheader(f"Bienvenido(a), {user_name} ¡Tu copiloto Deepseek está listo!")

    if 'pat' not in st.session_state:
        st.session_state.pat = {"fase": None, "problema": "", "proposito": "", "componentes": []}

    # --- Checkpoint inicial ---
    if st.session_state.pat["fase"] is None:
        st.markdown("**Asesor Deepseek:** ¿Cómo quieres empezar hoy?")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Iniciar con Diagnóstico (Árbol de Problemas)"):
                st.session_state.pat["fase"] = "diagnostico"
                st.session_state.respuesta = None # Limpiar respuesta anterior
                st.rerun()
        with col2:
            if st.button("Ya tengo mi Propósito → Ir directo a la MIR"):
                st.session_state.pat["fase"] = "proposito"
                st.session_state.respuesta = None # Limpiar respuesta anterior
                st.rerun()

    fase = st.session_state.pat["fase"]

    # FASE 1 – Diagnóstico / Problema Central
    if fase == "diagnostico":
        st.subheader("Fase 1 – Diagnóstico: Problema Central")
        problema = st.text_area("Describe el Problema Central que quieres resolver:", height=100, 
                                value=st.session_state.pat.get("problema", ""))
        
        if st.button("Analizar con Deepseek") and problema:
            st.session_state.pat["problema"] = problema # Guardar el problema
            with st.spinner("Analizando causas y efectos…"):
                query = f"Problema central: {problema}\nGenera un Árbol de Problemas con 3–5 causas directas y 3–5 efectos directos. Presenta todo en tabla Markdown."
                respuesta = get_deepseek_response(query)
                st.session_state.respuesta = respuesta
                st.rerun()

    # FASE 2 – Propósito
    # Solo mostrar si ya hay un problema definido (fase 'diagnostico') o si el usuario eligió empezar aquí ('proposito')
    if fase == "proposito" or (fase == "diagnostico" and st.session_state.pat.get("problema")):
        st.subheader("Fase 2 – Definición del Propósito")
        proposito = st.text_area("Escribe el Propósito de tu intervención (Objetivo General):", height=100,
                                 value=st.session_state.pat.get("proposito", ""))
        
        # Botón para generar indicador de Propósito
        if st.button("Validar Propósito y generar Indicador") and proposito:
            st.session_state.pat["proposito"] = proposito # Guardar el propósito
            with st.spinner("Validando coherencia y generando indicador R-M-A-E-T…"):
                query = f"Propósito propuesto: {proposito}\nValida su alineación con la lógica vertical, mejora la redacción si es necesario y genera un Indicador de Propósito completo (R-M-A-E-T) con fórmula, unidad, línea base, meta 2025, medios de verificación y supuestos. Presenta la información en tablas Markdown."
                respuesta = get_deepseek_response(query)
                st.session_state.respuesta = respuesta
                st.session_state.pat["fase"] = "componentes" # Avanzar fase
                st.rerun()

    # FASE 3 – Componentes (Se activará después de validar el Propósito)
    if fase == "componentes":
        st.subheader("Fase 3 – Definición de Componentes (Productos y Servicios)")
        # Lógica de componentes y actividades aquí (puedes expandir esta parte)
        st.info("Ya tienes tu Propósito validado. Ahora define los **Componentes** (productos/servicios clave) necesarios para lograrlo, junto con sus respectivos indicadores.")
        
        componente_input = st.text_area("Describe el Componente (ej: 'Vías primarias y secundarias rehabilitadas'):", height=50)
        
        if st.button("Generar Indicador de Componente") and componente_input:
             with st.spinner("Generando indicador R-M-A-E-T para el Componente…"):
                query = f"Propósito validado: {st.session_state.pat['proposito']}\nComponente propuesto: {componente_input}\nGenera un Indicador de Componente completo (R-M-A-E-T) con fórmula, unidad, línea base, meta 2025, medios de verificación y supuestos. Presenta la información en tablas Markdown."
                respuesta = get_deepseek_response(query)
                st.session_state.respuesta = respuesta
                st.session_state.pat["componentes"].append(componente_input) # Solo guardar el texto del componente
                st.rerun()

    # Mostrar siempre la última respuesta del asesor
    if st.session_state.get("respuesta"):
        st.markdown("---")
        st.markdown("### 💬 Asesoría Metodológica Deepseek")
        st.markdown(st.session_state.respuesta)
        st.markdown("---")


# ----------------------------------------------------------------------
# 5. VISTA ADMIN
# ----------------------------------------------------------------------
def admin_view(user_name):
    st.title(f"Panel Administrador | {user_name}")
    st.success("Acceso administrador concedido")
    df = load_users()
    if not df.empty:
        st.markdown("### Usuarios cargados desde `secrets.toml`")
        st.dataframe(df[['nombre', 'area', 'role', 'username']], height=600)
    else:
        st.error("No se pudieron cargar los usuarios")

# ----------------------------------------------------------------------
# 6. MAIN + LOGIN
# ----------------------------------------------------------------------
def main():
    df_users = load_users()

    if df_users.empty:
        # Si la carga de usuarios falló (por secrets mal configurados), no se puede continuar.
        st.stop()
    
    if 'authenticated' not in st.session_state:
        st.session_state.authenticated = False

    if st.session_state.authenticated:
        if st.session_state.role == "admin":
            admin_view(st.session_state.user_name)
        else:
            enlace_view(st.session_state.user_name, st.session_state.user_area)
            
        # Botón de cerrar sesión en la vista principal
        if st.sidebar.button("🔒 Cerrar Sesión"):
            st.session_state.clear()
            st.rerun()
            
    else:
        # Vista de Login
        st.sidebar.image("https://upload.wikimedia.org/wikipedia/commons/2/2c/Escudo_de_Veracruz.svg", width=100)
        st.sidebar.title("Asesor PbR/MML Veracruz")
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
                st.sidebar.error("Credenciales incorrectas")

if __name__ == "__main__":
    main()
