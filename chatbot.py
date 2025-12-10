import streamlit as st
import pandas as pd
import os
import json
import io
import requests # <-- IMPORTANTE: Necesario para la conexión a la API

# --- CONFIGURACIÓN GENERAL ---
st.set_page_config(page_title="Asesor PbR/MML Veracruz", layout="wide")

# Nombres de archivo que buscaremos 
# CORRECCIÓN: Simplificamos el nombre a la versión más común y en minúsculas.
USERS_FILE_NAME = "users.xlsx" 

# Clave API de Deepseek (¡REEMPLAZA ESTA CADENA CON TU CLAVE REAL!)
DEEPSEEK_API_KEY = "sk-266e71790bed476bb2c60a322090bf03" 

# --- DEFINICIÓN DEL PROMPT MAESTRO (PERSONALIDAD DEL ASESOR) ---

SYSTEM_PROMPT = """
# ROL DE ASESOR METODOLÓGICO PBR/MML
**ROL:** Eres el **Asesor Metodológico PBR/MML del H. Ayuntamiento de Veracruz 2022-2025**. Eres un experto en la **Gestión para Resultados (GpR)**, **Metodología de Marco Lógico (MML)**, **Indicadores de Desempeño** (Módulo V), **Transversalidad** (Módulo VI) y **Evaluación** (Módulo VIII), conforme al Diplomado de la SHCP y la Guía Técnica Municipal. 

**META:** Guiar al Enlace de Unidad Responsable (UR) paso a paso hasta obtener una **Matriz de Indicadores para Resultados (MIR)** coherente y un **Calendario de Actividades** detallado, asegurando la **Lógica Vertical** (Fin -> Propósito -> Componente -> Actividad).

**REGLAS DE INTERACCIÓN:**
1.  **Cordialidad:** Responde siempre en un tono profesional, didáctico y alentador.
2.  **Flexibilidad y Checkpoints:** Permite al usuario avanzar o saltar fases, pero siempre aplica una **Validación de Checkpoint** solicitando la información faltante (ej. el Propósito) para asegurar la coherencia metodológica antes de continuar.
3.  **Formato:** Proporciona los resultados (MIR, Árbol, Calendario) en formato de **Tablas Markdown** o listas numeradas claras.
4.  **Criterios de Calidad:** Insiste en que los Indicadores sean **R-M-A-E-T** (Relevantes, Medibles, Alcanzables, Específicos y con Tiempo).
"""

# --------------------------------------------------------------------------
# A. FUNCIONES CENTRALES: Carga de Usuarios y Conexión REAL a Deepseek
# --------------------------------------------------------------------------

def load_users():
    """
    Carga el listado de usuarios, intentando encontrar el archivo por diferentes nombres 
    y corrige nombres de columnas.
    """
    # Nombres posibles del archivo que vamos a buscar (incluyendo la variable global)
    possible_names = [
        USERS_FILE_NAME,
        "users.csv",              
        "usuarios.xlsx",
        "usuarios.csv",
    ]
    
    found_file = None
    # CORRECCIÓN DE ROBUSTEZ: Intentamos encontrar el archivo
    for name in possible_names:
        if os.path.exists(name.lower()):
            found_file = name.lower()
            break
        if os.path.exists(name): # Buscamos el nombre tal cual
             found_file = name
             break

    if found_file:
        try:
            # 1. Intentar cargar como CSV o Excel
            if found_file.endswith(('.xlsx', '.xls')):
                 df = pd.read_excel(found_file, engine='openpyxl')
            else:
                # Intentar leer con distintas separaciones para CSV
                try:
                    df = pd.read_csv(found_file, encoding='utf-8')
                    if len(df.columns) == 1: # Si solo hay una columna, reintentar con ';'
                        df = pd.read_csv(found_file, sep=';', encoding='utf-8')
                except:
                    # Último recurso: latin1 y punto y coma
                    df = pd.read_csv(found_file, sep=';', encoding='latin1')
                 
        except Exception as e:
            # Error de formato/lectura de Pandas
            st.error(f"Error al procesar el archivo '{found_file}'. Revise el formato. Error: {e}")
            return pd.DataFrame()

        # *** CORRECCIÓN CRÍTICA: NORMALIZAR NOMBRES DE COLUMNAS ***
        # SOLUCIÓN al AttributeError: Se convierte explícitamente a string antes de usar .str
        try:
            df.columns = df.columns.astype(str).str.strip().str.lower()
        except Exception as e:
            st.error(f"Error al normalizar nombres de columna: {e}. Asegúrese de que el archivo tenga encabezados válidos.")
            return pd.DataFrame()
        # **********************************************************
        
        return df
    
    # Si ningún archivo fue encontrado
    return pd.DataFrame() # Devuelve DataFrame vacío para evitar crasheo en login


