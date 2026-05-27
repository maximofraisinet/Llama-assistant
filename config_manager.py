import os
import json
import sounddevice as sd

class ConfigManager:
    """
    Clase para gestionar la configuración persistente del asistente virtual.
    Guarda y carga los parámetros en ~/.config/asistente_avatar/config.json.
    Mapea nombres estables de dispositivos a sus índices ALSA actuales en tiempo de ejecución.
    """
    CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))
    CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

    def __init__(self):
        self.config_data = {
            "input_device_name": None,
            "output_device_name": None,
            "llm_model_path": None,
            "kokoro_onnx_path": None,
            "kokoro_voices_path": None,
            "avatar_position": "bottom_right",
            "use_gpu": False,
            "kokoro_voice": "em_alex",
            "system_prompt": None,
            "llm_n_ctx": 2048,
            "whisper_model_size": "base"
        }
        self.load()

    def load(self):
        """Carga la configuración desde el archivo JSON si existe."""
        if os.path.exists(self.CONFIG_FILE):
            try:
                with open(self.CONFIG_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                    # Compatibilidad con archivos de configuración antiguos
                    if "input_device_index" in data and "input_device_name" not in data:
                        try:
                            idx = data["input_device_index"]
                            if idx is not None:
                                data["input_device_name"] = sd.query_devices(idx)["name"]
                        except Exception:
                            pass
                    if "output_device_index" in data and "output_device_name" not in data:
                        try:
                            idx = data["output_device_index"]
                            if idx is not None:
                                data["output_device_name"] = sd.query_devices(idx)["name"]
                        except Exception:
                            pass

                    # Actualizar campos existentes
                    for key in self.config_data:
                        if key in data:
                            self.config_data[key] = data[key]
            except Exception as e:
                print(f"Error al cargar la configuración: {e}")

    def save(self):
        """Guarda la configuración actual en el archivo JSON."""
        try:
            os.makedirs(self.CONFIG_DIR, exist_ok=True)
            with open(self.CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.config_data, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"Error al guardar la configuración: {e}")
            return False

    def is_valid(self) -> bool:
        """
        Valida que la configuración actual sea correcta.
        Los archivos especificados deben existir y las rutas no deben ser nulas.
        """
        # Validar rutas de modelos
        paths_to_check = [
            self.config_data.get("llm_model_path"),
            self.config_data.get("kokoro_onnx_path"),
            self.config_data.get("kokoro_voices_path")
        ]
        
        for path in paths_to_check:
            if not path or not isinstance(path, str) or not os.path.isfile(path):
                return False

        # Validar nombres de audio
        in_name = self.config_data.get("input_device_name")
        out_name = self.config_data.get("output_device_name")
        
        if in_name is None or out_name is None:
            return False

        return True

    # Getters y Setters de Índices Dinámicos (Resueltos en tiempo de ejecución)
    @property
    def input_device_index(self):
        name = self.config_data.get("input_device_name")
        if not name:
            return None
        try:
            devices = sd.query_devices()
            # 1. Intentar coincidencia exacta en dispositivos de entrada
            for i, dev in enumerate(devices):
                if dev.get('max_input_channels', 0) > 0 and name == dev.get('name'):
                    return i
            # 2. Intentar coincidencia parcial
            for i, dev in enumerate(devices):
                if dev.get('max_input_channels', 0) > 0 and name in dev.get('name', ''):
                    return i
        except Exception:
            pass
        return None

    @property
    def output_device_index(self):
        name = self.config_data.get("output_device_name")
        if not name:
            return None
        try:
            devices = sd.query_devices()
            # 1. Intentar coincidencia exacta en dispositivos de salida
            for i, dev in enumerate(devices):
                if dev.get('max_output_channels', 0) > 0 and name == dev.get('name'):
                    return i
            # 2. Intentar coincidencia parcial
            for i, dev in enumerate(devices):
                if dev.get('max_output_channels', 0) > 0 and name in dev.get('name', ''):
                    return i
        except Exception:
            pass
        return None

    # Getters y Setters directos para nombres
    @property
    def input_device_name(self):
        return self.config_data.get("input_device_name")

    @input_device_name.setter
    def input_device_name(self, val):
        self.config_data["input_device_name"] = val

    @property
    def output_device_name(self):
        return self.config_data.get("output_device_name")

    @output_device_name.setter
    def output_device_name(self, val):
        self.config_data["output_device_name"] = val

    @property
    def llm_model_path(self):
        return self.config_data.get("llm_model_path")

    @llm_model_path.setter
    def llm_model_path(self, val):
        self.config_data["llm_model_path"] = val

    @property
    def kokoro_onnx_path(self):
        return self.config_data.get("kokoro_onnx_path")

    @kokoro_onnx_path.setter
    def kokoro_onnx_path(self, val):
        self.config_data["kokoro_onnx_path"] = val

    @property
    def kokoro_voices_path(self):
        return self.config_data.get("kokoro_voices_path")

    @kokoro_voices_path.setter
    def kokoro_voices_path(self, val):
        self.config_data["kokoro_voices_path"] = val

    @property
    def avatar_position(self):
        return self.config_data.get("avatar_position", "bottom_right")

    @avatar_position.setter
    def avatar_position(self, val):
        self.config_data["avatar_position"] = val

    @property
    def use_gpu(self):
        return self.config_data.get("use_gpu", False)

    @use_gpu.setter
    def use_gpu(self, val):
        self.config_data["use_gpu"] = bool(val)

    @property
    def kokoro_voice(self):
        return self.config_data.get("kokoro_voice", "em_alex")

    @kokoro_voice.setter
    def kokoro_voice(self, val):
        self.config_data["kokoro_voice"] = val

    @property
    def system_prompt(self):
        return self.config_data.get("system_prompt")

    @system_prompt.setter
    def system_prompt(self, val):
        self.config_data["system_prompt"] = val

    @property
    def llm_n_ctx(self):
        return int(self.config_data.get("llm_n_ctx", 2048))

    @llm_n_ctx.setter
    def llm_n_ctx(self, val):
        self.config_data["llm_n_ctx"] = int(val)

    @property
    def whisper_model_size(self):
        return self.config_data.get("whisper_model_size", "base")

    @whisper_model_size.setter
    def whisper_model_size(self, val):
        self.config_data["whisper_model_size"] = val
