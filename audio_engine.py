import time
import numpy as np
import sounddevice as sd
from PyQt6.QtCore import QThread, pyqtSignal

class AudioRecorder:
    """
    Graba audio desde el micrófono configurado.
    Graba en formato mono en la tasa de muestreo nativa del dispositivo
    y luego la remuestrea a 16000Hz (óptimo para faster-whisper) en float32.
    """
    def __init__(self, device_index=None, sample_rate=16000):
        self.device_index = device_index
        self.sample_rate = sample_rate
        self.stream = None
        self.audio_data = []
        self.actual_sample_rate = sample_rate

    def _callback(self, indata, frames, time_info, status):
        """Callback que recibe los bloques de audio de sounddevice."""
        if status:
            print(f"Error en grabación de audio: {status}")
        self.audio_data.append(indata.copy())

    def start_recording(self):
        """Inicia la grabación de audio en segundo plano."""
        self.audio_data = []
        
        # Intentar obtener la tasa de muestreo por defecto del dispositivo
        try:
            device_info = sd.query_devices(self.device_index, 'input')
            self.actual_sample_rate = int(device_info.get('default_samplerate', 44100))
            print(f"Dispositivo de entrada: {device_info.get('name')}. Tasa nativa: {self.actual_sample_rate}Hz.")
        except Exception as e:
            print(f"No se pudo consultar el dispositivo de entrada: {e}. Usando 44100Hz como respaldo.")
            self.actual_sample_rate = 44100

        # Intentar abrir el flujo con la tasa nativa del dispositivo.
        # Si falla, intentaremos tasas de muestreo comunes.
        rates_to_try = [self.actual_sample_rate, 44100, 48000, 16000]
        for rate in rates_to_try:
            try:
                self.stream = sd.InputStream(
                    samplerate=rate,
                    channels=1,
                    dtype='float32',
                    device=self.device_index,
                    callback=self._callback
                )
                self.stream.start()
                self.actual_sample_rate = rate
                print(f"Grabación iniciada con éxito a {rate}Hz...")
                return
            except Exception as e:
                print(f"Error al abrir stream a {rate}Hz: {e}")
                self.stream = None
        
        print("Error crítico: No se pudo abrir el canal de audio del micrófono en ninguna tasa de muestreo.")

    def stop_recording(self) -> np.ndarray:
        """Detiene la grabación y devuelve el array de numpy con el audio remuestreado a 16000Hz."""
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None
            print("Grabación detenida.")
            
        if not self.audio_data:
            return np.array([], dtype=np.float32)
            
        # Concatenar todos los bloques grabados
        full_audio = np.concatenate(self.audio_data, axis=0)
        # Convertir a 1D (Whisper requiere shape (samples,))
        mono_audio = np.squeeze(full_audio)
        
        # Si la tasa real es distinta a la objetivo (16000Hz), remuestrear
        if self.actual_sample_rate != self.sample_rate and len(mono_audio) > 0:
            print(f"Remuestreando audio de {self.actual_sample_rate}Hz a {self.sample_rate}Hz...")
            duration = len(mono_audio) / self.actual_sample_rate
            num_target_samples = int(duration * self.sample_rate)
            
            x_orig = np.linspace(0, duration, len(mono_audio))
            x_target = np.linspace(0, duration, num_target_samples)
            
            resampled_audio = np.interp(x_target, x_orig, mono_audio)
            return resampled_audio.astype(np.float32)
            
        return mono_audio


