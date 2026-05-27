import sys
from PyQt6.QtWidgets import QApplication
from config_manager import ConfigManager
from settings_dialog import SettingsDialog

def main():
    """
    Script de acceso directo para abrir únicamente el panel de configuración
    del asistente sin necesidad de inicializar o cargar los modelos de IA en segundo plano.
    """
    app = QApplication(sys.argv)
    
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
