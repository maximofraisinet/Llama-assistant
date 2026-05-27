import os
import sys

# Force the X11 platform plugin (xcb) on Wayland to allow absolute window positioning.
# Modern Linux desktops running Wayland (like KDE Plasma or GNOME) run Xwayland by default.
if os.environ.get("XDG_SESSION_TYPE") == "wayland":
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon
from config_manager import ConfigManager
from settings_dialog import SettingsDialog

def main():
    """
    Script de acceso directo para abrir únicamente el panel de configuración
    del asistente sin necesidad de inicializar o cargar los modelos de IA en segundo plano.
    """
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon("/home/maximo/Código/Python/Llama-assistant/avatar/icon.svg"))
    
    # Cargar el gestor de configuración
    config_manager = ConfigManager()
    
    # Crear y mostrar el diálogo
    dialog = SettingsDialog(config_manager)
    dialog.setWindowTitle("Panel de Configuración del Asistente")
    
    # Ejecutar el diálogo
    dialog.exec()
    print("Configuración finalizada.")

if __name__ == "__main__":
    main()
