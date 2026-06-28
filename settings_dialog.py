import os
import sounddevice as sd
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, 
    QLineEdit, QPushButton, QFileDialog, QMessageBox, QGroupBox, QFormLayout, QCheckBox, QTextEdit, QSpinBox
)
from PyQt6.QtCore import Qt

class SettingsDialog(QDialog):
    """
    Dialog to configure audio devices (microphone and speakers),
    avatar preferences, and local AI model paths (LLM and Kokoro TTS).
    """
    def __init__(self, config_manager, parent=None):
        super().__init__(parent)
        self.config_manager = config_manager
        self.setWindowTitle("Virtual Assistant Settings")
        self.resize(580, 580)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)

        # 1. Audio Group
        audio_group = QGroupBox("Audio Devices")
        audio_layout = QFormLayout(audio_group)

        self.input_combo = QComboBox()
        self.output_combo = QComboBox()
        
        self.populate_audio_devices()
        
        audio_layout.addRow(QLabel("Input Device (Microphone):"), self.input_combo)
        audio_layout.addRow(QLabel("Output Device (Speakers):"), self.output_combo)
        main_layout.addWidget(audio_group)

        # 1.5. General Preferences Group
        pref_group = QGroupBox("General Preferences")
        pref_layout = QFormLayout(pref_group)
        self.position_combo = QComboBox()
        self.position_combo.addItem("Bottom Right", "bottom_right")
        self.position_combo.addItem("Bottom Left", "bottom_left")
        self.position_combo.addItem("Top Right", "top_right")
        self.position_combo.addItem("Top Left", "top_left")
        self.position_combo.addItem("Center", "center")
        
        # Prefill saved position
        saved_pos = self.config_manager.avatar_position
        pos_idx = self.position_combo.findData(saved_pos)
        if pos_idx != -1:
            self.position_combo.setCurrentIndex(pos_idx)
            
        pref_layout.addRow(QLabel("Initial Avatar Position:"), self.position_combo)

        # Active Avatar Selection with scanning & syntax validation
        self.avatar_combo = QComboBox()
        valid_avatars, invalid_avatars = self.scan_avatars()
        
        if invalid_avatars:
            error_msg = ""
            for folder, errors in invalid_avatars.items():
                error_msg += f"Folder '{folder}':\n"
                for err in errors:
                    error_msg += f"  - {err}\n"
                error_msg += "\n"
            QMessageBox.warning(
                self,
                "Avatar Validation Warning",
                "Issues with file names or syntax were detected in some avatar folders, and they will not be listed:\n\n" + error_msg
            )
            
        for av in valid_avatars:
            self.avatar_combo.addItem(av, av)
            
        saved_avatar = self.config_manager.avatar_name
        avatar_idx = self.avatar_combo.findData(saved_avatar)
        if avatar_idx != -1:
            self.avatar_combo.setCurrentIndex(avatar_idx)
        else:
            if self.avatar_combo.count() > 0:
                self.avatar_combo.setCurrentIndex(0)
                
        pref_layout.addRow(QLabel("Active Avatar:"), self.avatar_combo)
        
        # GPU acceleration checkbox
        self.gpu_checkbox = QCheckBox("Use hardware GPU acceleration (Nvidia CUDA)")
        self.gpu_checkbox.setChecked(self.config_manager.use_gpu)
        pref_layout.addRow(self.gpu_checkbox)
        
        # Context window spin box
        self.context_spin = QSpinBox()
        self.context_spin.setRange(512, 32768)
        self.context_spin.setSingleStep(512)
        self.context_spin.setValue(self.config_manager.llm_n_ctx)
        pref_layout.addRow(QLabel("Context Window (Tokens):"), self.context_spin)
        
        # Whisper model size combo box
        self.whisper_combo = QComboBox()
        self.whisper_combo.addItem("tiny (~1 GB RAM/VRAM, Very Fast)", "tiny")
        self.whisper_combo.addItem("base (~2 GB RAM/VRAM, Fast & Balanced)", "base")
        self.whisper_combo.addItem("small (~4 GB RAM/VRAM, Medium Precision)", "small")
        self.whisper_combo.addItem("medium (~8 GB RAM/VRAM, High Precision)", "medium")
        self.whisper_combo.addItem("large-v3 (~16 GB RAM/VRAM, Maximum Precision)", "large-v3")
        
        # Pre-select Whisper size
        saved_whisper = self.config_manager.whisper_model_size
        whisper_idx = self.whisper_combo.findData(saved_whisper)
        if whisper_idx != -1:
            self.whisper_combo.setCurrentIndex(whisper_idx)
        else:
            self.whisper_combo.setCurrentIndex(1) # base by default
            
        pref_layout.addRow(QLabel("Whisper STT Model Size:"), self.whisper_combo)
        
        main_layout.addWidget(pref_group)

        # 2. Local Models Group
        models_group = QGroupBox("Local Model Paths")
        models_layout = QFormLayout(models_group)

        # LLM GGUF Path
        llm_layout = QHBoxLayout()
        self.llm_path_edit = QLineEdit()
        self.llm_path_edit.setText(self.config_manager.llm_model_path or "")
        llm_btn = QPushButton("Browse...")
        llm_btn.clicked.connect(self.select_llm_model)
        llm_layout.addWidget(self.llm_path_edit)
        llm_layout.addWidget(llm_btn)
        models_layout.addRow(QLabel("LLM Model (.gguf):"), llm_layout)

        # Kokoro ONNX Path
        kokoro_onnx_layout = QHBoxLayout()
        self.kokoro_onnx_edit = QLineEdit()
        self.kokoro_onnx_edit.setText(self.config_manager.kokoro_onnx_path or "")
        kokoro_onnx_btn = QPushButton("Browse...")
        kokoro_onnx_btn.clicked.connect(self.select_kokoro_onnx)
        kokoro_onnx_layout.addWidget(self.kokoro_onnx_edit)
        kokoro_onnx_layout.addWidget(kokoro_onnx_btn)
        models_layout.addRow(QLabel("Kokoro ONNX (.onnx):"), kokoro_onnx_layout)

        # Kokoro Voices BIN Path
        kokoro_voices_layout = QHBoxLayout()
        self.kokoro_voices_edit = QLineEdit()
        self.kokoro_voices_edit.setText(self.config_manager.kokoro_voices_path or "")
        kokoro_voices_btn = QPushButton("Browse...")
        kokoro_voices_btn.clicked.connect(self.select_kokoro_voices)
        kokoro_voices_layout.addWidget(self.kokoro_voices_edit)
        kokoro_voices_layout.addWidget(kokoro_voices_btn)
        models_layout.addRow(QLabel("Kokoro Voices File (.bin):"), kokoro_voices_layout)

        # Kokoro Voice Selection
        self.voice_combo = QComboBox()
        
        # Spanish Voices
        spanish_voices = [
            ("Spanish: em_alex (Male - Recommended)", "em_alex"),
            ("Spanish: ef_dora (Female)", "ef_dora"),
            ("Spanish: em_santa (Male)", "em_santa")
        ]
        # US Voices
        us_voices = [
            ("English (US): am_adam (Male)", "am_adam"),
            ("English (US): af_sarah (Female)", "af_sarah"),
            ("English (US): af_alloy (Female)", "af_alloy"),
            ("English (US): af_aoede (Female)", "af_aoede"),
            ("English (US): af_bella (Female)", "af_bella"),
            ("English (US): af_heart (Female)", "af_heart"),
            ("English (US): af_jessica (Female)", "af_jessica"),
            ("English (US): af_kore (Female)", "af_kore"),
            ("English (US): af_nicole (Female)", "af_nicole"),
            ("English (US): af_nova (Female)", "af_nova"),
            ("English (US): af_river (Female)", "af_river"),
            ("English (US): af_sky (Female)", "af_sky"),
            ("English (US): am_echo (Male)", "am_echo"),
            ("English (US): am_eric (Male)", "am_eric"),
            ("English (US): am_fenrir (Male)", "am_fenrir"),
            ("English (US): am_liam (Male)", "am_liam"),
            ("English (US): am_michael (Male)", "am_michael"),
            ("English (US): am_onyx (Male)", "am_onyx"),
            ("English (US): am_puck (Male)", "am_puck"),
            ("English (US): am_santa (Male)", "am_santa")
        ]
        # UK Voices
        uk_voices = [
            ("English (UK): bf_alice (Female)", "bf_alice"),
            ("English (UK): bf_emma (Female)", "bf_emma"),
            ("English (UK): bf_isabella (Female)", "bf_isabella"),
            ("English (UK): bf_lily (Female)", "bf_lily"),
            ("English (UK): bm_daniel (Male)", "bm_daniel"),
            ("English (UK): bm_fable (Male)", "bm_fable"),
            ("English (UK): bm_george (Male)", "bm_george"),
            ("English (UK): bm_lewis (Male)", "bm_lewis")
        ]
        
        for display_name, val in spanish_voices:
            self.voice_combo.addItem(display_name, val)
        for display_name, val in us_voices:
            self.voice_combo.addItem(display_name, val)
        for display_name, val in uk_voices:
            self.voice_combo.addItem(display_name, val)
            
        # Pre-select saved voice
        saved_voice = self.config_manager.kokoro_voice
        voice_idx = self.voice_combo.findData(saved_voice)
        if voice_idx != -1:
            self.voice_combo.setCurrentIndex(voice_idx)
            
        models_layout.addRow(QLabel("Kokoro TTS Voice:"), self.voice_combo)

        main_layout.addWidget(models_group)

        # 2.5. Custom System Prompt Group
        prompt_group = QGroupBox("Custom System Prompt")
        prompt_layout = QVBoxLayout(prompt_group)
        self.prompt_text = QTextEdit()
        self.prompt_text.setPlaceholderText(
            "Type your custom system prompt here...\n"
            "Example: You are a witty helper who responds in English.\n"
            "You can use {hardware_info} to dynamically inject system resources.\n"
            "Leave empty to use the default red devil assistant prompt."
        )
        self.prompt_text.setAcceptRichText(False)
        self.prompt_text.setText(self.config_manager.system_prompt or "")
        self.prompt_text.setMaximumHeight(80)
        prompt_layout.addWidget(self.prompt_text)
        main_layout.addWidget(prompt_group)

        # 3. Save / Cancel Buttons
        btn_layout = QHBoxLayout()
        save_btn = QPushButton("Save Settings")
        save_btn.setStyleSheet("font-weight: bold; background-color: #2e7d32; color: white; padding: 6px;")
        save_btn.clicked.connect(self.save_configuration)
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        
        btn_layout.addStretch()
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(save_btn)
        
        main_layout.addLayout(btn_layout)

    def scan_avatars(self):
        """
        Scans the avatars directory and validates that each subfolder
        contains all required files (quiet, cm-ce, om-oe, om-ce, listen)
        in either .png, .jpg, or .jpeg format.
        """
        base_dir = "/home/maximo/Código/Python/Llama-assistant/avatar"
        required_bases = {"quiet", "cm-ce", "om-oe", "om-ce", "listen"}
        allowed_extensions = {".png", ".jpg", ".jpeg"}
        
        valid_avatars = []
        invalid_avatars = {}
        
        if os.path.exists(base_dir):
            for entry in os.scandir(base_dir):
                if entry.is_dir():
                    folder_name = entry.name
                    folder_path = entry.path
                    
                    try:
                        files_in_folder = os.listdir(folder_path)
                    except Exception as e:
                        invalid_avatars[folder_name] = [f"Could not read folder: {e}"]
                        continue
                    
                    errors = []
                    found_bases = {}
                    
                    for f in files_in_folder:
                        base, ext = os.path.splitext(f)
                        base_lower = base.lower()
                        ext_lower = ext.lower()
                        
                        if base_lower in required_bases:
                            if ext_lower in allowed_extensions:
                                if base_lower not in found_bases:
                                    found_bases[base_lower] = []
                                found_bases[base_lower].append(f)
                            else:
                                errors.append(f"File '{f}': extension '{ext}' is not allowed (use .png, .jpg or .jpeg)")
                        else:
                            # Search for common typos
                            if base_lower == "op-ce":
                                errors.append(f"Incorrect name '{f}': correct syntax is 'om-ce' (with .png, .jpg, or .jpeg)")
                            elif base_lower == "op-oe":
                                errors.append(f"Incorrect name '{f}': correct syntax is 'om-oe' (with .png, .jpg, or .jpeg)")
                                
                    # Verify presence of each required base
                    for req in required_bases:
                        if req not in found_bases:
                            errors.append(f"Missing file for state '{req}' (must be '{req}.png' or '{req}.jpg')")
                        elif len(found_bases[req]) > 1:
                            errors.append(f"Duplicate for state '{req}': multiple files found ({', '.join(found_bases[req])})")
                            
                    unique_errors = sorted(list(set(errors)))
                    if unique_errors:
                        invalid_avatars[folder_name] = unique_errors
                    else:
                        valid_avatars.append(folder_name)
                        
        return valid_avatars, invalid_avatars

    def populate_audio_devices(self):
        """Searches and populates audio devices into input/output combo boxes."""
        try:
            devices = sd.query_devices()
        except Exception as e:
            print(f"Error querying audio devices: {e}")
            devices = []

        self.input_devices_map = {}
        self.output_devices_map = {}

        self.input_combo.clear()
        self.output_combo.clear()

        # Add system default options
        self.input_combo.addItem("Default Mic / System Default Microphone", None)
        self.output_combo.addItem("Default Output / System Default Speakers", None)

        input_index_to_select = -1
        output_index_to_select = -1

        saved_input = self.config_manager.input_device_name
        saved_output = self.config_manager.output_device_name

        idx_in = 1
        idx_out = 1

        for i, dev in enumerate(devices):
            name = dev.get('name', 'Unknown Device')
            host_api = dev.get('hostapi', 0)
            try:
                api_name = sd.query_hostapis(host_api).get('name', '')
                display_name = f"{name} ({api_name})"
            except Exception:
                display_name = name

            # Filter input devices
            if dev.get('max_input_channels', 0) > 0:
                self.input_combo.addItem(display_name, name)
                self.input_devices_map[name] = display_name
                if saved_input == name:
                    input_index_to_select = idx_in
                idx_in += 1

            # Filter output devices
            if dev.get('max_output_channels', 0) > 0:
                self.output_combo.addItem(display_name, name)
                self.output_devices_map[name] = display_name
                if saved_output == name:
                    output_index_to_select = idx_out
                idx_out += 1

        # Select saved index or fallback to default
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
            self, "Select LLG GGUF Model", "", "Llama GGUF Models (*.gguf)"
        )
        if file_path:
            self.llm_path_edit.setText(file_path)

    def select_kokoro_onnx(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Kokoro ONNX Model", "", "ONNX Models (*.onnx)"
        )
        if file_path:
            self.kokoro_onnx_edit.setText(file_path)

    def select_kokoro_voices(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Kokoro Voices File", "", "Voices BIN (*.bin)"
        )
        if file_path:
            self.kokoro_voices_edit.setText(file_path)

    def save_configuration(self):
        """Validates paths and saves configuration."""
        llm_path = self.llm_path_edit.text().strip()
        onnx_path = self.kokoro_onnx_edit.text().strip()
        voices_path = self.kokoro_voices_edit.text().strip()

        # Validate file existence
        errors = []
        if not llm_path or not os.path.isfile(llm_path):
            errors.append("- The LLM model file (.gguf) does not exist or has not been selected.")
        if not onnx_path or not os.path.isfile(onnx_path):
            errors.append("- The Kokoro ONNX model file (.onnx) does not exist or has not been selected.")
        if not voices_path or not os.path.isfile(voices_path):
            errors.append("- The Kokoro voices file (.bin) does not exist or has not been selected.")

        if errors:
            QMessageBox.warning(
                self, 
                "Configuration Error", 
                "Please resolve the following issues before saving:\n\n" + "\n".join(errors)
            )
            return

        input_name = self.input_combo.currentData()
        output_name = self.output_combo.currentData()
        pos_name = self.position_combo.currentData()
        use_gpu_val = self.gpu_checkbox.isChecked()
        voice_name = self.voice_combo.currentData()
        
        prompt_val = self.prompt_text.toPlainText().strip()
        context_val = self.context_spin.value()
        whisper_val = self.whisper_combo.currentData()
        
        self.config_manager.input_device_name = input_name
        self.config_manager.output_device_name = output_name
        self.config_manager.avatar_position = pos_name
        self.config_manager.use_gpu = use_gpu_val
        self.config_manager.kokoro_voice = voice_name
        self.config_manager.llm_model_path = llm_path
        self.config_manager.kokoro_onnx_path = onnx_path
        self.config_manager.kokoro_voices_path = voices_path
        self.config_manager.system_prompt = prompt_val if prompt_val else None
        self.config_manager.llm_n_ctx = context_val
        self.config_manager.whisper_model_size = whisper_val
        
        avatar_name_val = self.avatar_combo.currentData()
        if avatar_name_val:
            self.config_manager.avatar_name = avatar_name_val

        # Save to file
        if self.config_manager.save():
            QMessageBox.information(self, "Success", "Configuration saved successfully.")
            self.accept()
        else:
            QMessageBox.critical(self, "Error", "Could not write configuration file.")