def authenticate(username, password, df_users):
    """Verifica credenciales y devuelve el rol, nombre y área del usuario."""
    
    # Aseguramos que las credenciales de entrada también estén limpias
    clean_username = username.strip().lower()
    
    # La columna 'username' ya está en minúsculas gracias a load_users()
    user = df_users[(df_users['username'] == clean_username) & (df_users['password'] == password)]
    
    if not user.empty:
        # Usar str() para asegurar que el tipo de dato sea string
        role = str(user['role'].iloc[0]).strip().lower() if 'role' in user.columns else 'enlace' 
        name = str(user['nombre'].iloc[0]).strip() if 'nombre' in user.columns else 'Usuario'
        area = str(user['area'].iloc[0]).strip() if 'area' in user.columns else 'Sin Área'
        return role, name, area
    return None, None, None

def get_deepseek_response(system_prompt: str, user_query: str):
    """
    Función REAL para la conexión a la API de Deepseek usando la librería requests.
    """
    global DEEPSEEK_API_KEY
    
    # 1. Verificar la clave API
    if DEEPSEEK_API_KEY == "sk-266e71790bed476bb2c60a322090bf03" or not DEEPSEEK_API_KEY:
        # Se muestra un mensaje de error y se devuelve una respuesta de simulación forzada.
        st.error("🚨 ERROR: Debes ingresar tu clave API de Deepseek en la variable DEEPSEEK_API_KEY o cambiar la clave por defecto.")
        return "❌ Conexión fallida. Por favor, configura tu clave API de Deepseek para continuar y deshabilitar el modo simulación."
    
    # 2. Configuración de la API (compatible con OpenAI)
    API_URL = "https://api.deepseek.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    
    # 3. Construir el historial de mensajes (Sistema + Usuario actual)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_query}
    ]
    
    # 4. Payload (Cuerpo de la solicitud)
    payload = {
        "model": "deepseek-chat", # Modelo optimizado para chat/asistencia
        "messages": messages,
        "temperature": 0.7,      
        "max_tokens": 1500       
    }
    
    try:
        # Mostrar un Spinner mientras se conecta
        with st.spinner("💻 Conectando a Deepseek y generando respuesta..."):
            response = requests.post(API_URL, headers=headers, json=payload, timeout=30)
            response.raise_for_status() # Lanza una excepción para errores 4xx/5xx
        
        data = response.json()
        
        # 5. Procesar la respuesta
        if data and 'choices' in data and data['choices']:
            # Se devuelve el contenido del mensaje del asistente
            return data['choices'][0]['message']['content']
        else:
            st.warning(f"⚠️ Respuesta vacía o inesperada de Deepseek. Código: {response.status_code}")
            return f"⚠️ Respuesta vacía de Deepseek. Código de estado: {response.status_code}"

    except requests.exceptions.HTTPError as e:
        st.error(f"❌ Error HTTP (Deepseek): {response.status_code} - {response.text}")
        return f"❌ Error de la API de Deepseek. (Código: {response.status_code}). Verifica tu clave API y saldo."
    except requests.exceptions.RequestException as e:
        st.error(f"❌ Error de conexión de red: {e}")
        return f"❌ Error de conexión con Deepseek. Asegúrate de tener conexión a internet."
    except Exception as e:
        st.error(f"❌ Error desconocido al procesar la respuesta: {e}")
        return "❌ Error interno. Revisa el código de procesamiento de la respuesta."

# --------------------------------------------------------------------------
# B. VISTA DEL ASESOR (ENLACE)
# --------------------------------------------------------------------------

