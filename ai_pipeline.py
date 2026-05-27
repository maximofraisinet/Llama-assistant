import os
import re
import queue
import subprocess
import platform
import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal, QObject, Qt
from faster_whisper import WhisperModel
from llama_cpp import Llama
from kokoro_onnx import Kokoro
from audio_engine import AudioPlayer

def get_hardware_info() -> str:
    """
    Ejecuta 'fastfetch --stdout' o cae en una alternativa robusta de lectura de 
    información del sistema en Linux para inyectarlo en el System Prompt.
    """
    try:
        res = subprocess.run(["fastfetch", "--stdout"], capture_output=True, text=True, timeout=3)
        if res.returncode == 0 and res.stdout.strip():
            # Limpiar secuencias de escape ANSI por si las hubiera
            ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
            return ansi_escape.sub('', res.stdout.strip())
    except Exception:
        pass

    # Alternativa si no está fastfetch
    try:
        info = []
        info.append(f"OS: {platform.system()} {platform.release()}")
        # CPU
        if os.path.exists("/proc/cpuinfo"):
            with open("/proc/cpuinfo", "r") as f:
                for line in f:
                    if "model name" in line:
                        info.append(f"CPU: {line.split(':')[1].strip()}")
                        break
        # Memoria
        if os.path.exists("/proc/meminfo"):
            with open("/proc/meminfo", "r") as f:
                total_mem = f.readline().strip()
                free_mem = f.readline().strip()
                info.append(f"Memory: {total_mem} ({free_mem})")
        return "\n".join(info)
    except Exception as e:
        return f"Linux System (Error al obtener detalles: {e})"


class ModelLoaderThread(QThread):
    """
    Hilo secundario para inicializar todos los modelos de IA de forma asíncrona
    durante el arranque, evitando congelar la interfaz de usuario.
    """
    status_changed = pyqtSignal(str)
    loading_finished = pyqtSignal(object, object, object)  # whisper, llama, kokoro
    loading_failed = pyqtSignal(str)

    def __init__(self, config):
        super().__init__()
        self.config = config

    def run(self):
        try:
            # 1. Cargar Kokoro-ONNX
            self.status_changed.emit("Cargando Kokoro TTS...")
            if not os.path.isfile(self.config.kokoro_onnx_path) or not os.path.isfile(self.config.kokoro_voices_path):
                raise FileNotFoundError("Rutas de Kokoro ONNX o Voces BIN no válidas.")
            
            kokoro = Kokoro(
                model_path=self.config.kokoro_onnx_path,
                voices_path=self.config.kokoro_voices_path
            )

            # 2. Cargar Llama.cpp
            self.status_changed.emit("Cargando Llama.cpp LLM...")
            if not os.path.isfile(self.config.llm_model_path):
                raise FileNotFoundError("Ruta del modelo GGUF no válida.")
            
            # Cargar LLM con GPU si está configurado, o caer en CPU si falla
            llama = None
            if self.config.use_gpu:
                try:
                    print("Intentando cargar Llama.cpp en GPU (Nvidia CUDA)...")
                    n_ctx_val = self.config.llm_n_ctx
                    llama = Llama(
                        model_path=self.config.llm_model_path,
                        n_ctx=n_ctx_val,
                        n_gpu_layers=-1,
                        verbose=False
                    )
                    print("Llama.cpp cargado con éxito en la GPU.")
                except Exception as e:
                    print(f"Fallo al iniciar Llama con GPU ({e}). Cargando en CPU...")
                    llama = None
            
            if llama is None:
                n_ctx_val = self.config.llm_n_ctx
                llama = Llama(
                    model_path=self.config.llm_model_path,
                    n_ctx=n_ctx_val,
                    n_gpu_layers=0,
                    verbose=False
                )

            # 3. Cargar Faster Whisper
            self.status_changed.emit("Cargando Faster-Whisper...")
            whisper = None
            if self.config.use_gpu:
                try:
                    print("Intentando cargar Faster-Whisper en GPU (CUDA)...")
                    w_size = self.config.whisper_model_size
                    whisper = WhisperModel(
                        w_size,
                        device="cuda",
                        compute_type="float16"
                    )
                    print("Faster-Whisper cargado con éxito en la GPU.")
                except Exception as e:
                    print(f"Fallo al iniciar Whisper con GPU ({e}). Cargando en CPU...")
                    whisper = None
                    
            if whisper is None:
                w_size = self.config.whisper_model_size
                whisper = WhisperModel(
                    w_size,
                    device="cpu",
                    compute_type="int8"
                )

            self.status_changed.emit("Modelos cargados con éxito.")
            self.loading_finished.emit(whisper, llama, kokoro)

        except Exception as e:
            self.loading_failed.emit(str(e))


