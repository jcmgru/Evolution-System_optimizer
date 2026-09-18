import os
import sys
import platform
import subprocess

# ==================================================================
#          NUCLEO UNIVERSAL EVOLUTION SYSTEM v2.0
#  COMPATIBILIDAD DETECTADA AUTOMÁTICAMENTE: WINDOWS / LINUX
# ==================================================================

PAYPAL_FUNDING = "juancamazo17@gmail.com"
GRASS_LINK = "https://app.grass.io/register?referralCode=xmpnmoiR2V4z7R4"

def mostrar_contrato_etico():
    print("=" * 60)
    print("         BIENVENIDO A EVOLUTION SYSTEM NETWORK v2.0")
    print("=" * 60)
    print(" Este software es una interfaz de colaboracion etica orientada")
    print(" al desarrollo responsable y el bienestar de los dispositivos.")
    print("\n ¿Que hara este programa en tu equipo?")
    print(" 1. Investigar componentes y diagnosticar el estado del hardware.")
    print(" 2. Solicitar tu permiso para corregir errores y eliminar virus.")
    print(" 3. Habilitar el puerto 8000 para telemetria cooperativa de IA.")
    print("\n [Opcional] Apoyo para la creacion de super servidores:")
    print(f" PayPal: {PAYPAL_FUNDING}")
    print("=" * 60)
    
    opcion = input(" ¿Aceptas unirte a la red y optimizar tu PC? (S/N): ").strip().upper()
    if opcion != 'S':
        print("[SISTEMA] Saliendo del instalador de forma segura.")
        sys.exit(0)

def diagnosticar_hardware(sistema_actual):
    print("\n" + "=" * 60)
    print("          ETAPA 1: INVESTIGACIÓN Y DIAGNÓSTICO NATIVO")
    print("=" * 60)
    print(f"[INFO] Sistema Operativo Detectado: {sistema_actual.upper()}")
    
    if sistema_actual == "windows":
        print("[INFO] Procesador Anfitrion:")
        os.system("wmic cpu get name, NumberOfCores, MaxClockSpeed")
        print("[INFO] Almacenamiento Detectado:")
        os.system("wmic diskdrive get model, size, status")
    elif sistema_actual == "linux":
        print("[INFO] Procesador Anfitrion:")
        os.system("lscpu | grep 'Model name\\|CPU(s):'")
        print("[INFO] Estado del Almacenamiento y Particiones:")
        os.system("df -h")

def reparar_y_desinfectar(sistema_actual):
    print("\n" + "=" * 60)
    print("             ADVERTENCIA DE SEGURIDAD Y PERMISOS")
    print("=" * 60)
    print(" El diagnóstico ha finalizado. El sistema puede buscar archivos")
    print(" corruptos, corregir errores logicos y ejecutar un escaneo de virus")
    print(" utilizando las herramientas oficiales y nativas del fabricante.")
    print("-" * 60)
    
    autoriza = input(" ¿Autorizas al sistema a realizar estas reparaciones? (S/N): ").strip().upper()
    if autoriza != 'S':
        print("[INFO] Reparaciones avanzadas omitidas por el usuario.")
        return

    print("\nEjecutando reparaciones autorizadas...")
    if sistema_actual == "windows":
        print("[1/2] Corrigiendo integridad de archivos (SFC)...")
        subprocess.run(["sfc", "/scannow"])
        print("[2/2] Escaneando amenazas con Windows Defender...")
        defender_path = "C:\\Program Files\\Windows Defender\\MpCmdRun.exe"
        if os.path.exists(defender_path):
            subprocess.run([defender_path, "-Scan", "-ScanType", "1"])
            
    elif sistema_actual == "linux":
        print("[1/2] Actualizando repositorios y corrigiendo paquetes rotos...")
        os.system("sudo apt-get update && sudo apt-get check")
        print("[2/2] Limpiando memoria cache residual del sistema...")
        os.system("sudo apt-get autoremove -y && sudo apt-get clean")
        
    print("[OK] Reparacion y desinfeccion completada con exito.\n")

def optimizar_y_desplegar_puerto(sistema_actual):
    print("=" * 60)
    print("      ETAPA 2: OPTIMIZACIÓN DE RED Y CONFIGURACIÓN DEL PUERTO")
    print("=" * 60)
    
    if sistema_actual == "windows":
        print("[1/2] Limpiando temporales de Windows y vaciando cache DNS...")
        os.system("del /s /f /q %windir%\\Temp\\*.* >nul 2>&1")
        os.system("ipconfig /flushdns >nul 2>&1")
        print("[2/2] Abriendo el puerto 8000 en el Firewall de Windows...")
        os.system("netsh advfirewall firewall add rule name=\"Evolution_8000\" dir=in action=allow protocol=TCP localport=8000 >nul 2>&1")
        
    elif sistema_actual == "linux":
        print("[1/2] Liberando memoria RAM en cache inactiva...")
        os.system("sync && echo 3 | sudo tee /proc/sys/vm/drop_caches > /dev/null")
        print("[2/2] Abriendo el puerto 8000 usando UFW (Uncomplicated Firewall)...")
        os.system("sudo ufw allow 8000/tcp > /dev/null 2>&1")

    print(f"[OK] Puerto 8000 expuesto. Red optimizada. Enlace de monetizacion Grass listo.")
    print("=" * 60)
    print(" ¡INSTALACIÓN COMPLETADA! GRACIAS POR COOPERAR CON EVOLUTION SYSTEM")
    print("=" * 60)
    
    # Redirige al usuario al panel de Grass para activar su nodo de red de internet
    if sistema_actual == "windows":
        os.system(f"start {GRASS_LINK}")
    elif sistema_actual == "linux":
        os.system(f"xdg-open {GRASS_LINK} > /dev/null 2>&1")

if __name__ == "__main__":
    # Deteccion automatica de la plataforma
    sistema = platform.system().lower()
    if sistema not in ["windows", "linux"]:
        print(f"[ERROR] Sistema operativo {sistema} no soportado actualmente.")
        sys.exit(1)
        
    mostrar_contrato_etico()
    diagnosticar_hardware(sistema)
    reparar_y_desinfectar(sistema)
    optimizar_y_desplegar_puerto(sistema)