def enlace_view(user_name, user_area):
    """Interfaz principal del Asesor PbR/MML para los Enlaces."""
    st.title(f"Asesoría PbR/MML | Unidad Responsable: {user_area}")
    st.subheader(f"Bienvenido(a), {user_name}. Tu copiloto Deepseek está listo.")
    
    if 'pat_en_curso' not in st.session_state:
        st.session_state['pat_en_curso'] = {"fase": None, "problema": None, "proposito": None, "componentes": []}
        
    st.markdown("---")
    
    # Checkpoint inicial de flexibilidad
    if st.session_state['pat_en_curso']['fase'] is None:
        st.markdown(f"**Asesor Deepseek:** Mi rol es guiarte. ¿Deseas iniciar con el **Diagnóstico (Árbol de Problemas)** o ya tienes definido tu **Propósito**?")
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("▶️ 1. Iniciar con el Diagnóstico (MML Completo)"):
                st.session_state['pat_en_curso']['fase'] = 'Diagnostico_Problema'
                st.session_state['deepseek_response'] = None
                st.rerun() 
        with col2:
            if st.button("🚀 2. Avanzar al Propósito (Checkpoint)"):
                st.session_state['pat_en_curso']['fase'] = 'Propósito_Alineacion'
                st.session_state['deepseek_response'] = None
                st.rerun() 
        st.markdown("---")
        
    fase = st.session_state['pat_en_curso']['fase']

    # Fases de Asesoría
    if fase == 'Diagnostico_Problema':
        st.subheader("Fase 1: Diagnóstico - Problema Central")
        problema_propuesto = st.text_area("Ingresa tu Problema Central (el déficit que quieres resolver):", height=50, key="input_problema")
        
        if st.button("Enviar a Deepseek (Evaluar Problema)"):
            if problema_propuesto:
                query_deepseek = f"Mi problema central es: {problema_propuesto}. Ahora, como experto en MML, define 3 Causas Directas y 3 Efectos de este problema, y preséntalos en formato de lista para el Árbol de Problemas. Guíame para transformarlo en Árbol de Objetivos. "
                response = get_deepseek_response(SYSTEM_PROMPT, query_deepseek) 
                
                st.session_state['pat_en_curso']['problema'] = problema_propuesto
                st.session_state['deepseek_response'] = response
                st.session_state['pat_en_curso']['fase'] = 'Propósito_Alineacion' # Mover a la siguiente fase
                st.rerun()
            else:
                st.warning("Por favor, ingresa el problema central.")
    
    elif fase == 'Propósito_Alineacion':
        st.subheader("Fase 2: Propósito y Alineación (Checkpoint)")
        
        # Si ya se evaluó un problema, mostrarlo
        if st.session_state['pat_en_curso']['problema']:
             st.info(f"Problema Central Identificado: **{st.session_state['pat_en_curso']['problema']}**")
             st.markdown("---")

        proposito_propuesto = st.text_area("Ingresa el Propósito de tu intervención (Objetivo General):", height=50, key="input_proposito")
        
        if st.button("Validar Propósito y Continuar"):
            if proposito_propuesto:
                query_deepseek = f"Quiero definir el Propósito de mi intervención: {proposito_propuesto}. Por favor, evalúa su coherencia con la Lógica Vertical. Luego, sugiere un borrador de Indicador del Propósito (asegurando criterios RMAE-T) y un resumen de las Columnas de la MIR (Medios de Verificación y Supuestos) para esta etapa. Finalmente, indícame el siguiente paso: la definición de Componentes."
                response = get_deepseek_response(SYSTEM_PROMPT, query_deepseek) 
                
                st.session_state['pat_en_curso']['proposito'] = proposito_propuesto
                st.session_state['deepseek_response'] = response
                st.session_state['pat_en_curso']['fase'] = 'Componentes' # Mover a la siguiente fase
                st.rerun()
            else:
                st.warning("Por favor, ingresa el Propósito.")

    elif fase == 'Componentes':
        st.subheader("Fase 3: Componentes (Resultados Directos)")
        st.info(f"Propósito en curso: **{st.session_state['pat_en_curso']['proposito']}**")
        
        # Aquí se podría implementar una entrada para múltiples componentes o una sola
        componente_propuesto = st.text_area("Ingresa el Componente 1 (el bien/servicio que entregarás):", height=50, key="input_componente")
        
        if st.button("Evaluar Componente y Sugerir Actividades"):
            if componente_propuesto:
                # Agregamos el componente para el estado de sesión (simplificado)
                st.session_state['pat_en_curso']['componentes'].append(componente_propuesto)
                
                query_deepseek = f"Mi Propósito es: {st.session_state['pat_en_curso']['proposito']}. El Componente propuesto es: {componente_propuesto}. Evalúa la coherencia entre ambos. Luego, sugiere: 1) Un borrador de Indicador para este Componente (RMAE-T) y 2) Una lista de 3 a 5 Actividades para producir este Componente."
                response = get_deepseek_response(SYSTEM_PROMPT, query_deepseek) 
                
                st.session_state['deepseek_response'] = response
                st.rerun()
            else:
                st.warning("Por favor, ingresa el Componente.")

    # Mostrar la respuesta del asesor (se mantiene visible después de cada acción)
    if 'deepseek_response' in st.session_state and st.session_state['deepseek_response']:
        st.markdown("### Asesoría Metodológica de Deepseek")
        # El contenido de la respuesta del LLM ya viene en formato Markdown
        st.markdown(st.session_state['deepseek_response'])