class SpeechPipelineWorker(QThread):
    """
    Hilo de ejecución para procesar el pipeline completo:
    STT (Audio -> Texto) -> LLM (Texto -> Streaming de tokens) -> TTS (Oración -> Audio).
    Coloca las oraciones en una cola para reproducción secuencial.
    """
    status_changed = pyqtSignal(str)
    transcription_done = pyqtSignal(str)
    llm_token_received = pyqtSignal(str)
    pipeline_finished = pyqtSignal()
    pipeline_error = pyqtSignal(str)
    
    # Señal para actualizar la boca desde el reproductor en el hilo principal
    change_mouth_image = pyqtSignal(str)

    def __init__(self, whisper, llama, kokoro, audio_data, config):
        super().__init__()
        self.whisper = whisper
        self.llama = llama
        self.kokoro = kokoro
        self.audio_data = audio_data
        self.config = config
        self.speech_queue = queue.Queue()
        self.is_running = True
        self.current_player = None

    def run(self):
        try:
            if self.audio_data is None or len(self.audio_data) == 0:
                self.pipeline_finished.emit()
                return

            # --- 1. STT (Whisper) ---
            self.status_changed.emit("Transcribiendo voz...")
            voice = self.config.kokoro_voice or "em_alex"
            is_spanish = voice.startswith("ef") or voice.startswith("em")
            transcribe_lang = "es" if is_spanish else "en"

            segments, info = self.whisper.transcribe(
                self.audio_data, 
                language=transcribe_lang,
                beam_size=5
            )
            
            transcription = " ".join([segment.text for segment in segments]).strip()
            if not transcription:
                self.status_changed.emit("No se detectó voz clara." if is_spanish else "No clear speech detected.")
                self.pipeline_finished.emit()
                return
                
            self.transcription_done.emit(transcription)

            # --- 2. Preparar Prompt y Llamada a LLM ---
            self.status_changed.emit("Pensando respuesta..." if is_spanish else "Thinking response...")
            hardware_info = get_hardware_info()
            
            custom_prompt = self.config.system_prompt
            if custom_prompt and custom_prompt.strip():
                if "{hardware_info}" in custom_prompt:
                    system_prompt = custom_prompt.replace("{hardware_info}", hardware_info)
                else:
                    system_prompt = f"{custom_prompt}\n\n[Información de hardware / Hardware info:\n{hardware_info}]"
            else:
                if is_spanish:
                    system_prompt = (
                        "Eres un asistente virtual de escritorio para Linux con apariencia de diablo rojo.\n"
                        "Eres ingenioso, directo y respondes en español.\n"
                        f"Información de hardware del sistema de forma oculta:\n{hardware_info}\n\n"
                        "IMPORTANTE: No uses etiquetas <think> ni muestres tu proceso de razonamiento. Responde directamente de forma inmediata.\n"
                        "Responde de forma concisa y conversacional (máximo 2 oraciones), ya que tu respuesta "
                        "será leída en voz alta por el motor de TTS."
                    )
                else:
                    system_prompt = (
                        "You are a Linux desktop virtual assistant with the appearance of a red devil.\n"
                        "You are witty, direct, and respond in English.\n"
                        f"System hardware info (hidden):\n{hardware_info}\n\n"
                        "IMPORTANT: Do NOT output any <think> tags or reasoning. Go straight to the answer immediately.\n"
                        "Be very concise and conversational (maximum 2 sentences), as your response will be read aloud by a TTS engine."
                    )

            # Iniciar el consumidor de audio en un hilo secundario independiente
            playback_thread = QThread()
            playback_thread.run = self._playback_consumer
            playback_thread.start()

            # Expresión regular para detectar finales de oraciones
            sentence_end_regex = re.compile(r'([.!?\n]+)')
            
            # Streaming del LLM
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": transcription}
            ]
            
            response_stream = self.llama.create_chat_completion(
                messages=messages,
                stream=True,
                max_tokens=150,
                temperature=0.7
            )

            current_sentence = ""
            token_buffer = ""
            inside_think = False
            full_visible_response = ""
            
            for chunk in response_stream:
                if not self.is_running:
                    break
                    
                choice = chunk['choices'][0]
                delta = choice.get('delta', {})
                token = delta.get('content', '')
                
                if token:
                    token_buffer += token
                    
                    # Filtrar etiquetas <think>
                    if "<think>" in token_buffer:
                        inside_think = True
                        parts = token_buffer.split("<think>", 1)
                        visible = parts[0]
                        if visible:
                            self.llm_token_received.emit(visible)
                            current_sentence += visible
                            full_visible_response += visible
                        token_buffer = ""
                        
                    elif "</think>" in token_buffer:
                        inside_think = False
                        parts = token_buffer.split("</think>", 1)
                        visible = parts[1]
                        token_buffer = visible
                        
                    else:
                        if inside_think:
                            # Ignorar contenido de razonamiento
                            if len(token_buffer) > 10:
                                token_buffer = token_buffer[-10:]
                        else:
                            # Evitar emitir fragmentos de etiqueta parcial
                            potential_prefix = False
                            for i in range(1, len("<think>")):
                                prefix = "<think>"[:i]
                                if token_buffer.endswith(prefix):
                                    potential_prefix = True
                                    break
                            
                            if not potential_prefix:
                                self.llm_token_received.emit(token_buffer)
                                current_sentence += token_buffer
                                full_visible_response += token_buffer
                                token_buffer = ""

                    # Procesar oraciones terminadas (fuera de bloques think)
                    if not inside_think and len(current_sentence) > 0:
                        matches = list(sentence_end_regex.finditer(current_sentence))
                        if matches:
                            last_match = matches[-1]
                            end_pos = last_match.end()
                            
                            sentence_to_speak = current_sentence[:end_pos].strip()
                            current_sentence = current_sentence[end_pos:]
                            
                            if len(sentence_to_speak) > 2:
                                self._synthesize_and_queue(sentence_to_speak)

            # Agregar remanente del búfer de tokens
            if not inside_think and token_buffer:
                self.llm_token_received.emit(token_buffer)
                current_sentence += token_buffer
                full_visible_response += token_buffer

            # Sintetizar lo que quede en el búfer al finalizar el stream
            if self.is_running and current_sentence.strip():
                self._synthesize_and_queue(current_sentence.strip())

            # Indicar al consumidor que la generación de oraciones ha finalizado
            self.speech_queue.put((None, None))
            
            # Buscar comandos para ejecutar en terminal inmediatamente
            commands = re.findall(r'<cmd>(.*?)</cmd>', full_visible_response, re.DOTALL)
            for cmd in commands:
                if cmd.strip():
                    self._open_terminal_with_command(cmd.strip())
            
            # Esperar a que el hilo consumidor de reproducción finalice
            playback_thread.wait()
            self.pipeline_finished.emit()

        except Exception as e:
            self.pipeline_error.emit(str(e))

    def _open_terminal_with_command(self, command: str):
        """
        Abre una terminal del sistema con el comando pre-escrito pero sin ejecutar,
        permitiendo al usuario editarlo y ejecutarlo presionando Enter.
        """
        import subprocess
        
        # Escapar comillas dobles en el comando para que no rompa la cadena de bash
        escaped_command = command.replace('"', '\\"')
        
        # El script bash que pre-rellena el buffer usando read -e -i
        bash_script = (
            f'read -e -i "{escaped_command}" -p "Ejecutar comando? (Enter para confirmar, Ctrl+C para cancelar): " cmd; '
            f'history -s "$cmd"; '
            f'echo ""; '
            f'eval "$cmd"; '
            f'exec bash'
        )
        
        # Buscar terminales disponibles en orden de preferencia
        terminals = ["konsole", "gnome-terminal", "xterm"]
        launched = False
        
        for term in terminals:
            # Verificar si la terminal está en el PATH
            if subprocess.run(["which", term], capture_output=True).returncode == 0:
                try:
                    if term == "gnome-terminal":
                        # gnome-terminal usa -- para pasar el comando
                        subprocess.Popen([term, "--", "bash", "-c", bash_script])
                    else:
                        # konsole y xterm usan -e
                        subprocess.Popen([term, "-e", "bash", "-c", bash_script])
                    launched = True
                    print(f"Terminal abierta con éxito usando {term}.")
                    break
                except Exception as e:
                    print(f"Fallo al abrir terminal {term}: {e}")
                    
        if not launched:
            print("Error: No se encontró ninguna terminal compatible (konsole, gnome-terminal, xterm).")

    def _synthesize_and_queue(self, text: str):
        """Sintetiza texto a audio usando Kokoro-ONNX y lo coloca en la cola."""
        try:
            # 0. Eliminar etiquetas <cmd>...</cmd> y su contenido para que no sea leído por el TTS
            clean_text = re.sub(r'<cmd>.*?</cmd>', '', text)
            
            # 1. Limpiar asteriscos, guiones bajos y comillas invertidas de Markdown
            clean_text = clean_text.replace("*", "").replace("_", "").replace("`", "")
            
            # 2. Eliminar emojis (caracteres en los planos unicode suplementarios)
            clean_text = re.sub(r'[\U00010000-\U0010ffff]', '', clean_text)
            
            # 3. Eliminar espacios múltiples y espacios previos a signos de puntuación comunes
            clean_text = re.sub(r'\s+', ' ', clean_text)
            clean_text = re.sub(r'\s+([.,;:!?])', r'\1', clean_text).strip()
            
            print(f"Sintetizando: '{clean_text}' (Original: '{text}')")
            voice = self.config.kokoro_voice or "em_alex"
            
            # Determinar el idioma del modelo Kokoro según el prefijo de la voz
            if voice.startswith("ef") or voice.startswith("em"):
                lang = "es"
            elif voice.startswith("bf") or voice.startswith("bm"):
                lang = "en-gb"
            else:
                lang = "en-us"
                
            samples, sample_rate = self.kokoro.create(clean_text, voice=voice, lang=lang)
            # Pasamos clean_text a la cola para que la animación de Lip-Sync y la reproducción
            # se sincronicen con el texto pronunciado real.
            self.speech_queue.put((samples, clean_text))
        except Exception as e:
            print(f"Error al sintetizar con Kokoro: {e}")

    def _playback_consumer(self):
        """
        Consumidor que corre en segundo plano procesando secuencialmente la cola de audio 
        y reproduciéndola a través de sounddevice con Lip-Sync.
        """
        self.status_changed.emit("Hablando...")
        while self.is_running:
            try:
                audio_data, text = self.speech_queue.get(timeout=0.1)
                
                # Elemento centinela para indicar fin de reproducción
                if audio_data is None:
                    break

                # Crear y ejecutar el AudioPlayer
                self.current_player = AudioPlayer(
                    audio_data=audio_data,
                    text=text,
                    device_index=self.config.output_device_index,
                    sample_rate=24000
                )
                
                # Conectar el cambio de boca del reproductor a la señal de este Worker usando conexión directa
                self.current_player.change_mouth_image.connect(self.change_mouth_image.emit, Qt.ConnectionType.DirectConnection)
                
                # Iniciar la reproducción en su propio hilo
                self.current_player.start()
                
                # Esperar a que el reproductor termine
                self.current_player.wait()
                self.current_player = None
                
                self.speech_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                print(f"Error en el consumidor de reproducción de audio: {e}")
                break

    def stop(self):
        """Detiene forzosamente la ejecución del pipeline."""
        self.is_running = False
        if self.current_player:
            self.current_player.stop()
