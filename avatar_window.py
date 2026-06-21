import os
import numpy as np
from PyQt6.QtWidgets import QMainWindow, QWidget, QLabel, QVBoxLayout, QHBoxLayout, QMenu, QMessageBox, QApplication, QScrollArea, QDialog, QLineEdit, QPushButton
from PyQt6.QtGui import QPixmap, QCursor, QAction, QPainter
from PyQt6.QtCore import Qt, QPoint, pyqtSlot, QObject, pyqtSignal, QTimer

# Importar clases del proyecto
from config_manager import ConfigManager
from settings_dialog import SettingsDialog
from audio_engine import AudioRecorder
from ai_pipeline import ModelLoaderThread, SpeechPipelineWorker

# Intentar importar pynput
try:
    from pynput import keyboard
except ImportError:
    keyboard = None

class HotkeyListener(QObject):
    """
    Escucha global de teclado utilizando pynput.
    Emite señales cuando la combinación Ctrl + Shift + Espacio se mantiene presionada
    y cuando cualquiera de esas teclas es liberada (Walkie-Talkie).
    """
    pressed = pyqtSignal()
    released = pyqtSignal()
    text_trigger = pyqtSignal()  # Señal para atajo de texto

    def __init__(self):
        super().__init__()
        self.active_keys = set()
        self.is_triggered = False
        self.listener = None

    def clear_keys(self):
        self.active_keys.clear()
        self.is_triggered = False
        print("Atajos de teclado reseteados (limpieza de teclas stuck).")

    def start(self):
        if not keyboard:
            print("pynput no disponible. No se registrará atajo global.")
            return
        self.listener = keyboard.Listener(
            on_press=self.on_press,
            on_release=self.on_release
        )
        self.listener.start()

    def stop(self):
        if self.listener:
            self.listener.stop()

    def _get_key_name(self, key):
        if isinstance(key, keyboard.Key):
            name = key.name
            if "ctrl" in name:
                return "ctrl"
            if "shift" in name:
                return "shift"
            if "alt" in name:
                return "alt"
            if name == "space":
                return "space"
        else:
            try:
                return key.char.lower() if key.char else None
            except AttributeError:
                return None
        return None

    def on_press(self, key):
        name = self._get_key_name(key)
        if name:
            self.active_keys.add(name)
            # Combinación Ctrl + Alt + J (Voz)
            if "ctrl" in self.active_keys and "alt" in self.active_keys and "j" in self.active_keys:
                if not self.is_triggered:
                    self.is_triggered = True
                    self.pressed.emit()
            # Combinación Ctrl + Alt + K (Texto)
            elif "ctrl" in self.active_keys and "alt" in self.active_keys and "k" in self.active_keys:
                self.text_trigger.emit()

    def on_release(self, key):
        name = self._get_key_name(key)
        if name:
            if name in self.active_keys:
                self.active_keys.remove(name)
            
            # Si estaba activo y se suelta alguna de las teclas del atajo
            if self.is_triggered and (name in ("ctrl", "alt", "j")):
                self.is_triggered = False
                self.released.emit()


