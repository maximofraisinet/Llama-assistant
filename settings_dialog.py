import os
import sounddevice as sd
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, 
    QLineEdit, QPushButton, QFileDialog, QMessageBox, QGroupBox, QFormLayout
)
from PyQt6.QtCore import Qt

class SettingsDialog(QDialog):
    """
    Diálogo para configurar los dispositivos de audio (micrófono y salida)
    y las rutas locales del modelo LLM (GGUF) y de Kokoro TTS (ONNX y BIN).
    """
    def __init__(self, config_manager, parent=None):
        super().__init__(parent)
        self.config_manager = config_manager
        self.setWindowTitle("Configuración del Asistente Virtual")
        self.resize(550, 400)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)

        # 1. Grupo de Audio
        audio_group = QGroupBox("Dispositivos de Audio")
        audio_layout = QFormLayout(audio_group)

        self.input_combo = QComboBox()
        self.output_combo = QComboBox()
        
        self.populate_audio_devices()
        
        audio_layout.addRow(QLabel("Dispositivo de Entrada (Micrófono):"), self.input_combo)
        audio_layout.addRow(QLabel("Dispositivo de Salida (Altavoces):"), self.output_combo)
        main_layout.addWidget(audio_group)

        # 1.5. Grupo de Posicionamiento
        pos_group = QGroupBox("Ubicación del Avatar")
        pos_layout = QFormLayout(pos_group)
        self.position_combo = QComboBox()
        self.position_combo.addItem("Esquina Inferior Derecha", "bottom_right")
        self.position_combo.addItem("Esquina Inferior Izquierda", "bottom_left")
        self.position_combo.addItem("Esquina Superior Derecha", "top_right")
        self.position_combo.addItem("Esquina Superior Izquierda", "top_left")
        self.position_combo.addItem("Centro de la Pantalla", "center")
        
        # Seleccionar posición guardada
        saved_pos = self.config_manager.avatar_position
        pos_idx = self.position_combo.findData(saved_pos)
        if pos_idx != -1:
            self.position_combo.setCurrentIndex(pos_idx)
            
        pos_layout.addRow(QLabel("Posición Inicial en Pantalla:"), self.position_combo)
        main_layout.addWidget(pos_group)

        # 2. Grupo de Modelos de IA
        models_group = QGroupBox("Rutas de Modelos Locales")
        models_layout = QFormLayout(models_group)

        # LLM GGUF Path
        llm_layout = QHBoxLayout()
        self.llm_path_edit = QLineEdit()
        self.llm_path_edit.setText(self.config_manager.llm_model_path or "")
        llm_btn = QPushButton("Examinar...")
        llm_btn.clicked.connect(self.select_llm_model)
        llm_layout.addWidget(self.llm_path_edit)
        llm_layout.addWidget(llm_btn)
        models_layout.addRow(QLabel("Modelo LLM (.gguf):"), llm_layout)

        # Kokoro ONNX Path
        kokoro_onnx_layout = QHBoxLayout()
        self.kokoro_onnx_edit = QLineEdit()
        self.kokoro_onnx_edit.setText(self.config_manager.kokoro_onnx_path or "")
        kokoro_onnx_btn = QPushButton("Examinar...")
        kokoro_onnx_btn.clicked.connect(self.select_kokoro_onnx)
        kokoro_onnx_layout.addWidget(self.kokoro_onnx_edit)
        kokoro_onnx_layout.addWidget(kokoro_onnx_btn)
        models_layout.addRow(QLabel("Kokoro ONNX (.onnx):"), kokoro_onnx_layout)

        # Kokoro Voices BIN Path
        kokoro_voices_layout = QHBoxLayout()
        self.kokoro_voices_edit = QLineEdit()
        self.kokoro_voices_edit.setText(self.config_manager.kokoro_voices_path or "")
        kokoro_voices_btn = QPushButton("Examinar...")
        kokoro_voices_btn.clicked.connect(self.select_kokoro_voices)
        kokoro_voices_layout.addWidget(self.kokoro_voices_edit)
        kokoro_voices_layout.addWidget(kokoro_voices_btn)
        models_layout.addRow(QLabel("Archivo de Voces Kokoro (.bin):"), kokoro_voices_layout)

        main_layout.addWidget(models_group)

        # 3. Botones Aceptar / Cancelar
        btn_layout = QHBoxLayout()
        save_btn = QPushButton("Guardar Configuración")
        save_btn.setStyleSheet("font-weight: bold; background-color: #2e7d32; color: white; padding: 6px;")
        save_btn.clicked.connect(self.save_configuration)
        
        cancel_btn = QPushButton("Cancelar")
        cancel_btn.clicked.connect(self.reject)
        
        btn_layout.addStretch()
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(save_btn)
        
        main_layout.addLayout(btn_layout)

    def populate_audio_devices(self):
        """Busca y añade los dispositivos a los combos diferenciando Entrada/Salida."""
        try:
            devices = sd.query_devices()
        except Exception as e:
            print(f"Error al obtener dispositivos de audio: {e}")
            devices = []

        self.input_devices_map = {}
        self.output_devices_map = {}

        # Combos vacíos
        self.input_combo.clear()
        self.output_combo.clear()

        # Configurar por defecto (None representa el dispositivo del sistema)
        self.input_combo.addItem("Default Mic / Micrófono Predeterminado", None)
        self.output_combo.addItem("Default Output / Salida Predeterminada", None)

        input_index_to_select = -1
        output_index_to_select = -1

        saved_input = self.config_manager.input_device_name
        saved_output = self.config_manager.output_device_name

        idx_in = 1
        idx_out = 1

        for i, dev in enumerate(devices):
            name = dev.get('name', 'Dispositivo Desconocido')
            host_api = dev.get('hostapi', 0)
            try:
                api_name = sd.query_hostapis(host_api).get('name', '')
                display_name = f"{name} ({api_name})"
            except Exception:
                display_name = name

            # Filtrar dispositivos con canales de entrada
            if dev.get('max_input_channels', 0) > 0:
                self.input_combo.addItem(display_name, name)
                self.input_devices_map[name] = display_name
                if saved_input == name:
                    input_index_to_select = idx_in
                idx_in += 1

            # Filtrar dispositivos con canales de salida
            if dev.get('max_output_channels', 0) > 0:
                self.output_combo.addItem(display_name, name)
                self.output_devices_map[name] = display_name
                if saved_output == name:
                    output_index_to_select = idx_out
                idx_out += 1

        # Seleccionar dispositivo guardado o el por defecto
        if input_index_to_select != -1:
            self.input_combo.setCurrentIndex(input_index_to_select)
        else:
            self.input_combo.setCurrentIndex(0)

        if output_index_to_select != -1:
            self.output_combo.setCurrentIndex(output_index_to_select)
        else:
            self.output_combo.setCurrentIndex(0)

    def select_llm_model(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Seleccionar Modelo LLM GGUF", "", "Modelos Llama GGUF (*.gguf)"
        )
        if file_path:
            self.llm_path_edit.setText(file_path)

    def select_kokoro_onnx(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Seleccionar Modelo Kokoro ONNX", "", "Modelos ONNX (*.onnx)"
        )
        if file_path:
            self.kokoro_onnx_edit.setText(file_path)

    def select_kokoro_voices(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Seleccionar Archivo de Voces Kokoro", "", "Voces BIN (*.bin)"
        )
        if file_path:
            self.kokoro_voices_edit.setText(file_path)

    def save_configuration(self):
        """Valida las rutas y guarda la configuración."""
        llm_path = self.llm_path_edit.text().strip()
        onnx_path = self.kokoro_onnx_edit.text().strip()
        voices_path = self.kokoro_voices_edit.text().strip()

        # Validaciones de archivos
        errors = []
        if not llm_path or not os.path.isfile(llm_path):
            errors.append("- El archivo del modelo LLM (.gguf) no existe o no se ha seleccionado.")
        if not onnx_path or not os.path.isfile(onnx_path):
            errors.append("- El archivo del modelo Kokoro ONNX (.onnx) no existe o no se ha seleccionado.")
        if not voices_path or not os.path.isfile(voices_path):
            errors.append("- El archivo de voces de Kokoro (.bin) no existe o no se ha seleccionado.")

        if errors:
            QMessageBox.warning(
                self, 
                "Error de Configuración", 
                "Por favor, corrige los siguientes problemas antes de guardar:\n\n" + "\n".join(errors)
            )
            return

        # Obtener valores seleccionados de los combos (nombres de dispositivo y posición)
        input_name = self.input_combo.currentData()
        output_name = self.output_combo.currentData()
        pos_name = self.position_combo.currentData()
        
        self.config_manager.input_device_name = input_name
        self.config_manager.output_device_name = output_name
        self.config_manager.avatar_position = pos_name
        self.config_manager.llm_model_path = llm_path
        self.config_manager.kokoro_onnx_path = onnx_path
        self.config_manager.kokoro_voices_path = voices_path

        # Guardar en archivo
        if self.config_manager.save():
            QMessageBox.information(self, "Éxito", "Configuración guardada correctamente.")
            self.accept()
        else:
            QMessageBox.critical(self, "Error", "No se pudo escribir el archivo de configuración.")