class AudioPlayer(QThread):
    """
    QThread para reproducir audio generado por Kokoro (24000Hz) sin bloquear la GUI.
    Emite señales de sincronización de boca (Lip-Sync) basadas en el texto pronunciado.
    """
    change_mouth_image = pyqtSignal(str)  # Envía el nombre del archivo de imagen (ej: "O.png")
    playback_started = pyqtSignal()
    playback_finished = pyqtSignal()

    def __init__(self, audio_data: np.ndarray, text: str, device_index=None, sample_rate=24000):
        super().__init__()
        self.audio_data = audio_data
        self.text = text
        self.device_index = device_index
        self.sample_rate = sample_rate
        self.is_playing = False
        self._toggle_state = False  # Para alternar entre CH-I-S.png y R.png

    def run(self):
        if self.audio_data is None or len(self.audio_data) == 0:
            self.playback_finished.emit()
            return

        self.is_playing = True
        self.playback_started.emit()

        # Duración total del audio en segundos
        total_duration = len(self.audio_data) / self.sample_rate
        
        # Procesar texto para la animación de Lip-Sync
        tokens = self._tokenize_text(self.text)
        num_tokens = len(tokens)

        # Si no hay tokens, usar una lista vacía para evitar división por cero
        if num_tokens > 0:
            # Calcular tiempo por token (con un pequeño ajuste)
            delay_per_token = total_duration / num_tokens
        else:
            delay_per_token = 0.1

        # Obtener la tasa de muestreo nativa del dispositivo de salida
        try:
            device_info = sd.query_devices(self.device_index, 'output')
            native_rate = int(device_info.get('default_samplerate', 44100))
        except Exception as e:
            print(f"No se pudo consultar el dispositivo de salida: {e}. Usando 44100Hz como respaldo.")
            native_rate = 44100

        audio_to_play = self.audio_data
        play_rate = self.sample_rate

        # Si la tasa nativa es distinta a la de Kokoro (24000Hz), remuestrear
        if native_rate != self.sample_rate and len(self.audio_data) > 0:
            print(f"Remuestreando audio de salida de {self.sample_rate}Hz a {native_rate}Hz para compatibilidad...")
            num_target_samples = int(total_duration * native_rate)
            x_orig = np.linspace(0, total_duration, len(self.audio_data))
            x_target = np.linspace(0, total_duration, num_target_samples)
            audio_to_play = np.interp(x_target, x_orig, self.audio_data).astype(np.float32)
            play_rate = native_rate

        # Reproducir audio de forma asíncrona usando sounddevice
        try:
            sd.play(audio_to_play, samplerate=play_rate, device=self.device_index)
        except Exception as e:
            # Si falla por problemas de canales (ej. mono no soportado), duplicar a estéreo (2 canales)
            if "channel" in str(e).lower() or "9998" in str(e):
                print("El dispositivo de salida no soporta reproducción mono. Duplicando canales a estéreo...")
                try:
                    stereo_audio = np.column_stack((audio_to_play, audio_to_play))
                    sd.play(stereo_audio, samplerate=play_rate, device=self.device_index)
                except Exception as e2:
                    print(f"Error crítico al reproducir en estéreo: {e2}")
                    self.is_playing = False
                    self.playback_finished.emit()
                    return
            else:
                print(f"Error al iniciar reproducción en sounddevice: {e}")
                self.is_playing = False
                self.playback_finished.emit()
                return

        # Mientras el audio se reproduce, mover la boca sincronizadamente
        start_time = time.time()
        token_index = 0
        
        while self.is_playing and token_index < num_tokens:
            current_time = time.time()
            elapsed = current_time - start_time
            
            # Calcular en qué token deberíamos estar según el tiempo transcurrido
            expected_index = int(elapsed / delay_per_token)
            
            if expected_index > token_index:
                token_index = min(expected_index, num_tokens - 1)
                token = tokens[token_index]
                image_name = self._get_image_for_token(token)
                self.change_mouth_image.emit(image_name)
            
            # Pequeña espera para no saturar la CPU
            time.sleep(0.01)
            
            # Comprobar si ya terminó la reproducción real de sounddevice
            # sd.get_stream() es None si la reproducción terminó
            # Pero una forma más segura es esperar la duración total del audio
            if elapsed >= total_duration:
                break

        # Esperar a que sounddevice termine completamente por si acaso
        try:
            sd.wait()
        except Exception:
            pass

        # Volver al estado Callado al terminar
        self.change_mouth_image.emit("Callado.png")
        self.is_playing = False
        self.playback_finished.emit()

    def stop(self):
        """Detiene la reproducción y el hilo."""
        self.is_playing = False
        try:
            sd.stop()
        except Exception:
            pass
        self.wait()

    def _tokenize_text(self, text: str):
        """
        Divide el texto en tokens/fonemas aproximados.
        Maneja dígrafos como 'ch' para que se traten como un solo token.
        """
        tokens = []
        i = 0
        text = text.lower()
        while i < len(text):
            if i < len(text) - 1 and text[i:i+2] == "ch":
                tokens.append("ch")
                i += 2
            else:
                tokens.append(text[i])
                i += 1
        return tokens

    def _get_image_for_token(self, token: str) -> str:
        """
        Mapea un token de texto (letra o dígrafo) a una imagen de la boca.
        """
        # Vocales abiertas y de gran apertura (A, E, S, CH) -> Alternar dinámicamente entre CH-I-S.png y R.png
        if token in ('a', 'e', 's', 'ch'):
            self._toggle_state = not self._toggle_state
            return "CH-I-S.png" if self._toggle_state else "R.png"
            
        # Vocales cerradas/semicerradas (I) -> L-R.png o CH-I-S.png
        elif token == 'i':
            self._toggle_state = not self._toggle_state
            return "L-R.png" if self._toggle_state else "CH-I-S.png"
            
        # Vocales redondas (O, U) -> O.png
        elif token in ('o', 'u'):
            return "O.png"
            
        # Consonantes bilabiales y oclusivas (M, B, V, F, P) -> M-B-V-F-P.png
        elif token in ('m', 'b', 'v', 'f', 'p'):
            return "M-B-V-F-P.png"
            
        # Espacios y puntuación -> Callado.png
        elif token in (' ', ',', '.', ';', '?', '!', '\n', '\t'):
            return "Callado.png"
            
        # Consonantes generales -> R.png o L-R.png
        else:
            return "R.png"