class TextInputWindow(QDialog):
    """
    Ventana flotante y semitransparente para escribir o pegar un prompt
    directamente al asistente virtual.
    """
    submitted = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Enviar Prompt al Asistente")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.init_ui()

    def init_ui(self):
        # Widget contenedor principal para aplicar estilo
        container = QWidget(self)
        container.setStyleSheet("""
            QWidget {
                background-color: rgba(33, 33, 44, 235);
                border: 1px solid rgba(255, 60, 60, 120);
                border-radius: 12px;
            }
            QLabel {
                color: #ff5555;
                font-size: 12px;
                font-weight: bold;
                font-family: 'Outfit', 'Inter', sans-serif;
                border: none;
                background: transparent;
            }
            QLineEdit {
                background-color: rgba(20, 20, 30, 200);
                border: 1px solid rgba(255, 255, 255, 40);
                border-radius: 6px;
                color: #ffffff;
                font-size: 12px;
                font-family: 'Outfit', 'Inter', sans-serif;
                padding: 6px 10px;
                border: none;
            }
            QLineEdit:focus {
                border: 1px solid rgba(255, 60, 60, 150);
            }
            QPushButton {
                background-color: rgba(255, 60, 60, 180);
                border: none;
                border-radius: 6px;
                color: white;
                font-size: 11px;
                font-weight: bold;
                font-family: 'Outfit', 'Inter', sans-serif;
                padding: 6px 12px;
            }
            QPushButton:hover {
                background-color: rgba(255, 80, 80, 220);
            }
            QPushButton#cancel_btn {
                background-color: rgba(255, 255, 255, 20);
                color: #e0e0e0;
            }
            QPushButton#cancel_btn:hover {
                background-color: rgba(255, 255, 255, 40);
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        inner_layout = QVBoxLayout(container)
        inner_layout.setContentsMargins(15, 15, 15, 15)
        inner_layout.setSpacing(10)

        label = QLabel("Pregunta al Asistente:")
        inner_layout.addWidget(label)

        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("Escribe o pega tu consulta aquí...")
        inner_layout.addWidget(self.input_field)

        btn_layout = QHBoxLayout()
        cancel_btn = QPushButton("Cancelar")
        cancel_btn.setObjectName("cancel_btn")
        cancel_btn.clicked.connect(self.reject)
        
        submit_btn = QPushButton("Enviar")
        submit_btn.clicked.connect(self.on_submit)
        
        btn_layout.addStretch()
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(submit_btn)
        inner_layout.addLayout(btn_layout)

        layout.addWidget(container)
        
        # Conectar Enter en el QLineEdit
        self.input_field.returnPressed.connect(self.on_submit)
        
        self.resize(400, 120)
        self.center_on_screen()

    def center_on_screen(self):
        screen = QApplication.primaryScreen().availableGeometry()
        self.move((screen.width() - self.width()) // 2, (screen.height() - self.height()) // 2)

    def showEvent(self, event):
        super().showEvent(event)
        self.input_field.clear()
        self.input_field.setFocus()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
        else:
            super().keyPressEvent(event)

    def on_submit(self):
        text = self.input_field.text().strip()
        if text:
            self.submitted.emit(text)
            self.accept()
        else:
            self.reject()


class AvatarWindow(QMainWindow):
    """
    Ventana principal del avatar. Transparente, sin bordes, siempre visible.
    Controla los estados y la animación de Lip-Sync del avatar.
    """
    def __init__(self, config_manager: ConfigManager):
        super().__init__()
        self.config_manager = config_manager
        
        # Estado de los modelos y del pipeline
        self.whisper = None
        self.llama = None
        self.kokoro = None
        self.pipeline_worker = None
        self.audio_recorder = None
        
        # Rutas de imágenes
        self.avatar_dir = "/home/maximo/Código/Python/Llama-assistant/avatar"
        
        self.drag_position = QPoint()
        self.is_recording = False
        self.is_thinking_or_speaking = False

        # Estado del avatar (matriz de animación)
        self.eyes_state = "open"
        self.mouth_state = "closed"
        self.avatar_status = "quiet"

        # Temporizador para auto-ocultación de la ventana (10 segundos)
        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self.hide_avatar)

        # Temporizador para parpadeo aleatorio
        self.blink_timer = QTimer(self)
        self.blink_timer.setSingleShot(True)
        self.blink_timer.timeout.connect(self.trigger_blink)

        self.init_window_properties()
        self.init_ui()
        self.preload_pixmaps()
        self.update_avatar_display()
        self.schedule_next_blink()

        # Iniciar carga de modelos en segundo plano
        self.start_model_loading()

    def init_window_properties(self):
        # Frameless, Always on Top, Tool window flag (prevents KWin taskbar clutter and forces standard positioning)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | 
            Qt.WindowType.WindowStaysOnTopHint | 
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(280, 360)
        self.reposition_window()

    def reposition_window(self):
        """Mueve la ventana a la posición configurada en pantalla utilizando la geometría del escritorio principal."""
        screen = QApplication.primaryScreen().availableGeometry()
        pos = self.config_manager.avatar_position
        
        w = 280
        h = 360
        margin_x = 40
        margin_y = 60
        
        if pos == "top_left":
            x = margin_x
            y = margin_x
        elif pos == "top_right":
            x = screen.width() - w - margin_x
            y = margin_x
        elif pos == "center":
            x = (screen.width() - w) // 2
            y = (screen.height() - h) // 2
        elif pos == "bottom_left":
            x = margin_x
            y = screen.height() - h - margin_y
        else:  # "bottom_right" por defecto
            x = screen.width() - w - margin_x
            y = screen.height() - h - margin_y
            
        self.setGeometry(x, y, w, h)

    def showEvent(self, event):
        super().showEvent(event)
        # Ejecutar el reposicionamiento 100ms después de que KWin mapee la ventana
        # para forzar la posición e impedir que la centre de forma predeterminada
        QTimer.singleShot(100, self.reposition_window)

    def init_ui(self):
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # Contenedor de la imagen del avatar
        self.avatar_label = QLabel(self)
        self.avatar_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.avatar_label.setFixedSize(250, 250)
        layout.addWidget(self.avatar_label)

        # Burbuja de texto (Status y transcripción/respuestas) dentro de un ScrollArea
        self.status_label = QLabel("Cargando...", self)
        self.status_label.setWordWrap(True)
        self.status_label.setTextFormat(Qt.TextFormat.MarkdownText)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("""
            background-color: rgba(33, 33, 44, 210);
            border: 1px solid rgba(255, 60, 60, 60);
            border-radius: 12px;
            color: #ffffff;
            font-size: 11px;
            font-family: 'Outfit', 'Inter', 'Segoe UI', sans-serif;
            padding: 8px;
        """)

        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll_area.setWidget(self.status_label)
        self.scroll_area.setStyleSheet("""
            QScrollArea {
                background: transparent;
                border: none;
            }
            QScrollBar:vertical {
                border: none;
                background: rgba(33, 33, 44, 100);
                width: 6px;
                margin: 0px 0px 0px 0px;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical {
                background: rgba(255, 60, 60, 150);
                min-height: 20px;
                border-radius: 3px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                border: none;
                background: none;
            }
        """)
        layout.addWidget(self.scroll_area)

    def preload_pixmaps(self):
        """Pre-carga en memoria todos los cuadros del avatar, unificando su tamaño al canvas máximo."""
        self.pixmaps = {}
        images = ["quiet.png", "cm-ce.png", "om-oe.png", "om-ce.png", "listen.png"]
        
        raw_pixmaps = {}
        max_w = 0
        max_h = 0
        
        # 1. Cargar las imágenes originales y buscar las dimensiones máximas
        for img in images:
            path = os.path.join(self.avatar_dir, img)
            if os.path.exists(path):
                pixmap = QPixmap(path)
                raw_pixmaps[img] = pixmap
                if pixmap.width() > max_w:
                    max_w = pixmap.width()
                if pixmap.height() > max_h:
                    max_h = pixmap.height()
            else:
                print(f"Error: No se encontró la imagen {path}")
        
        if not raw_pixmaps:
            return
            
        print(f"Dimensiones máximas unificadas para evitar saltos: {max_w}x{max_h}px")
        
        # 2. Redimensionar cada imagen al canvas máximo centrando el dibujo
        for img, pixmap in raw_pixmaps.items():
            unified_pixmap = QPixmap(max_w, max_h)
            unified_pixmap.fill(Qt.GlobalColor.transparent)
            
            painter = QPainter(unified_pixmap)
            # Calcular posición superior izquierda para centrar
            x = (max_w - pixmap.width()) // 2
            y = (max_h - pixmap.height()) // 2
            painter.drawPixmap(x, y, pixmap)
            painter.end()
            
            self.pixmaps[img] = unified_pixmap

    def set_avatar_image(self, img_name: str):
        """Actualiza la imagen en pantalla a partir del diccionario precargado."""
        pixmap = self.pixmaps.get(img_name)
        if not pixmap:
            # Si no está cargada (ej. cargando por primera vez), intentar cargarla o usar quiet.png como fallback
            path = os.path.join(self.avatar_dir, img_name)
            if os.path.exists(path):
                pixmap = QPixmap(path)
                self.pixmaps[img_name] = pixmap
            else:
                pixmap = self.pixmaps.get("quiet.png")
                if not pixmap:
                    path_quiet = os.path.join(self.avatar_dir, "quiet.png")
                    if os.path.exists(path_quiet):
                        pixmap = QPixmap(path_quiet)
                        self.pixmaps["quiet.png"] = pixmap

        if pixmap:
            # Mantener márgenes estables (6px arriba/abajo) para evitar saltos
            self.avatar_label.setContentsMargins(0, 6, 0, 6)

            scaled = pixmap.scaled(
                self.avatar_label.width() - 12,  # Dejar espacio para márgenes
                self.avatar_label.height() - 12,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.avatar_label.setPixmap(scaled)

    def update_avatar_display(self):
        """Actualiza el avatar en pantalla según el estado actual (matriz de estados)."""
        if self.avatar_status == "listening":
            img_name = "listen.png"
        else:
            if self.mouth_state == "closed":
                if self.eyes_state == "closed":
                    img_name = "cm-ce.png"
                else:
                    img_name = "quiet.png"
            else: # open
                if self.eyes_state == "closed":
                    img_name = "om-ce.png"
                else:
                    img_name = "om-oe.png"
        self.set_avatar_image(img_name)

    def schedule_next_blink(self):
        import random
        # Parpadeo aleatorio cada 2.5 a 5.5 segundos
        interval = random.randint(2500, 5500)
        self.blink_timer.start(interval)

    def trigger_blink(self):
        if self.avatar_status in ("quiet", "listening"):
            self.eyes_state = "open"
            self.schedule_next_blink()
            return

        self.eyes_state = "closed"
        self.update_avatar_display()
        QTimer.singleShot(150, self.finish_blink)

    def finish_blink(self):
        self.eyes_state = "open"
        self.update_avatar_display()
        self.schedule_next_blink()

    @pyqtSlot(str)
    def on_mouth_state_changed(self, state: str):
        """Actualiza el estado de la boca y redibuja el avatar."""
        if state in ("open", "closed"):
            self.mouth_state = state
            self.update_avatar_display()

    # --- Carga de Modelos ---
    def start_model_loading(self):
        self.loader_thread = ModelLoaderThread(self.config_manager)
        self.loader_thread.status_changed.connect(self.update_status)
        self.loader_thread.loading_finished.connect(self.on_models_loaded)
        self.loader_thread.loading_failed.connect(self.on_models_failed)
        self.loader_thread.start()

    @pyqtSlot(str)
    def update_status(self, text: str):
        self.status_label.setText(text)
        if text.startswith("Hablando..."):
            self.avatar_status = "speaking"
            self.update_avatar_display()

    @pyqtSlot(object, object, object)
    def on_models_loaded(self, whisper, llama, kokoro):
        self.whisper = whisper
        self.llama = llama
        self.kokoro = kokoro
        self.status_label.setText("Listo (Manten Ctrl + Alt + J)")
        
        # Ocultar la ventana automáticamente tras 10 segundos
        self.hide_timer.start(10000)
        
        # Inicializar el atajo global de teclado con señales Qt para seguridad de hilos
        self.hotkey_listener = HotkeyListener()
        self.hotkey_listener.pressed.connect(self.on_hotkey_pressed)
        self.hotkey_listener.released.connect(self.on_hotkey_released)
        self.hotkey_listener.text_trigger.connect(self.on_text_hotkey_triggered)
        self.hotkey_listener.start()

    @pyqtSlot(str)
    def on_models_failed(self, error_msg: str):
        self.status_label.setText(f"Error al cargar modelos: {error_msg}")
        QMessageBox.critical(
            self, 
            "Error de Inicialización", 
            f"No se pudieron cargar los modelos locales:\n{error_msg}\n\nAbriendo configuración..."
        )
        self.open_settings()

    # --- Acciones de Eventos del Ratón (Ventana Draggable y Context Menu) ---
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()

    def contextMenuEvent(self, event):
        context_menu = QMenu(self)
        
        config_action = QAction("Configuración", self)
        config_action.triggered.connect(self.open_settings)
        context_menu.addAction(config_action)
        
        exit_action = QAction("Salir", self)
        exit_action.triggered.connect(QApplication.quit)
        context_menu.addAction(exit_action)
        
        context_menu.exec(QCursor.pos())

    def open_settings(self):
        # Detener la escucha de teclado momentáneamente
        if hasattr(self, 'hotkey_listener'):
            self.hotkey_listener.stop()

        dialog = SettingsDialog(self.config_manager, self)
        if dialog.exec() == SettingsDialog.DialogCode.Accepted:
            # Reposicionar ventana dinámicamente
            self.reposition_window()
            # Si se guardó nueva configuración, recargar modelos
            self.start_model_loading()
        else:
            # Si cancela, reanudar escucha de teclado
            if hasattr(self, 'hotkey_listener'):
                self.hotkey_listener.start()

    @pyqtSlot()
    def on_text_hotkey_triggered(self):
        """Se activa al pulsar Ctrl + Alt + K."""
        print("Atajo Ctrl + Alt + K detectado. Abriendo ventana de texto.")
        # Detener temporizador de ocultación y asegurar visibilidad de la ventana del avatar
        self.hide_timer.stop()
        if self.isHidden():
            self.show()
            self.raise_()
            self.activateWindow()

        # Si ya estamos grabando, no hacer nada
        if self.is_recording:
            return

        # Limpiar atajos presionados para evitar estados bloqueados
        if hasattr(self, 'hotkey_listener') and self.hotkey_listener:
            self.hotkey_listener.clear_keys()

        # Interrumpir habla si está activa
        if self.is_thinking_or_speaking:
            print("Interrumpiendo reproducción en curso por solicitud de prompt de texto.")
            if self.pipeline_worker and self.pipeline_worker.isRunning():
                try:
                    self.pipeline_worker.status_changed.disconnect()
                    self.pipeline_worker.transcription_done.disconnect()
                    self.pipeline_worker.llm_token_received.disconnect()
                    self.pipeline_worker.pipeline_finished.disconnect()
                    self.pipeline_worker.pipeline_error.disconnect()
                    self.pipeline_worker.change_mouth_image.disconnect()
                except Exception:
                    pass
                self.pipeline_worker.stop()
            self.is_thinking_or_speaking = False
            self.avatar_status = "quiet"
            self.mouth_state = "closed"
            self.eyes_state = "open"
            self.update_avatar_display()
            self.status_label.setText("Listo (Manten Ctrl + Alt + J)")

        # Abrir la ventana de prompt de texto
        if not hasattr(self, 'text_input_window'):
            self.text_input_window = TextInputWindow(self)
            self.text_input_window.submitted.connect(self.on_text_prompt_submitted)
            self.text_input_window.rejected.connect(self.on_text_prompt_rejected)
        
        self.text_input_window.show()
        self.text_input_window.raise_()
        self.text_input_window.activateWindow()

    @pyqtSlot()
    def on_text_prompt_rejected(self):
        """Se activa si el usuario cancela la ventana de texto."""
        print("Ventana de prompt cancelada - Iniciando temporizador de ocultación (10s).")
        if hasattr(self, 'hotkey_listener') and self.hotkey_listener:
            self.hotkey_listener.clear_keys()
        self.hide_timer.start(10000)  # Ocultar tras 10 segundos

    @pyqtSlot(str)
    def on_text_prompt_submitted(self, prompt_text: str):
        """Se activa al enviar el prompt desde la ventana de texto."""
        print(f"Prompt de texto enviado: {prompt_text}")
        if hasattr(self, 'hotkey_listener') and self.hotkey_listener:
            self.hotkey_listener.clear_keys()
        self.is_thinking_or_speaking = True
        self.avatar_status = "thinking"
        self.mouth_state = "closed"
        self.update_avatar_display()
        self.status_label.setText("Procesando...")

        # Lanzar el pipeline pasándole directamente el prompt_text
        self.pipeline_worker = SpeechPipelineWorker(
            whisper=self.whisper,
            llama=self.llama,
            kokoro=self.kokoro,
            audio_data=None,
            config=self.config_manager,
            text_prompt=prompt_text
        )
        
        # Conectar señales
        self.pipeline_worker.status_changed.connect(self.update_status)
        self.pipeline_worker.transcription_done.connect(self.on_transcription_done)
        self.pipeline_worker.llm_token_received.connect(self.on_llm_token)
        self.pipeline_worker.change_mouth_image.connect(self.on_mouth_state_changed)
        self.pipeline_worker.pipeline_finished.connect(self.on_pipeline_finished)
        self.pipeline_worker.pipeline_error.connect(self.on_pipeline_error)
        
        self.pipeline_worker.start()

    # --- Pipeline de Grabación y Procesamiento (Walkie-Talkie) ---
    def on_hotkey_pressed(self):
        """Se activa al mantener pulsado el atajo."""
        # Detener temporizador de ocultación y asegurar visibilidad de la ventana
        self.hide_timer.stop()
        if self.isHidden():
            self.show()
            self.raise_()
            self.activateWindow()

        # Ignorar si ya estamos ocupados grabando (pero NO si estamos pensando o hablando)
        if self.is_recording:
            return

        # Interrumpir el pipeline de habla si está en curso
        if self.is_thinking_or_speaking:
            print("Interrumpiendo reproducción en curso para escuchar de nuevo.")
            if self.pipeline_worker and self.pipeline_worker.isRunning():
                try:
                    # Desconectar señales de GUI para evitar interferencias
                    self.pipeline_worker.status_changed.disconnect()
                    self.pipeline_worker.transcription_done.disconnect()
                    self.pipeline_worker.llm_token_received.disconnect()
                    self.pipeline_worker.pipeline_finished.disconnect()
                    self.pipeline_worker.pipeline_error.disconnect()
                    self.pipeline_worker.change_mouth_image.disconnect()
                except Exception:
                    pass
                self.pipeline_worker.stop()
            self.is_thinking_or_speaking = False

        print("Atajo presionado - Iniciando grabación.")
        self.is_recording = True
        self.avatar_status = "listening"
        self.mouth_state = "closed"
        self.update_avatar_display()
        self.status_label.setText("Escuchando...")

        # Iniciar grabación
        self.audio_recorder = AudioRecorder(device_index=self.config_manager.input_device_index)
        self.audio_recorder.start_recording()

    def on_hotkey_released(self):
        """Se activa al soltar el atajo."""
        if not self.is_recording:
            return

        print("Atajo soltado - Procesando audio.")
        self.is_recording = False
        self.is_thinking_or_speaking = True
        self.avatar_status = "thinking"
        self.mouth_state = "closed"
        self.update_avatar_display()
        self.status_label.setText("Procesando...")

        # Detener la grabación y obtener los datos
        audio_data = self.audio_recorder.stop_recording()
        
        # Verificar que se grabó audio
        if len(audio_data) < 16000 * 0.5:  # menos de medio segundo
            self.status_label.setText("Grabación demasiado corta.")
            self.is_thinking_or_speaking = False
            self.avatar_status = "quiet"
            self.mouth_state = "closed"
            self.update_avatar_display()
            self.status_label.setText("Listo (Manten Ctrl + Alt + J)")
            self.hide_timer.start(10000)  # Ocultar tras 10 segundos
            return

        # Lanzar el pipeline
        self.pipeline_worker = SpeechPipelineWorker(
            whisper=self.whisper,
            llama=self.llama,
            kokoro=self.kokoro,
            audio_data=audio_data,
            config=self.config_manager
        )
        
        # Conectar señales
        self.pipeline_worker.status_changed.connect(self.update_status)
        self.pipeline_worker.transcription_done.connect(self.on_transcription_done)
        self.pipeline_worker.llm_token_received.connect(self.on_llm_token)
        self.pipeline_worker.change_mouth_image.connect(self.on_mouth_state_changed)
        self.pipeline_worker.pipeline_finished.connect(self.on_pipeline_finished)
        self.pipeline_worker.pipeline_error.connect(self.on_pipeline_error)
        
        self.pipeline_worker.start()

    @pyqtSlot(str)
    def on_transcription_done(self, text: str):
        print(f"Usuario: {text}")
        self.status_label.setText(f"Tú: {text}")
        # Limpiar texto para empezar a acumular respuesta del LLM
        self.llm_response_text = ""

    @pyqtSlot(str)
    def on_llm_token(self, token: str):
        # Acumular y mostrar la respuesta en streaming
        if not hasattr(self, 'llm_response_text'):
            self.llm_response_text = ""
        self.llm_response_text += token
        
        # Reemplazar etiquetas <cmd> y </cmd> por bloques de código Markdown
        display_text = self.llm_response_text.replace("<cmd>", " `").replace("</cmd>", "` ")
        self.status_label.setText(display_text)

        # Auto-scroll al fondo para ver los nuevos tokens
        scrollbar = self.scroll_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    @pyqtSlot()
    def on_pipeline_finished(self):
        print("Pipeline finalizado correctamente.")
        self.is_thinking_or_speaking = False
        self.avatar_status = "quiet"
        self.mouth_state = "closed"
        self.eyes_state = "open"
        self.update_avatar_display()
        self.status_label.setText("Listo (Manten Ctrl + Alt + J)")
        self.hide_timer.start(10000)  # Ocultar tras 10 segundos

    @pyqtSlot(str)
    def on_pipeline_error(self, err_msg: str):
        print(f"Error en pipeline: {err_msg}")
        self.is_thinking_or_speaking = False
        self.avatar_status = "quiet"
        self.mouth_state = "closed"
        self.eyes_state = "open"
        self.update_avatar_display()
        self.status_label.setText(f"Error: {err_msg}")
        self.hide_timer.start(10000)  # Ocultar tras 10 segundos

    def hide_avatar(self):
        print("hide_avatar llamado - Ocultando ventana del avatar.")
        self.status_label.setText("Listo (Manten Ctrl + Alt + J)")
        self.hide()

    def closeEvent(self, event):
        """Limpieza al cerrar la aplicación."""
        if hasattr(self, 'hide_timer'):
            self.hide_timer.stop()
        if hasattr(self, 'hotkey_listener'):
            self.hotkey_listener.stop()
        if self.pipeline_worker and self.pipeline_worker.isRunning():
            self.pipeline_worker.stop()
            self.pipeline_worker.wait()
        event.accept()
