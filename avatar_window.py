import os
import numpy as np
from PyQt6.QtWidgets import QMainWindow, QWidget, QLabel, QVBoxLayout, QMenu, QMessageBox, QApplication
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

    def __init__(self):
        super().__init__()
        self.active_keys = set()
        self.is_triggered = False
        self.listener = None

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
            # Combinación Ctrl + Alt + J
            if "ctrl" in self.active_keys and "alt" in self.active_keys and "j" in self.active_keys:
                if not self.is_triggered:
                    self.is_triggered = True
                    self.pressed.emit()

    def on_release(self, key):
        name = self._get_key_name(key)
        if name:
            if name in self.active_keys:
                self.active_keys.remove(name)
            
            # Si estaba activo y se suelta alguna de las teclas del atajo
            if self.is_triggered and (name in ("ctrl", "alt", "j")):
                self.is_triggered = False
                self.released.emit()


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

        # Temporizador para auto-ocultación de la ventana (10 segundos)
        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self.hide_avatar)

        self.init_window_properties()
        self.init_ui()
        self.preload_pixmaps()
        self.set_avatar_image("Callado.png")

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

        # Burbuja de texto (Status y transcripción/respuestas)
        self.status_label = QLabel("Cargando...", self)
        self.status_label.setWordWrap(True)
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
        layout.addWidget(self.status_label)

    def preload_pixmaps(self):
        """Pre-carga en memoria todos los cuadros del avatar, unificando su tamaño al canvas máximo."""
        self.pixmaps = {}
        images = ["Callado.png", "Escucha.png", "CH-I-S.png", "L-R.png", "M-B-V-F-P.png", "O.png", "R.png"]
        
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
        """Actualiza la imagen en pantalla a partir del diccionario precargado, con rebote de habla."""
        pixmap = self.pixmaps.get(img_name)
        if not pixmap:
            # Si no está cargada (ej. cargando por primera vez), intentar cargarla
            path = os.path.join(self.avatar_dir, img_name)
            if os.path.exists(path):
                pixmap = QPixmap(path)
                self.pixmaps[img_name] = pixmap

        if pixmap:
            # Aplicar un rebote/movimiento vertical sutil si está hablando
            offset_y = 0
            if self.is_thinking_or_speaking and img_name not in ("Callado.png", "Escucha.png"):
                if not hasattr(self, '_bounce_state'):
                    self._bounce_state = 0
                self._bounce_state = (self._bounce_state + 1) % 4
                if self._bounce_state in (1, 2):
                    offset_y = -6  # Subir 6px
            
            # Aplicar márgenes para simular rebote
            self.avatar_label.setContentsMargins(0, 6 + offset_y, 0, 6 - offset_y)

            scaled = pixmap.scaled(
                self.avatar_label.width() - 12,  # Dejar espacio para márgenes
                self.avatar_label.height() - 12,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.avatar_label.setPixmap(scaled)

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

    # --- Pipeline de Grabación y Procesamiento (Walkie-Talkie) ---
    def on_hotkey_pressed(self):
        """Se activa al mantener pulsado el atajo."""
        # Detener temporizador de ocultación y asegurar visibilidad de la ventana
        self.hide_timer.stop()
        if self.isHidden():
            self.show()
            self.raise_()
            self.activateWindow()

        # Ignorar si ya estamos ocupados procesando o hablando
        if self.is_recording or self.is_thinking_or_speaking:
            return

        print("Atajo presionado - Iniciando grabación.")
        self.is_recording = True
        self.set_avatar_image("Escucha.png")
        self.status_label.setText("Escuchando...")

        # Detener cualquier reproducción en curso si el pipeline estaba corriendo
        if self.pipeline_worker and self.pipeline_worker.isRunning():
            self.pipeline_worker.stop()

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
        self.set_avatar_image("Callado.png")
        self.status_label.setText("Procesando...")

        # Detener la grabación y obtener los datos
        audio_data = self.audio_recorder.stop_recording()
        
        # Verificar que se grabó audio
        if len(audio_data) < 16000 * 0.5:  # menos de medio segundo
            self.status_label.setText("Grabación demasiado corta.")
            self.is_thinking_or_speaking = False
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
        self.pipeline_worker.change_mouth_image.connect(self.set_avatar_image)
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
        self.status_label.setText(self.llm_response_text)

    @pyqtSlot()
    def on_pipeline_finished(self):
        print("Pipeline finalizado correctamente.")
        self.is_thinking_or_speaking = False
        self.set_avatar_image("Callado.png")
        self.status_label.setText("Listo (Manten Ctrl + Alt + J)")
        self.hide_timer.start(10000)  # Ocultar tras 10 segundos

    @pyqtSlot(str)
    def on_pipeline_error(self, err_msg: str):
        print(f"Error en pipeline: {err_msg}")
        self.is_thinking_or_speaking = False
        self.set_avatar_image("Callado.png")
        self.status_label.setText(f"Error: {err_msg}")
        self.hide_timer.start(10000)  # Ocultar tras 10 segundos

    def hide_avatar(self):
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