# --------------------------------------------------------------------------
# C. VISTA DEL ADMINISTRADOR (GESTIÓN DE USUARIOS)
# --------------------------------------------------------------------------

def admin_view(user_name):
    """Interfaz de administración para la gestión de usuarios."""
    st.title(f"Panel de Administrador | {user_name}")
    st.subheader("Gestión de Usuarios y Supervisión de PATs")

    # Cargar datos actuales
    df_users = load_users()

    # --- 1. GESTIÓN DE USUARIOS (Carga/Descarga) ---
    st.markdown("### 1. Control de Listado de Enlaces")
    
    col1, col2 = st.columns(2)

    with col1:
        # Descargar listado de usuarios
        if not df_users.empty:
            csv = df_users.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="⬇️ Descargar Listado de Usuarios (.csv)",
                data=csv,
                file_name='usuarios_veracruz_actual.csv',
                mime='text/csv',
                help="Exporta la lista actual de usuarios con todas las columnas."
            )
        st.write(f"Usuarios actuales en el sistema: **{len(df_users)}**")
        
    with col2:
        # Subir nuevo listado de usuarios (Excel o CSV)
        uploaded_file = st.file_uploader("⬆️ Subir/Actualizar Listado de Usuarios (.xlsx o .csv)", type=['csv', 'xlsx'])
        if uploaded_file is not None:
            try:
                # Usar pandas para leer el archivo subido
                if uploaded_file.name.endswith('.csv'):
                    # Intentar leer con distintas separaciones
                    try:
                         new_df = pd.read_csv(uploaded_file, encoding='utf-8')
                    except:
                         uploaded_file.seek(0) # Resetear puntero
                         new_df = pd.read_csv(uploaded_file, sep=';', encoding='utf-8')
                else:
                    new_df = pd.read_excel(uploaded_file, engine='openpyxl')
                
                # Normalizar columnas del nuevo archivo ANTES de validar
                new_df.columns = new_df.columns.astype(str).str.strip().str.lower()

                # Validar columnas mínimas
                required_cols = ['username', 'password', 'role']
                
                if all(col in new_df.columns for col in required_cols):
                    # Guardar el archivo localmente con el nombre USERS_FILE_NAME
                    new_df.to_csv(USERS_FILE_NAME, index=False, encoding='utf-8')
                    st.success(f"¡Listado de usuarios actualizado! Se cargaron **{len(new_df)}** registros. (Guardado como {USERS_FILE_NAME})")
                    st.balloons()
                    st.rerun()
                else:
                    st.error(f"El archivo debe contener las columnas: {', '.join(required_cols)} (ignorando mayúsculas y espacios).")

            except Exception as e:
                st.error(f"Error al procesar el archivo subido. Error: {e}")

    # --- 2. SUPERVISIÓN DE PATS ---
    st.markdown("### 2. Supervisión de Programas Anuales de Trabajo (PATs)")
    st.warning("🚨 **PENDIENTE DE INTEGRAR:** Aquí se requiere la integración con Google Drive para leer y mostrar el resumen de los PATs de todos los enlaces.")
    
    # Se muestra un resumen de usuarios para referencia
    if not df_users.empty:
        st.markdown("**Vista Previa de Usuarios**")
        # Asegurarse de que las columnas existan antes de mostrarlas
        cols_to_show = [col for col in ['nombre', 'area', 'role', 'username'] if col in df_users.columns]
        if cols_to_show:
            st.dataframe(df_users[cols_to_show].sort_values('role', ascending=False), height=200)

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
            enlace_view(st.session_state['user_name'], st.session_state['user_area'])
    else:
        # PANTALLA DE LOGIN
        st.sidebar.title("Bienvenido al Asesor PbR/MML")
        st.sidebar.markdown("---")
        username = st.sidebar.text_input("Usuario (Correo)", key="login_user")
        password = st.sidebar.text_input("Contraseña", type="password", key="login_pass")
        
        if st.sidebar.button("🔐 Ingresar"):
            if df_users.empty:
                # El mensaje de error ya se muestra en load_users si hay un problema
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
        
        # Mensaje de ayuda inicial si no hay usuarios (solo visible si df_users está vacío)
        if df_users.empty:
            st.warning(f"⚠️ **ATENCIÓN:** El listado de usuarios no ha sido cargado o el archivo está dañado. Por favor, asegúrese de que exista un archivo como `{USERS_FILE_NAME}` o `users.csv` en la misma carpeta del repositorio de GitHub.")


if __name__ == "__main__":
    main()