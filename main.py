import os
import sys

# Force the X11 platform plugin (xcb) on Wayland to allow absolute window positioning.
# Modern Linux desktops running Wayland (like KDE Plasma or GNOME) run Xwayland by default.
if os.environ.get("XDG_SESSION_TYPE") == "wayland":
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

from PyQt6.QtWidgets import QApplication, QMessageBox
from config_manager import ConfigManager
from settings_dialog import SettingsDialog
from avatar_window import AvatarWindow

def main():
    # Inicializar la aplicación Qt
    app = QApplication(sys.argv)
    
    # Crear el gestor de configuración
    config_manager = ConfigManager()

    # Si la configuración no es válida al arrancar, abrir la ventana de configuración
    if not config_manager.is_valid():
        print("Configuración no válida o inexistente. Mostrando ventana de configuración...")
        
        # Mostrar un mensaje informativo
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setWindowTitle("Primer Arranque del Asistente")
        msg.setText(
            "Bienvenido al Asistente Virtual.\n\n"
            "Es necesario configurar los dispositivos de audio y "
            "especificar las rutas de los modelos de IA locales antes de comenzar."
        )
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()

        dialog = SettingsDialog(config_manager)
        if dialog.exec() != SettingsDialog.DialogCode.Accepted:
            print("Configuración cancelada. Saliendo de la aplicación.")
            sys.exit(0)

    # Si la configuración es válida, arrancar la ventana del avatar
    if config_manager.is_valid():
        window = AvatarWindow(config_manager)
        window.show()
        sys.exit(app.exec())
    else:
        print("Error: No se pudo configurar la aplicación correctamente. Saliendo.")
        sys.exit(1)

if __name__ == "__main__":
    main()
