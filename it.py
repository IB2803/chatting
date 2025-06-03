import sys
import os
import requests
import json
import threading
import time
import socketio
from websocket import create_connection

from PyQt5.QtMultimedia import QSoundEffect
from PyQt5.QtWidgets import QFileDialog
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QListWidget, QTextEdit,
    QScrollArea, QFrame, QSizePolicy, QListWidgetItem, QGraphicsDropShadowEffect,
    QFileDialog, QMessageBox, QComboBox, QDialog
)
from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply # Untuk memuat gambar secara asinkron
from PyQt5.QtCore import pyqtSignal, Qt, QTimer, QUrl, QMimeData, QDir, QStandardPaths
from PyQt5.QtGui import QColor, QFont, QPainter, QBrush, QPalette, QPixmap, QIcon, QDesktopServices, QImage


# Suppress font warnings
os.environ['QT_LOGGING_RULES'] = 'qt.qpa.fonts=false'

IP = "192.168.79.125"
# IP = "192.168.1.7"
PORT = "5000"

# BASE_URL = "http://localhost:5000"
# BASE_URL = "http://192.168.46.6:5000"  # Ganti <IP_KANTOR> dengan IP server
# BASE_URL = "http://192.168.45.137:5000"  # Ganti <IP_KANTOR> dengan IP server
BASE_URL = f"http://{IP}:{PORT}"   

def is_image_file(filename_or_path):
    if not filename_or_path:
        return False
    filename = os.path.basename(filename_or_path)
    return filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif'))


class FilePasteTextEdit(QTextEdit):
    def __init__(self, parent_chat_window, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.parent_chat_window = parent_chat_window
        self.setAcceptRichText(True)

    def canInsertFromMimeData(self, source: QMimeData) -> bool:
        return source.hasUrls() or source.hasImage() or super().canInsertFromMimeData(source)

    def insertFromMimeData(self, source: QMimeData) -> None:
        processed_something = False # Flag untuk menandai apakah kita sudah menangani sesuatu

        if source.hasUrls():
            for url in source.urls():
                if url.isLocalFile():
                    file_path = url.toLocalFile()
                    print(f"File pasted from URL: {file_path}")
                    if hasattr(self.parent_chat_window, 'send_file') and self.parent_chat_window.current_conversation:
                        self.parent_chat_window.send_file(file_path)
                        processed_something = True
                    else:
                        print("Cannot send pasted file: No active conversation or send_file method missing.")
            
            if processed_something: # Jika file dari URL sudah diproses, jangan lakukan apa-apa lagi.
                return 
            # Jika URL bukan file lokal, atau tidak ada file lokal, biarkan super() yang menangani jika ada teks.
            # Jika tidak, paste URL sebagai teks jika itu yang diinginkan (biasanya tidak untuk file paste)

        elif source.hasImage(): # MENANGANI GAMBAR DARI CLIPBOARD (misalnya Snipping Tool)
            image: QImage = source.imageData() # Dapatkan QImage
            if image and not image.isNull():
                try:
                    # Buat nama file temporer yang unik
                    # Menggunakan direktori cache aplikasi adalah praktik yang baik
                    cache_dir = QStandardPaths.writableLocation(QStandardPaths.CacheLocation)
                    if not cache_dir: # Fallback ke direktori temp sistem jika cache_dir tidak tersedia
                        cache_dir = QDir.tempPath()
                    
                    app_temp_subdir = os.path.join(cache_dir, "ITSupportChatCache") # Subdirektori khusus
                    if not os.path.exists(app_temp_subdir):
                        os.makedirs(app_temp_subdir, exist_ok=True)

                    filename = f"pasted_image_{int(time.time() * 1000)}.png" # Nama file dengan timestamp milidetik
                    temp_file_path = os.path.join(app_temp_subdir, filename)

                    # Simpan QImage ke file temporer (PNG adalah format yang baik untuk screenshot)
                    if image.save(temp_file_path, "PNG", quality=90): # quality 0-100, -1 default
                        print(f"Pasted image saved to temporary file: {temp_file_path}")
                        if hasattr(self.parent_chat_window, 'send_file') and self.parent_chat_window.current_conversation:
                            self.parent_chat_window.send_file(temp_file_path)
                            # Di sini, kita tidak langsung menghapus temp_file_path karena send_file mungkin asinkron.
                            # Manajemen file temporer bisa lebih kompleks (misalnya, hapus setelah upload berhasil,
                            # atau bersihkan folder temp saat aplikasi ditutup/dimulai).
                            # Untuk saat ini, file akan tersimpan di folder cache/temp.
                            processed_something = True
                        else:
                            print("Cannot send pasted image: No active conversation or send_file method missing.")
                    else:
                        print(f"Failed to save pasted image to {temp_file_path}. Error: {image.save(temp_file_path, 'PNG')}")
                except Exception as e:
                    print(f"Error processing pasted image: {e}")
            
            if processed_something: # Jika gambar dari clipboard sudah diproses, jangan lakukan apa-apa lagi.
                return

        # Jika tidak ada URL file lokal atau gambar yang diproses,
        # atau jika ada data lain (seperti teks), biarkan handler default yang bekerja.
        if not processed_something:
            super().insertFromMimeData(source)
            
class WebSocketThread(threading.Thread):
    def __init__(self, chat_window):
        super().__init__()
        self.chat_window = chat_window
        
        self.sio = socketio.Client(logger=True, engineio_logger=True)
        self.setup_event_handlers()
        
        self.running = True
        
    def setup_event_handlers(self):
        # Handler untuk event koneksi berhasil
        @self.sio.event
        def connect():
            print("DEBUG: WebSocketThread (python-socketio) - Terhubung ke server Socket.IO!")

        # Handler untuk error koneksi
        @self.sio.event
        def connect_error(data):
            print(f"DEBUG: WebSocketThread (python-socketio) - Gagal terhubung: {data}")

        # Handler untuk event diskoneksi
        @self.sio.event
        def disconnect():
            print("DEBUG: WebSocketThread (python-socketio) - Terputus dari server Socket.IO.")

        # Handler untuk event 'new_message' dari server
        # Nama event 'new_message' harus sama dengan yang di-emit oleh server.py
        @self.sio.on('new_message')
        def on_new_message(data):
            # 'data' yang diterima di sini adalah payload yang dikirim server, yaitu:
            # {'conversation_id': ..., 'message': {'id': ..., 'sender_id': ..., ...}}
            print(f"DEBUG: WebSocketThread (python-socketio) - Menerima 'new_message': {data}")
            # Emit sinyal ke ChatWindow dengan payload ini.
            # Logika di ChatWindow.handle_received_message seharusnya sudah kompatibel.
            self.chat_window.receive_message_signal.emit(data)

        
    # def run(self):
    #     ws = create_connection("ws://192.168.45.137:5000")
    #     # ws = create_connection(f"ws://{BASE_URL.split('//')[1]}")
    #     while self.running:
    #         try:
    #             message = ws.recv()
    #             data = json.loads(message)
    #             if data.get('event') == 'new_message':
    #                 self.chat_window.receive_message_signal.emit(data['data'])
    #         except Exception as e:
    #             print("WebSocket error:", e)
    #             break
    #     ws.close()
        
    def run(self):
        # MODIFIKASI DI SINI: Tambahkan /socket.io/ pada URL
        print(f"DEBUG: WebSocketThread (python-socketio) - Mencoba terhubung ke http://{IP}:{PORT}")
        try:
            # Lakukan koneksi. Pustaka akan menangani handshake Engine.IO/Socket.IO.
            # Ia akan mencoba path default /socket.io/
            # 'transports=['websocket']' memaksa penggunaan WebSocket.
            self.sio.connect(f"http://{IP}:{PORT}", transports=['websocket'])
            
            # sio.wait() akan menjaga thread ini tetap aktif dan memproses event
            # sampai sio.disconnect() dipanggil atau koneksi terputus.
            self.sio.wait()
            print("DEBUG: WebSocketThread (python-socketio) - sio.wait() telah berhenti/unblocked.")

        except socketio.exceptions.ConnectionError as e:
            print(f"DEBUG: WebSocketThread (python-socketio) - Kesalahan koneksi: {e}")
        except Exception as e_run:
            # Tangkap error lain yang mungkin terjadi selama run
            print(f"DEBUG: WebSocketThread (python-socketio) - Error tak terduga di run(): {e_run}")
        finally:
            # Ini mungkin tidak akan tercapai jika sio.wait() berjalan terus atau jika error tidak tertangkap
            # Penutupan koneksi utama ada di metode stop().
            print("DEBUG: WebSocketThread (python-socketio) - Thread 'run' selesai atau keluar dari try-except.")

    def stop(self):
        print("DEBUG: WebSocketThread (python-socketio) - Metode stop() dipanggil.")
        if self.sio and self.sio.connected:
            print("DEBUG: WebSocketThread (python-socketio) - Memutuskan koneksi Socket.IO...")
            self.sio.disconnect()
        else:
            print("DEBUG: WebSocketThread (python-socketio) - Klien Socket.IO tidak terhubung atau sudah terputus.")

# class BubbleMessage(QLabel):
#     def __init__(self, text, is_me, sender_name, time, file_path=None, parent=None):
#         super().__init__(parent)
#         self.is_me = is_me
#         self.sender_name = sender_name
#         self.time = time
#         self.file_path = file_path
#         self.msg_id = None # Tambahkan untuk menyimpan ID pesan
        
#         self.setWordWrap(True)
#         self.setMargin(15)
#         self.setTextFormat(Qt.RichText)
        
#         display_text = text
#         # Jika Anda ingin menampilkan ikon atau nama file yang lebih bersih dari path:
#         # if self.file_path:
#         #     display_text = f"📄 File: {os.path.basename(self.file_path)}" 
#         # Namun, karena server sudah mengirimkan format "[File: namafile.ext]", kita bisa langsung gunakan 'text'.

#         if is_me:
#             message_html = f"""
#             <div style='font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; font-size: 15px; line-height: 1;'>
#                 <div style='color: #FFFFFF; margin-bottom: 8px;'>{display_text}</div>
#                 <div style='color: rgba(255,255,255,0.8); font-size: 11px; text-align: right; margin-top: 4px;'>{time}</div>
#             </div>"""
#             self.setStyleSheet("""
#                 BubbleMessage {
#                     background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #4A90E2, stop:1 #357ABD);
#                     border-radius: 18px;
#                     margin: 4px 4px 4px 60px; /* Margin untuk pesan 'saya' di it.py */
#                     max-width: 400px;
#                 }""")
#         else: # Pesan dari orang lain
#             message_html = f"""
#             <div style='font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; font-size: 15px; line-height: 1;'>
#                 <div style='color: #2C3E50; margin-bottom: 8px;'>{display_text}</div>
#                 <div style='color: #95A5A6; font-size: 11px; text-align: left; margin-top: 4px;'>{time}</div>
#             </div>"""
#             self.setStyleSheet("""
#                 BubbleMessage {
#                     background-color: #FFFFFF; border: 1px solid #E8ECEF; border-radius: 18px;
#                     margin: 4px 60px 4px 4px; /* Margin untuk pesan 'orang lain' di it.py */
#                     max-width: 400px;
#                 }""")

#         self.setText(message_html)
#         # Perataan (alignment) di it.py biasanya diatur oleh kontainer yang menambahkan addStretch.
#         # self.setAlignment(Qt.AlignLeft if not is_me else Qt.AlignRight) # Mungkin tidak diperlukan jika kontainer sudah mengatur
#         self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)

#         shadow = QGraphicsDropShadowEffect()
#         shadow.setBlurRadius(8); shadow.setColor(QColor(0, 0, 0, 20)); shadow.setOffset(0, 2)
#         self.setGraphicsEffect(shadow)
        
class BubbleMessage(QLabel):
    def __init__(self, text, is_me, sender_name, time, file_path=None, parent=None):
        super().__init__(parent)
        self.is_me = is_me
        self.sender_name = sender_name
        self.time = time
        self.original_file_path = file_path # Simpan path asli dari DB (mis. uploads/namafile.ext)
        self.filename_to_download = os.path.basename(file_path) if file_path else None # Hanya nama file (mis. namafile.ext)
        self.msg_id = None

        self.setWordWrap(True)
        self.setMargin(15)
        self.setTextFormat(Qt.RichText)
        
        import html
        processed_text = html.escape(text) # Pertama, escape HTML entities seperti <, >, &
        display_text = processed_text.replace('\n', '<br>') # Kemudian ganti newline dengan <br>
        
        
        # display_text = text

        if self.filename_to_download and text.startswith("[File:"):
            actual_filename_in_text = text[len("[File: "):-1]
            display_text = f"<a href='#' style='color: inherit; text-decoration: underline;'>📄 File: {actual_filename_in_text}</a>"

        if is_me:
            message_html = f"""
            <div style='font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; font-size: 15px; line-height: 1;'>
                <div style='color: #FFFFFF; margin-bottom: 8px;'>{display_text}</div>
                <div style='color: rgba(255,255,255,0.8); font-size: 11px; text-align: right; margin-top: 4px;'>{time}</div>
            </div>"""
            self.setStyleSheet("""
                BubbleMessage {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #4A90E2, stop:1 #357ABD);
                    border-radius: 18px;
                    margin: 4px 4px 4px 60px; 
                    max-width: 400px;
                }""")
        else: 
            message_html = f"""
            <div style='font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; font-size: 15px; line-height: 1;'>
                <div style='color: #2C3E50; margin-bottom: 8px;'>{display_text}</div>
                <div style='color: #95A5A6; font-size: 11px; text-align: left; margin-top: 4px;'>{time}</div>
            </div>"""
            self.setStyleSheet("""
                BubbleMessage {
                    background-color: #FFFFFF; border: 1px solid #E8ECEF; border-radius: 18px;
                    margin: 4px 60px 4px 4px; 
                    max-width: 400px;
                }""")

        self.setText(message_html)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)

        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(8); shadow.setColor(QColor(0, 0, 0, 20)); shadow.setOffset(0, 2)
        self.setGraphicsEffect(shadow)

        if self.filename_to_download:
            self.setOpenExternalLinks(False) 
            # self.linkActivated.connect(self.handle_link_click) # Tidak perlu jika mousePressEvent cukup

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.filename_to_download:
            download_url_str = f"{BASE_URL}/uploads/{self.filename_to_download}"
            print(f"Attempting to open URL for download: {download_url_str}")
            QDesktopServices.openUrl(QUrl(download_url_str))
            event.accept()
        else:
            super().mousePressEvent(event)

    def enterEvent(self, event):
        if self.filename_to_download:
            self.setCursor(Qt.PointingHandCursor)
        super().enterEvent(event)

    def leaveEvent(self, event):
        if self.filename_to_download:
            self.unsetCursor()
        super().leaveEvent(event)
 
class ConversationItem(QWidget):
    # Versi ini menggunakan 'last_message' yang di-pass saat inisialisasi
    def __init__(self, conversation_data, user_role, last_message_text="Click to start conversation"): # Terima last_message_text
        super().__init__()
        self.conversation_data = conversation_data
        
        processed_preview_text = last_message_text
        
        self.setup_ui(conversation_data, user_role, processed_preview_text)
        
    def setup_ui(self, conv, user_role, display_preview_text): # Terima last_message_text
        layout = QHBoxLayout()
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(12)
        
        avatar = QLabel()
        avatar.setFixedSize(48, 48)
        avatar.setStyleSheet("""
            QLabel {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #6C7CE7, stop:1 #A8E6CF);
                border-radius: 24px;
                color: white;
                font-weight: bold;
                font-size: 18px;
            }
        """)
        
        if user_role == 'employee':
            name = conv.get('tech_name', 'Tech')
        else:
            name = conv.get('employee_name', 'User')
        avatar.setText(name[0].upper() if name else "?") # Handle jika name None
        
        avatar.setAlignment(Qt.AlignCenter)
        layout.addWidget(avatar)
        
        info_layout = QVBoxLayout()
        info_layout.setSpacing(4)
        
        name_status_layout = QHBoxLayout()
        name_label = QLabel(name)
        name_label.setObjectName("nameLabel")
        name_label.setStyleSheet("""
            QLabel {
                font-size: 15px;
                font-weight: 600;
                color: #2C3E50;
                background-color: transparent;
            }
        """)
        name_status_layout.addWidget(name_label)
        
        if conv.get('status') == 'closed':
            status_label = QLabel("• Closed")
            status_label.setStyleSheet("color: #95A5A6; font-size: 12px;")
            name_status_layout.addWidget(status_label)
        
        name_status_layout.addStretch()
        info_layout.addLayout(name_status_layout)
        
        self.preview_label = QLabel(display_preview_text) # Gunakan display preview text yang diterima
        self.preview_label.setStyleSheet("""
            QLabel {
                color: #7F8C8D;
                background-color: transparent;
                font-size: 13px;
                white-space: nowrap;
                min-width: 200px;
                max-width: 200px;
            }
        """)
        # self.preview_label.setMaximumWidth(200) # Opsional, atur lebar jika perlu
        info_layout.addWidget(self.preview_label)
        
        layout.addLayout(info_layout)
        self.setLayout(layout)
        
       


class ChatWindow(QWidget):
    receive_message_signal = pyqtSignal(dict)
    
    def __init__(self, user, parent=None):
        super().__init__(parent)
        self.user = user
        self.current_conversation = None
        self.unread_map = {} 
        self.message_cache = {}
        self.setup_ui()
        self.load_conversations() # Panggil setelah setup_ui
        
            # --- INISIALISASI SUARA NOTIFIKASI ---
        self.message_sound = QSoundEffect(self) # 'self' sebagai parent

        # Tentukan path ke file suara
        # Asumsi 'notification.wav' ada di direktori yang sama dengan script
        sound_file_name = "akh.wav" 
        # Path bisa juga: os.path.join("sounds", "notification.wav") jika di subfolder 'sounds'

        # Dapatkan path direktori tempat script dijalankan
        current_script_dir = os.path.dirname(os.path.abspath(__file__))
        sound_file_path = os.path.join(current_script_dir, sound_file_name)

        if os.path.exists(sound_file_path):
            self.message_sound.setSource(QUrl.fromLocalFile(sound_file_path))
            self.message_sound.setVolume(1.0)  # Atur volume antara 0.0 (sunyi) dan 1.0 (maks)
            print(f"Sound effect loaded from: {sound_file_path}")
        else:
            print(f"WARNING: Sound file not found at '{sound_file_path}'. Sound notifications will be disabled.")
            self.message_sound = None # Nonaktifkan jika file tidak ditemukan
        # --- AKHIR INISIALISASI SUARA ---
        # Timer untuk refresh
        self.timer = QTimer(self)
        # self.timer.timeout.connect(self.refresh_messages)
        # self.timer.timeout.connect(self.load_conversations)
        # self.timer.start(5000) # Tingkatkan interval jika load_conversations tetap di timer
        
        # Jika tidak ada yang terhubung ke timer, kita tidak perlu start:
        active_timer_connections = self.timer.receivers(self.timer.timeout) # Cek apakah ada koneksi
        if active_timer_connections > 0 : # Jika masih ada koneksi lain (misal load_conversations berkala kamu aktifkan lagi)
             print(f"DEBUG: Timer masih memiliki {active_timer_connections} koneksi aktif, memulai timer.")
             self.timer.start(5000) 
        else:
            print("DEBUG: Tidak ada koneksi ke timer, timer tidak di-start.")
        
        self.receive_message_signal.connect(self.handle_received_message)
        self.ws_thread = WebSocketThread(self)
        self.ws_thread.start()
        


    def setup_ui(self):
        self.setWindowTitle(f"IT Support Chat - {self.user['full_name']} ({self.user['role'].title()})")
        self.resize(1200, 800)
        
        # Main layout
        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Left Sidebar
        sidebar = QFrame()
        sidebar.setFixedWidth(360)
        sidebar.setStyleSheet("""
            QFrame {
                background-color: #FFFFFF;
                
            }
        """)
        
        sidebar_layout = QVBoxLayout()
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)
        
        # Sidebar header
        header_widget = QWidget()
        header_widget.setFixedHeight(70)
        header_widget.setStyleSheet("""
            QWidget {
                background-color: #3D82CA;
                
            }
        """)
        
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(20, 15, 20, 15)
        
        # App title with icon
        title_layout = QHBoxLayout()
        title_layout.setSpacing(8)
        
        # Message icon
        # icon_label = QLabel("💬")
        # icon_label.setStyleSheet("font-size: 20px;")
        # title_layout.addWidget(icon_label)
        
        # title_label = QLabel("Messages")
        # title_label.setStyleSheet("""
        #     QLabel {
        #         font-size: 20px;
        #         font-weight: 700;
        #         color: #FFFFFF;
        #     }
        # """)
        # title_layout.addWidget(title_label)
        # title_layout.addStretch()
        
        # header_layout.addLayout(title_layout)
        # header_widget.setLayout(header_layout)
        # sidebar_layout.addWidget(header_widget)
        
        # Search bar
        search_widget = QWidget()
        search_widget.setFixedHeight(60)
        search_widget.setStyleSheet("background-color: #FFFFFF;")
        
        search_layout = QHBoxLayout()
        search_layout.setContentsMargins(20, 10, 20, 10)
        
        search_input = QLineEdit()
        search_input.setPlaceholderText("🔍 Search messages...")
        search_input.setStyleSheet("""
            QLineEdit {
                background-color: #F1F3F4;
                border: none;
                border-radius: 20px;
                padding: 10px 16px;
                font-size: 14px;
                color: #2C3E50;
            }
            QLineEdit:focus {
                background-color: #FFFFFF;
                border: 2px solid #4A90E2;
            }
        """)
        search_layout.addWidget(search_input)
        search_widget.setLayout(search_layout)
        sidebar_layout.addWidget(search_widget)
        
        # Conversations list
        self.conversation_list = QListWidget()
        self.conversation_list.setStyleSheet("""
            QListWidget {
                background-color: #FFFFFF;
                border: none;
                outline: none;
            }
            QListWidget::item {
                border: none;
                padding: 0px;
                margin: 0px;
            }
            QListWidget::item:selected {
                background-color: transparent;
                border-left: 9px solid #4A90E2;
            
                
            }
        """)
        self.conversation_list.itemClicked.connect(self.select_conversation)
        sidebar_layout.addWidget(self.conversation_list)
        
        # New chat button (for employees)
        # if self.user['role'] == 'technician': 
        #     button_widget = QWidget()
        #     button_widget.setFixedHeight(80)
        #     button_widget.setStyleSheet("background-color: #FFFFFF; border-top: 1px solid #E8ECEF;")
            
        #     button_layout = QHBoxLayout()
        #     button_layout.setContentsMargins(20, 20, 20, 20)
            
        #     self.new_chat_btn = QPushButton("✨ New Ticket")
        #     self.new_chat_btn.setStyleSheet("""
        #         QPushButton {
        #             background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
        #                 stop:0 #4A90E2, stop:1 #357ABD);
        #             color: white;
        #             border: none;
        #             padding: 12px 24px;
        #             border-radius: 20px;
        #             font-size: 14px;
        #             font-weight: 600;
        #         }
        #         QPushButton:hover {
        #             background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
        #                 stop:0 #357ABD, stop:1 #2E6DA4);
        #         }
        #         QPushButton:pressed {
        #             background: #2E6DA4;
        #         }
        #     """)
        #     self.new_chat_btn.clicked.connect(self.create_new_conversation)
        #     button_layout.addWidget(self.new_chat_btn)
        #     button_widget.setLayout(button_layout)
        #     sidebar_layout.addWidget(button_widget)
        
        # Dalam ChatWindow.setup_ui, di bagian sidebar_layout:
# ... (setelah self.new_chat_btn atau di tempat lain yang sesuai di sidebar) ...
        # button_layout = QHBoxLayout()
        # button_layout.setContentsMargins(20, 20, 20, 20)
        # self.add_user_btn = QPushButton("👤 Add User") # Atau "➕ New Contact"
        # self.add_user_btn.setStyleSheet("""
        #     QPushButton {
        #         background-color: #2ECC71; /* Warna hijau sebagai contoh */
        #         color: white;
        #         border: none;
        #         padding: 10px; /* Sesuaikan padding */
        #         border-radius: 18px; /* Sesuaikan border-radius */
        #         font-size: 13px; /* Sesuaikan font size */
        #         font-weight: 500;
        #         margin: 5px 50px; /* Margin atas/bawah dan kiri/kanan */
        #     }
        #     QPushButton:hover {
        #         background-color: #27AE60;
        #     }
        #     QPushButton:pressed {
        #         background-color: #1E8449;
        #     }
        # """)
        # self.add_user_btn.clicked.connect(self.handle_add_user_button_click) # Hubungkan ke handler
        # sidebar_layout.addWidget(self.add_user_btn) # Tambahkan ke layout sidebar
        
        # Tombol "Add User" (jika hanya untuk technician/admin)
        if self.user['role'] == 'technician': # Misal hanya teknisi yang bisa tambah user
            self.add_user_btn = QPushButton("👤 Add User")
            # ... (style dan connect add_user_btn seperti sebelumnya) ...
            self.add_user_btn.setStyleSheet("""
                QPushButton {
                    background-color: #2ECC71; color: white; border: none;
                    padding: 10px; border-radius: 18px; font-size: 13px;
                    font-weight: 500; margin: 5px 20px;
                }
                QPushButton:hover { background-color: #27AE60; }
                QPushButton:pressed { background-color: #1E8449; }
            """)
            self.add_user_btn.clicked.connect(self.handle_add_user_button_click)
            sidebar_layout.addWidget(self.add_user_btn)

            # Tombol "New Custom Conversation" untuk technician
            self.new_custom_conv_btn = QPushButton("💬+ New Custom Conversation")
            self.new_custom_conv_btn.setStyleSheet("""
                QPushButton {
                    background-color: #3498DB; /* Warna biru sebagai contoh */
                    color: white; border: none;
                    padding: 10px; border-radius: 18px; font-size: 13px;
                    font-weight: 500; margin: 5px 20px;
                }
                QPushButton:hover { background-color: #2980B9; }
                QPushButton:pressed { background-color: #1F618D; }
            """)
            self.new_custom_conv_btn.clicked.connect(self.handle_new_custom_conversation_click)
            sidebar_layout.addWidget(self.new_custom_conv_btn)
            
        chat_header_layout = QHBoxLayout()
        chat_header_layout.setContentsMargins(24, 15, 24, 15)        
        #  Tombol "Back" untuk kembali ke daftar percakapan
        self.back_button = QPushButton("⬅") # Atau gunakan QIcon jika punya ikon panah
        self.back_button.setFixedSize(30, 30)
        self.back_button.setStyleSheet("""
            QPushButton {
                color: white;
                font-size: 20px;
                font-weight: bold;
                border: none;
                border-radius: 15px; /* Membuatnya bulat */
                background-color: transparent; /* Transparan awal */
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.2); /* Efek hover */
            }
            QPushButton:pressed {
                background-color: rgba(255, 255, 255, 0.3); /* Efek tekan */
            }
        """)
        self.back_button.clicked.connect(self.go_back_to_selection_view)
        self.back_button.setVisible(False) # Sembunyikan di awal, tampilkan saat chat dipilih
        chat_header_layout.addWidget(self.back_button)
        
        
        
        sidebar.setLayout(sidebar_layout)
        main_layout.addWidget(sidebar)
        
        # Right side - Chat area
        chat_area = QVBoxLayout()
        chat_area.setContentsMargins(0, 0, 0, 0)
        chat_area.setSpacing(0)
        
        # Chat header
        self.chat_header_widget = QWidget()
        self.chat_header_widget.setFixedHeight(70)
        self.chat_header_widget.setStyleSheet("""
            QWidget {
                background-color: #3D82CA;
                
            }
        """)
        

        
        # User avatar and info
        self.chat_avatar = QLabel()
        self.chat_avatar.setFixedSize(40, 40)
        self.chat_avatar.setStyleSheet("""
            QLabel {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #A8E6CF, stop:1 #6C7CE7);
                border-radius: 20px;
                color: white;
                font-weight: bold;
                font-size: 16px;
            }
        """)
        self.chat_avatar.setAlignment(Qt.AlignCenter)
        chat_header_layout.addWidget(self.chat_avatar)
        
        # User info
        info_layout = QVBoxLayout()
        # info_layout.setSpacing(2)
        
        self.chat_name = QLabel("Select a conversation")
        self.chat_name.setStyleSheet("""
            QLabel {
                font-size: 16px;
                font-weight: 600;
                color: #FFFFFF;
            }
        """)
        info_layout.addWidget(self.chat_name)
        
        self.chat_status = QLabel("Choose a chat to start messaging")
        self.chat_status.setStyleSheet("""
            QLabel {
                font-size: 13px;
                color: #FFFFFF;
            }
        """)
        info_layout.addWidget(self.chat_status)
        
        chat_header_layout.addLayout(info_layout)
        chat_header_layout.addStretch()
        
        self.chat_header_widget.setLayout(chat_header_layout)
        chat_area.addWidget(self.chat_header_widget)
        
        # Messages area
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("""
            QScrollArea {
                background-color: #F5F7FA;
                border: none;
            }
            QScrollBar:vertical {
                border: none;
                background: transparent;
                width: 8px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: rgba(0,0,0,0.2);
                border-radius: 4px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(0,0,0,0.3);
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)
        
        self.messages_container = QWidget()
        self.messages_container.setStyleSheet("background-color: #F5F7FA;")
        self.messages_layout = QVBoxLayout()
        self.messages_layout.setContentsMargins(24, 20, 24, 20)
        self.messages_layout.setSpacing(8)
        self.messages_layout.addStretch(1)
        
        self.messages_container.setLayout(self.messages_layout)
        self.scroll_area.setWidget(self.messages_container)
        chat_area.addWidget(self.scroll_area)
        
        # Message input area
        input_area = QWidget()
        input_area.setFixedHeight(80)
        # input_area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)  
        input_area.setStyleSheet("""
            QWidget {
                background-color: #FFFFFF;
                border-top: 1px solid #E8ECEF;
            }
        """)
        
        input_layout = QHBoxLayout()
        input_layout.setContentsMargins(24, 16, 24, 16)
        input_layout.setSpacing(12)
        
    # Ganti attach_btn menjadi:
        self.attach_btn = QPushButton("📎")
        self.attach_btn.setFixedSize(40, 40)
        self.attach_btn.setStyleSheet("""
            QPushButton {
                background-color: #F1F3F4;
                border: none;
                border-radius: 20px;
                font-size: 16px;
            }
            QPushButton:hover {
                background-color: #E8ECEF;
            }
        """)
        self.attach_btn.clicked.connect(self.attach_file)
        input_layout.addWidget(self.attach_btn)
        
        # Message input
        # self.message_input = QTextEdit()
        self.message_input = FilePasteTextEdit(self)
        # self.message_input.setMaximumHeight(48)
        self.message_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.message_input.setPlaceholderText("Add a comment or paste a file...")
        self.message_input.setStyleSheet("""
            QTextEdit {
                background-color: #F1F3F4;
                border: none;
                border-radius: 24px;
                padding: 12px 16px;
                font-size: 14px;
                color: #2C3E50;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            }
            QTextEdit:focus {
                background-color: #FFFFFF;
                border: 2px solid #4A90E2;
            }
        """)
        input_layout.addWidget(self.message_input)
        
        # Send button
        self.send_btn = QPushButton("➤")
        self.send_btn.setFixedSize(40, 40)
        self.send_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                    stop:0 #4A90E2, stop:1 #357ABD);
                color: white;
                border: none;
                border-radius: 20px;
                font-size: 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                    stop:0 #357ABD, stop:1 #2E6DA4);
            }
        """)
        self.send_btn.clicked.connect(self.send_message)
        input_layout.addWidget(self.send_btn)
        
        input_area.setLayout(input_layout)
        chat_area.addWidget(input_area)
        
        main_layout.addLayout(chat_area)
        self.setLayout(main_layout)
        
        # Set overall background
        self.setStyleSheet("""
            QWidget {
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            }
        """)
    # Dalam kelas ChatWindow:
# ...
    # Dalam kelas ChatWindow:
# ...
    def update_chat_input_active_state(self, active: bool):
        """Mengatur status aktif/nonaktif untuk area input pesan."""
        self.message_input.setEnabled(active)
        self.send_btn.setEnabled(active)
        self.attach_btn.setEnabled(active)
        if active:
            self.message_input.setPlaceholderText("Add a comment or paste a file...")
        else:
            self.message_input.setPlaceholderText("Select a conversation to chat")
        # Seluruh input area bisa disembunyikan/ditampilkan jika diinginkan
    def update_chat_input_active_state(self, active: bool):
        """Mengatur status aktif/nonaktif untuk area input pesan."""
        self.message_input.setEnabled(active)
        self.send_btn.setEnabled(active)
        self.attach_btn.setEnabled(active)
        if active:
            self.message_input.setPlaceholderText("Add a comment or paste a file...")
        else:
            self.message_input.setPlaceholderText("Select a conversation to chat")
        # Seluruh input area bisa disembunyikan/ditampilkan jika diinginkan
        # self.input_area_widget.setVisible(active) # Opsional, jika ingin menyembunyikan seluruh bar input
    
    
    
    def handle_new_custom_conversation_click(self):
        dialog = CreateConversationDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            selected_ids = dialog.get_selected_ids()

            if selected_ids is None:
                QMessageBox.warning(self, "Selection Error", "Please select both an employee and a technician.")
                return

            if selected_ids['employee_id'] == selected_ids['technician_id']:
                QMessageBox.warning(self, "Selection Error", "Employee and Technician cannot be the same user.")
                return

            print(f"DEBUG: Attempting to create custom conversation with data: {selected_ids}")

            try:
                response = requests.post(f"{BASE_URL}/admin_create_conversation", json=selected_ids)
                response_data = response.json()

                if response.status_code == 200 and response_data.get('success'):
                    QMessageBox.information(self, "Success", response_data.get('message', "Conversation created successfully!"))
                    # Server sekarang mengirim 'conversation_created' via socket,
                    # jadi idealnya handle_conversation_created akan mengurus penambahan ke list.
                    # Jika tidak, atau sebagai fallback:
                    self.load_conversations() # Muat ulang daftar percakapan
                    # Anda bisa memilih untuk langsung membuka percakapan baru ini:
                    # new_conv_id = response_data.get('conversation_id')
                    # if new_conv_id:
                    #     self.select_conversation_by_id(new_conv_id)
                elif response_data.get('message'):
                    QMessageBox.warning(self, "Creation Failed", response_data.get('message'))
                else:
                    QMessageBox.critical(self, "Server Error", f"Server returned status {response.status_code}: {response.text}")

            except requests.exceptions.RequestException as e:
                QMessageBox.critical(self, "Connection Error", f"Could not connect to server: {e}")
            except json.JSONDecodeError:
                QMessageBox.critical(self, "Server Error", f"Invalid response from server: {response.text}")
            except Exception as e_generic:
                QMessageBox.critical(self, "Error", f"An unexpected error occurred: {e_generic}")

# Tambahkan juga handler untuk event socket 'conversation_created' jika Anda emit dari server
# Di dalam __init__ atau setup_event_handlers di WebSocketThread:
# @self.sio.on('conversation_created')
# def on_conversation_created(data):
#     print(f"DEBUG: WebSocketThread - Menerima 'conversation_created': {data}")
#     self.chat_window.new_conversation_signal.emit(data.get('conversation_data'))

# Di ChatWindow, definisikan sinyal dan slotnya:
# new_conversation_signal = pyqtSignal(dict) # Di atas __init__
# self.new_conversation_signal.connect(self.handle_newly_created_conversation) # Di __init__

# def handle_newly_created_conversation(self, conv_data):
#     print(f"DEBUG: ChatWindow - Menangani percakapan baru dari socket: {conv_data}")
#     # Logika untuk menambahkan atau memperbarui item percakapan di self.conversation_list
#     # Ini bisa lebih kompleks karena harus membuat QListWidgetItem dan ConversationItem baru
#     # Untuk cara paling mudah, panggil saja load_conversations()
#     self.load_conversations()
#     QMessageBox.information(self, "New Conversation", f"A new conversation involving {conv_data.get('employee_name')} and {conv_data.get('tech_name')} has been noted.")


# (Opsional) Helper untuk memilih percakapan berdasarkan ID setelah dibuat
# def select_conversation_by_id(self, conversation_id):
#     for i in range(self.conversation_list.count()):
#         item = self.conversation_list.item(i)
#         if item.data(Qt.UserRole) == conversation_id:
#             self.conversation_list.setCurrentItem(item)
#             self.select_conversation(item) # Panggil slot yang sudah ada
#             break

# ... (sisa metode ChatWindow)
    
    
    def handle_add_user_button_click(self):
        dialog = AddUserDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            user_data = dialog.get_data()

            # Validasi dasar untuk field yang selalu wajib
            if not user_data['username'] or not user_data['full_name']:
                QMessageBox.warning(self, "Input Error", "Username and Full Name cannot be empty.")
                return

            # Validasi password khusus untuk teknisi di sisi klien
            if user_data['role'] == 'technician' and not user_data['password']:
                QMessageBox.warning(self, "Input Error", "Password is required for the technician role.")
                return
            
            # Jika role adalah 'employee', password bisa kosong, jadi tidak ada cek khusus di sini.
            # Server akan menangani logika jika password dikirim kosong untuk employee.

            try:
                response = requests.post(f"{BASE_URL}/add_user", json=user_data)
                response_data = response.json() # Coba parse JSON di awal

                if response.status_code == 200 and response_data.get('success'):
                    QMessageBox.information(self, "Success", f"User '{user_data['username']}' added successfully!")
                    # Anda mungkin ingin me-refresh daftar kontak/user di sini jika ada
                elif response.status_code == 409 : # Username exists (atau error spesifik lain dari server)
                     QMessageBox.warning(self, "Conflict", f"Failed to add user: {response_data.get('message', 'Username already exists or conflict.')}")
                elif response.status_code == 400: # Bad request (misal, password kosong untuk teknisi dari server)
                     QMessageBox.warning(self, "Input Error", f"Failed to add user: {response_data.get('message', 'Invalid input.')}")
                else: # Error server lainnya atau error yang tidak spesifik
                    QMessageBox.critical(self, "Error", f"Failed to add user: {response_data.get('message', f'Server error {response.status_code}')}")
            
            except requests.exceptions.RequestException as e:
                QMessageBox.critical(self, "Connection Error", f"Could not connect to server: {e}")
            except json.JSONDecodeError: # Jika server tidak mengembalikan JSON yang valid
                QMessageBox.critical(self, "Server Error", f"Invalid response from server: {response.text}")
            except Exception as e_generic:
                QMessageBox.critical(self, "Error", f"An unexpected error occurred: {e_generic}")

# ... (sisa metode ChatWindow) ...    

    # Tambahkan metode ini dari it.py ke kelas ChatWindow di client.py
    def attach_file(self):
        if not self.current_conversation:
            print("Silakan pilih percakapan terlebih dahulu.") # Pesan opsional untuk pengguna
            return
            
        options = QFileDialog.Options()
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Pilih File untuk Dikirim", "", 
            "Semua File (*);;Gambar (*.png *.jpg *.jpeg *.gif);;Video (*.mp4 *.mov);;Dokumen (*.pdf *.doc *.docx)",
            options=options
        )
        
        if file_path:
            self.send_file(file_path) #

    def send_file(self, file_path):
        url = f"{BASE_URL}/upload_file" #
        try:
            # Penting: Kirim nama file asli ke server agar bisa digunakan di sisi penerima
            # dan disimpan dengan benar di server.
            with open(file_path, 'rb') as f:
                files = {'file': (os.path.basename(file_path), f, 'application/octet-stream')} # Menyertakan nama file dan tipe MIME opsional
                data = {
                    'conversation_id': str(self.current_conversation),
                    'sender_id': str(self.user['id'])
                }
                
                response = requests.post(url, files=files, data=data) #
                print(f"DEBUG: ChatWindow - Mengirim file ke {url} dengan data: {data}") # DEBUG
                print(f"DEBUG: ChatWindow - Status response: {response.status_code}") # DEBUG
                if response.status_code == 200:
                    print("File berhasil dikirim")
                    # Server akan mengirim event socket, yang akan menambahkan pesan ke UI.
                else:
                    print(f"Gagal mengirim file: {response.status_code} - {response.text}")
        except Exception as e:
            print(f"Terjadi kesalahan saat mengirim file: {e}")    
            
    def mark_conversation_unread(self, conversation_id, new_message_text=None):
        print(f"DEBUG: Menandai belum dibaca untuk conv ID: {conversation_id}") # DEBUG
        self.unread_map[conversation_id] = True 
        for i in range(self.conversation_list.count()):
            item = self.conversation_list.item(i)
            if item.data(Qt.UserRole) == conversation_id:
                widget = self.conversation_list.itemWidget(item)
                if widget and hasattr(widget, 'preview_label'):
                    display_text = "🔵 New message"
                    if new_message_text:
                        # Buat cuplikan, misalnya maksimal 30 karakter, ganti newline dengan spasi
                        snippet = (new_message_text[:30] + '...') if len(new_message_text) > 30 else new_message_text
                        cleaned_snippet = snippet.replace(os.linesep, ' ').replace('\n', ' ')
                        display_text = f"🔵 {cleaned_snippet}"
                        print("\n\n", display_text, "\n\n")

                    widget.preview_label.setText(display_text)
                    widget.preview_label.setStyleSheet("""
                        QLabel {
                            color: #4A90E2; font-size: 13px; font-weight: bold;
                            qproperty-wordWrap: false;
                            max-width: 200px;
                        }
                    """)
                    print(f"DEBUG: Teks preview_label di mark_unread: {widget.preview_label.text()}") # DEBUG
                break # Keluar dari loop setelah item ditemukan dan diperbarui
                
    def load_conversations(self):
        print(f"DEBUG: Memuat percakapan untuk user {self.user['id']}")
        
        try: 
            response = requests.get(f"{BASE_URL}/get_conversations/{self.user['id']}")
            print(f"DEBUG: ChatWindow - Status load_conversations: {response.status_code}") # DEBUG
            QTimer.singleShot(100, self.scroll_to_bottom)
            if response.status_code == 200:
                try:
                    conversations = response.json()
                    print(f"DEBUG: ChatWindow - Percakapan diterima (raw): {conversations}") # DEBUG
                except requests.exceptions.JSONDecodeError:
                    print(f"DEBUG: ChatWindow - Gagal parse JSON dari /get_conversations: {response.text}") # DEBUG
                    conversations = []
                
                self.conversation_list.clear() # Hapus item lama
                
                if not conversations:
                    print("DEBUG: ChatWindow - Tidak ada percakapan.") # DEBUG
                    return
                
                conversations.sort(key=lambda x: str(x.get('last_updated', '0')), reverse=True) # Gunakan last_updated dari server


                for conv_data in conversations:
                    print(f"DEBUG: ChatWindow - Memproses conv ID: {conv_data.get('id')}") # DEBUG
                    item = QListWidgetItem()
                    item.setData(Qt.UserRole, conv_data['id'])
                    
                    # Ambil 'last_message_preview' dari conv_data (HARUS DISEDIAKAN SERVER)
                    last_message_preview = conv_data.get('last_message_preview', "No messages yet.")
                    if not last_message_preview:
                         last_message_preview = "No messages yet."
                    print(f"DEBUG: ChatWindow - Last message untuk conv {conv_data.get('id')}: {last_message_preview}") #DEBUG
                                    
                    conv_widget = ConversationItem(conv_data, self.user['role'], last_message_preview)
                    item.setSizeHint(conv_widget.sizeHint())
                    
                    self.conversation_list.addItem(item)
                    self.conversation_list.setItemWidget(item, conv_widget)
                    
                    if self.unread_map.get(conv_data['id'], False) and conv_data['id'] != self.current_conversation:
                        self.mark_conversation_unread(conv_data['id'], last_message_preview)

                    if conv_data['id'] == self.current_conversation:
                        self.conversation_list.setCurrentItem(item)
                    
                    print(f"DEBUG: ChatWindow - Unread message: \n {self.unread_map}") # DEBUG
                # print(f"DEBUG: ChatWindow - percakapan dimuat. List:\n {conversations}") # DEBUG
            else:
                print(f"DEBUG: ChatWindow - Gagal memuat percakapan: {response.status_code} - {response.text}") # DEBUG
        except requests.exceptions.RequestException as e:
            print(f"DEBUG: Error koneksi saat memuat percakapan: {e}")
        except Exception as e:
            print(f"DEBUG: Error tak terduga di load_conversations: {e}")

    
    def select_conversation(self, item ):
        if not item:
            print("DEBUG: ChatWindow - select_conversation dipanggil dengan item None") # DEBUG
            return
        self.update_chat_input_active_state(True)
        self.back_button.setVisible(True)
        conversation_id = item.data(Qt.UserRole)
        print(f"DEBUG: ChatWindow - Memilih percakapan ID: {conversation_id}") # DEBUG
        self.current_conversation = conversation_id
        QTimer.singleShot(100, self.scroll_to_bottom)
        conv_widget = self.conversation_list.itemWidget(item)
        if not conv_widget:
            print(f"DEBUG: ChatWindow - Tidak ada widget untuk item percakapan ID: {conversation_id}") # DEBUG
            return
        conv_data = conv_widget.conversation_data
        
        if self.user['role'] == 'employee': #
            name = conv_data.get('tech_name', 'Technician') #
        else:
            name = conv_data.get('employee_name', 'Employee') #
        
        self.chat_name.setText(name) #
        self.chat_status.setText("🟢 Active now" if conv_data.get('status') != 'closed' else "⚫ Closed") #
        self.chat_avatar.setText(name[0].upper() if name else "?") #
        
        self.load_messages(conversation_id, scroll_to_bottom=True) # Muat pesan
        self.unread_map[conversation_id] = False
        # item.setSelected(False) # Hapus highlight biru bawaan QListWidget
        # Reset style dasar ConversationItem
        default_item_style = ConversationItem(conv_data, self.user['role'], "").styleSheet() # Dapatkan style dasar
        conv_widget.setStyleSheet(default_item_style)
        
    

        
        # Reset tampilan preview_label ke pesan terakhir yang sebenarnya
        if hasattr(conv_widget, 'preview_label'):
            # Ambil preview pesan terakhir dari data percakapan yang tersimpan di widget
            actual_last_preview = conv_widget.conversation_data.get('last_message_preview', "No messages yet.")

            MAX_PREVIEW_LENGTH = 35 # Sesuaikan
            processed_preview = actual_last_preview
            if not isinstance(actual_last_preview, str) or not actual_last_preview.strip():
                processed_preview = "No messages yet."
            elif len(actual_last_preview) > MAX_PREVIEW_LENGTH:
                processed_preview = actual_last_preview[:MAX_PREVIEW_LENGTH - 3] + "..."

            conv_widget.preview_label.setText(processed_preview)
            conv_widget.preview_label.setStyleSheet("""
                QLabel {
                    color: #7F8C8D; /* Warna normal */
                    font-size: 13px;
                    /* Hapus properti CSS penyebab warning jika masih ada */
                }
            """)
            
    def go_back_to_selection_view(self):
        # 1. Bersihkan area pesan
        while self.messages_layout.count() > 1: # Sisakan item 'stretch' di akhir
            item = self.messages_layout.takeAt(0) # Ambil dari atas
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        # 2. Reset header chat
        self.chat_name.setText("Select a conversation")
        self.chat_status.setText("Choose a chat to start messaging")
        self.chat_avatar.setText("") # Kosongkan avatar
        self.back_button.setVisible(False) # Sembunyikan tombol back lagi

        # 3. Set current_conversation menjadi None
        self.current_conversation = None

        # 4. Nonaktifkan area input pesan
        self.update_chat_input_active_state(False)

        # 5. (Opsional) Hapus sorotan dari QListWidget jika ada
        if self.conversation_list.currentItem():
            self.conversation_list.currentItem().setSelected(False)
            self.conversation_list.setCurrentItem(None) # Ini penting untuk menghapus fokus    
            
    def load_messages(self, conversation_id, scroll_to_bottom=False):
        
        print(f"DEBUG: ChatWindow - Memuat pesan untuk conv_id: {conversation_id}") # DEBUG
        try:
            response = requests.get(f"{BASE_URL}/get_messages/{conversation_id}", timeout=5)
            print(f"DEBUG: ChatWindow - Status load_messages: {response.status_code}") # DEBUG
            if response.status_code == 200:
                try:
                    messages_from_server = response.json()
                except requests.exceptions.JSONDecodeError:
                    print(f"DEBUG: ChatWindow - Gagal parse JSON dari /get_messages: {response.text}") # DEBUG
                    messages_from_server = []
                    
                # Simpan pesan ke cache
                self.message_cache[conversation_id] = messages_from_server # Simpan pesan ke cache
                print(f"DEBUG: ChatWindow - Pesan untuk conv {conversation_id} disimpan ke cache. Jumlah: {len(messages_from_server)}")

                while self.messages_layout.count() > 1: # Sisakan stretch item
                    item_to_remove = self.messages_layout.takeAt(0)
                    widget = item_to_remove.widget()
                    if widget:
                        widget.deleteLater()
                
                # Tampilkan pesan dari cache
                if conversation_id in self.message_cache:
                    for msg_data in self.message_cache[conversation_id]:
                        self.add_message_to_ui( # Panggil add_message_to_ui yang sudah ada
                            msg_data['message'], 
                            msg_data['sender_id'] == self.user['id'],
                            msg_data['sender_name'],
                            msg_data['sent_at'],
                            msg_data['id'], # msg_id penting untuk message_exists
                            msg_data['file_path'] # DIPERBARUI: Teruskan file_path
                        )
                        
                
                return self.message_cache.get(conversation_id, []) 
            else:
                print(f"DEBUG: ChatWindow - Gagal memuat pesan: {response.status_code} - {response.text}") # DEBUG
        except requests.exceptions.RequestException as e:
            print(f"DEBUG: ChatWindow - Error koneksi saat memuat pesan: {e}") # DEBUG
        except Exception as e:
            print(f"DEBUG: ChatWindow - Error tak terduga di load_messages: {e}") # DEBUG
        
            
        # Jika gagal, pastikan cache untuk conversation_id ini kosong atau sesuai keadaan
        self.message_cache[conversation_id] = []
        return [] # Kembalikan list kosong jika gagal
    
    def scroll_to_bottom(self): #
        scrollbar = self.scroll_area.verticalScrollBar() #
        scrollbar.setValue(scrollbar.maximum()) #
    
    def refresh_messages(self): #
        if self.current_conversation: #
            print(f"DEBUG: ChatWindow - Refresh messages untuk conv: {self.current_conversation}") # DEBUG
            self.load_messages(self.current_conversation) #
            
    def handle_received_message(self, data):
        conv_id = data['conversation_id']
        message_content = data['message'] # Ini dictionary: {id, message, sender_id, sender_name, sent_at}
        print(f"DEBUG: IT/handle_received_message - 📨 Pesan baru untuk conv_id {conv_id}: {message_content.get('message')}")
        # --- MAINKAN SUARA JIKA PESAN DARI ORANG LAIN ---
        if self.message_sound and message_content.get('sender_id') != self.user['id']:
            self.message_sound.play()
            # print("Playing notification sound.") # Debug
        # --- AKHIR MAINKAN SUARA ---
        # 1. Tambahkan pesan ke cache
        if conv_id not in self.message_cache:
            self.message_cache[conv_id] = []

        # Cek apakah pesan dengan ID ini sudah ada di cache untuk conv_id ini
        message_already_in_cache = False
        for msg_in_cache in self.message_cache[conv_id]:
            if msg_in_cache.get('id') == message_content.get('id'):
                message_already_in_cache = True
                break
            
        if not message_already_in_cache:
            self.message_cache[conv_id].append(message_content)
            print(f"DEBUG: IT/handle_received_message - Pesan ID {message_content.get('id')} ditambahkan ke cache untuk conv {conv_id}.")
        else:
            print(f"DEBUG: IT/handle_received_message - Pesan ID {message_content.get('id')} sudah ada di cache untuk conv {conv_id}.")

        # 2. Cari item percakapan di list sidebar
        item_widget = None
        item_found_in_sidebar = False
        list_item_object = None # Untuk menyimpan QListWidgetItem

        for i in range(self.conversation_list.count()):
            current_list_item = self.conversation_list.item(i)
            if current_list_item.data(Qt.UserRole) == conv_id:
                item_widget = self.conversation_list.itemWidget(current_list_item)
                item_found_in_sidebar = True
                list_item_object = current_list_item # Simpan QListWidgetItem
                
                # Update data internal di ConversationItem (jika perlu, untuk konsistensi saat select)
                if isinstance(item_widget, ConversationItem):
                    item_widget.conversation_data['last_message_preview'] = message_content.get('message')
                    item_widget.conversation_data['last_updated'] = message_content.get('sent_at') # Gunakan sent_at sebagai last_updated
                    print(f"DEBUG: IT/handle_received_message - Data lokal ConversationItem {conv_id} diperbarui.")
                break
        
        # 3. Proses berdasarkan apakah percakapan aktif atau tidak
        if conv_id == self.current_conversation:
            print(f"DEBUG: IT/handle_received_message - Pesan untuk percakapan aktif {conv_id}.")
            if not self.message_exists(message_content.get('id')):
                self.add_message_to_ui(
                    message_content.get('message'), 
                    message_content.get('sender_id') == self.user['id'], 
                    message_content.get('sender_name'), 
                    message_content.get('sent_at'),
                    message_content.get('id'),
                    message_content.get('file_path') # Teruskan file_path jika ada
                )
            # Meskipun aktif, kita tetap ingin itemnya pindah ke atas jika ada pesan baru
            if item_found_in_sidebar:
                self.move_conversation_to_top(conv_id)
        else: # Pesan untuk percakapan yang tidak aktif
            if item_found_in_sidebar:
                print(f"DEBUG: IT/handle_received_message - Pesan untuk percakapan TIDAK aktif {conv_id}. Menandai belum dibaca dan pindah ke atas.")
                self.mark_conversation_unread(conv_id, message_content.get("message")) # Ini akan set preview_label ke "🔵 New message"
                self.move_conversation_to_top(conv_id)
            else:
                # Percakapan ini belum ada di list, mungkin percakapan baru yang dibuat oleh employee lain
                print(f"DEBUG: IT/handle_received_message - Pesan untuk percakapan BARU {conv_id} (tidak ada di list). Memuat ulang semua.")
                self.load_conversations() # Muat ulang semua untuk menampilkan percakapan baru ini
                self.unread_map[conv_id] = True # Tandai sebagai belum dibaca di map


    def move_conversation_to_top(self, conversation_id):
        print(f"DEBUG: IT/move_conversation_to_top (Revisi Unread Style) - Mencoba memindahkan percakapan ID: {conversation_id}")
        
        source_index = -1
        original_item_widget_ref = None 

        for i in range(self.conversation_list.count()):
            item = self.conversation_list.item(i) 
            if item.data(Qt.UserRole) == conversation_id:
                source_index = i
                original_item_widget_ref = self.conversation_list.itemWidget(item)
                break
        
        if source_index == -1:
            print(f"DEBUG: IT/move_conversation_to_top (Revisi Unread Style) - Item {conversation_id} tidak ditemukan.")
            return
        
        # Jika item sudah di atas, tidak perlu dipindahkan.
        # Styling unread sudah ditangani oleh mark_conversation_unread() yang dipanggil sebelumnya
        # pada original_item_widget_ref.
        if source_index == 0:
            print(f"DEBUG: IT/move_conversation_to_top (Revisi Unread Style) - Item {conversation_id} sudah di posisi teratas.")
            # Kita bisa pastikan preview text di-update jika datanya berubah, meskipun sudah di atas
            if original_item_widget_ref and hasattr(original_item_widget_ref, 'conversation_data') and hasattr(original_item_widget_ref, 'preview_label'):
                is_unread = self.unread_map.get(conversation_id, False)
                current_preview_from_data = original_item_widget_ref.conversation_data.get('last_message_preview', "Tidak ada pesan.")
                snippet = (current_preview_from_data[:30] + '...') if len(current_preview_from_data) > 30 else current_preview_from_data
                snippet = snippet.replace(os.linesep, ' ').replace('\n', ' ')

                if is_unread:
                    original_item_widget_ref.preview_label.setText(f"🔵 {snippet}")
                    original_item_widget_ref.preview_label.setStyleSheet("""
                        QLabel {
                            color: #4A90E2; font-size: 13px; font-weight: bold;
                            white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
                        }
                    """)
                else: # Jika karena alasan tertentu sudah terbaca tapi di paling atas
                    original_item_widget_ref.preview_label.setText(snippet)
                    original_item_widget_ref.preview_label.setStyleSheet("""
                        QLabel {
                            color: #7F8C8D; font-size: 13px; font-weight: normal;
                            white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
                        }
                    """)
            return

        if not original_item_widget_ref or not hasattr(original_item_widget_ref, 'conversation_data'):
            print(f"DEBUG: IT/move_conversation_to_top (Revisi Unread Style) - Widget atau conversation_data untuk item {conversation_id} tidak ditemukan. Operasi dibatalkan.")
            return

        conv_data_to_recreate = original_item_widget_ref.conversation_data
        last_preview_text_from_data = conv_data_to_recreate.get('last_message_preview', "Tidak ada pesan.")
        if not last_preview_text_from_data: 
            last_preview_text_from_data = "Tidak ada pesan."
        
        # Buat QListWidgetItem BARU.
        new_qlist_item = QListWidgetItem()
        new_qlist_item.setData(Qt.UserRole, conversation_id)
        
        # Buat instance ConversationItem BARU.
        # Berikan teks preview dasar (tanpa "🔵") saat pembuatan.
        new_conv_widget = ConversationItem(
            conv_data_to_recreate,
            self.user['role'],
            last_preview_text_from_data 
        )
        new_qlist_item.setSizeHint(new_conv_widget.sizeHint())

        # Hapus QListWidgetItem yang lama.
        item_lama_yang_diambil = self.conversation_list.takeItem(source_index)
        if item_lama_yang_diambil:
            if original_item_widget_ref:
                original_item_widget_ref.deleteLater() 
            del item_lama_yang_diambil
            print(f"DEBUG: IT/move_conversation_to_top (Revisi Unread Style) - Item lama dan widgetnya untuk {conversation_id} telah dijadwalkan untuk dihapus.")
        else:
            print(f"DEBUG: IT/move_conversation_to_top (Revisi Unread Style) - Gagal takeItem untuk item lama {conversation_id}.")
            return

        # Masukkan QListWidgetItem BARU ke paling atas.
        self.conversation_list.insertItem(0, new_qlist_item)
        
        # Pasang ConversationItem widget BARU ke QListWidgetItem BARU.
        self.conversation_list.setItemWidget(new_qlist_item, new_conv_widget)
        
        # Setelah widget BARU dipasang, cek self.unread_map dan terapkan styling unread jika perlu.
        # Ini akan menangani kasus di mana item dipindahkan dari bawah ke atas dan harus tetap unread.
        if self.unread_map.get(conversation_id, False):
            if hasattr(new_conv_widget, 'preview_label'):
                # Ambil teks preview asli dari data (tanpa "🔵") untuk membuat snippet
                raw_preview_for_snippet = last_preview_text_from_data 
                snippet = (raw_preview_for_snippet[:30] + '...') if len(raw_preview_for_snippet) > 30 else raw_preview_for_snippet
                snippet = snippet.replace(os.linesep, ' ').replace('\n', ' ')
                
                unread_display_text = f"🔵 {snippet}"
                
                new_conv_widget.preview_label.setText(unread_display_text)
                new_conv_widget.preview_label.setStyleSheet("""
                    QLabel {
                        color: #4A90E2; font-size: 13px; font-weight: bold;
                        white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
                    }
                """)
                print(f"DEBUG: IT/move_conversation_to_top (Revisi Unread Style) - Gaya unread diterapkan pada widget BARU untuk {conversation_id}")
        
        print(f"DEBUG: IT/move_conversation_to_top (Revisi Unread Style) - Berhasil memindahkan {conversation_id}.")
        # self.conversation_list.setCurrentItem(new_qlist_item) # Opsional
            
    def message_exists(self, msg_id):
        if msg_id is None: return False # Jika msg_id None, anggap belum ada
        for i in range(self.messages_layout.count()):
            container_widget = self.messages_layout.itemAt(i).widget()
            if container_widget:
                # BubbleMessage adalah child dari container_widget
                # Asumsi bubble adalah widget pertama (atau satu-satunya non-stretch) di layout container
                if container_widget.layout() and container_widget.layout().count() > 0:
                    bubble_item = container_widget.layout().itemAt(0 if container_widget.layout().itemAt(0).widget() else 1)
                    if bubble_item:
                        bubble_widget = bubble_item.widget()
                        if isinstance(bubble_widget, BubbleMessage) and hasattr(bubble_widget, 'msg_id') and bubble_widget.msg_id == msg_id:
                            print(f"DEBUG: Pesan dengan ID {msg_id} sudah ada di UI.") # DEBUG
                            return True
        return False
    

    
    # def add_message_to_ui(self, message, is_me, sender_name, sent_at, scroll_to_bottom=True):
    #     bubble = BubbleMessage(message, is_me, sender_name, sent_at)
        
    #     # Create container for proper alignment
    #     container = QWidget()
    #     container_layout = QHBoxLayout()
    #     container_layout.setContentsMargins(0, 0, 0, 0)
        
    #     if is_me:
    #         container_layout.addStretch()
    #         container_layout.addWidget(bubble)
    #     else:
    #         container_layout.addWidget(bubble)
    #         container_layout.addStretch()
        
    #     container.setLayout(container_layout)
    #     self.messages_layout.addWidget(container)
    #     if scroll_to_bottom:
    #         QTimer.singleShot(100, self.scroll_to_bottom)
    
    # Modifikasi add_message_to_ui untuk menerima seluruh dictionary pesan
    def add_message_to_ui(self, message_text, is_me, sender_name, sent_at, msg_id=None, file_path=None, scroll_to_bottom=True ):
        bubble = BubbleMessage(message_text, is_me, sender_name, sent_at, file_path=file_path) # Tambahkan file_path jika ada
        bubble.msg_id = msg_id # Simpan ID pesan di bubble
        
        container = QWidget()
        container_layout = QHBoxLayout(container)
        container_layout.setContentsMargins(0,0,0,0)
        
        if is_me:
            container_layout.addStretch()
            container_layout.addWidget(bubble)
        else:
            container_layout.addWidget(bubble)
            container_layout.addStretch()
        
        # Sisipkan sebelum stretch item terakhir di self.messages_layout
        self.messages_layout.insertWidget(self.messages_layout.count() - 1, container)
        if scroll_to_bottom:
            QTimer.singleShot(100, self.scroll_to_bottom)
            

    
    def send_message(self):
        if not self.current_conversation or not self.message_input.toPlainText().strip():
            return
        
        message_text = self.message_input.toPlainText().strip()
        print(f"DEBUG: Mengirim pesan: '{message_text}' ke conv ID: {self.current_conversation}") # DEBUG
        data = {
            'conversation_id': self.current_conversation,
            'sender_id': self.user['id'],
            'message': message_text
        }
        
        try:
            response = requests.post(f"{BASE_URL}/send_message", json=data)
            print(f"DEBUG: Status send_message: {response.status_code}") # DEBUG
            if response.status_code == 200:
                self.message_input.clear()
                # Pesan akan muncul via WebSocket, jadi tidak perlu refresh manual di sini
                # Mungkin panggil load_conversations untuk update preview dan urutan
                # QTimer.singleShot(200, self.load_conversations) # Beri jeda agar server sempat update DB
            else:
                print(f"DEBUG: Gagal mengirim pesan: {response.text}") # DEBUG
                # Tampilkan error ke pengguna jika perlu
        except requests.exceptions.RequestException as e:
            print(f"DEBUG: Error koneksi saat mengirim pesan: {e}") # DEBUG
    
    def create_new_conversation(self): #
        print("DEBUG: Membuat percakapan baru") # DEBUG
        data = {'employee_id': self.user['id'], 'technician_id': None} #
        try:
            response = requests.post(f"{BASE_URL}/create_conversation", json=data) #
            print(f"DEBUG: Status create_conversation: {response.status_code}") # DEBUG
            if response.status_code == 200: #
                self.load_conversations() #
            else:
                print(f"DEBUG: Gagal membuat percakapan: {response.text}") # DEBUG
        except requests.exceptions.RequestException as e:
            print(f"DEBUG: Error koneksi saat membuat percakapan: {e}") # DEBUG
    
    def closeEvent(self, event):
        print("DEBUG: ChatWindow - Menutup ChatWindow, menghentikan WebSocket thread.")
        if hasattr(self, 'ws_thread') and self.ws_thread.is_alive():
            self.ws_thread.stop()  # Panggil metode stop dari WebSocketThread yang baru
            self.ws_thread.join(timeout=2) # Tunggu thread selesai (opsional, dengan timeout)
        super().closeEvent(event)

# ... (impor lain yang sudah ada: QDialog, QVBoxLayout, QLabel, QComboBox, QPushButton, QMessageBox, requests) ...

class CreateConversationDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create New Custom Conversation")
        self.setFixedSize(450, 250)

        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        # Employee Selection
        self.employee_label = QLabel("Select Employee (Client):")
        self.employee_combo = QComboBox()
        self.employee_combo.setPlaceholderText("Loading employees...")
        layout.addWidget(self.employee_label)
        layout.addWidget(self.employee_combo)

        # Technician Selection
        self.technician_label = QLabel("Select Technician:")
        self.technician_combo = QComboBox()
        self.technician_combo.setPlaceholderText("Loading technicians...")
        layout.addWidget(self.technician_label)
        layout.addWidget(self.technician_combo)

        # Buttons
        button_layout = QHBoxLayout()
        self.create_button = QPushButton("Create Conversation")
        self.create_button.setStyleSheet("""
            QPushButton {
                background-color: #27AE60; color: white; padding: 10px;
                border-radius: 5px; font-weight: bold;
            }
            QPushButton:hover { background-color: #229954; }
        """)
        self.cancel_button = QPushButton("Cancel")
        # ... (style cancel button seperti di AddUserDialog) ...
        self.cancel_button.setStyleSheet("""
             QPushButton {
                background-color: #E0E0E0; color: #333333; padding: 10px;
                border-radius: 5px;
            }
            QPushButton:hover { background-color: #D0D0D0; }
        """)


        button_layout.addStretch()
        button_layout.addWidget(self.create_button)
        button_layout.addWidget(self.cancel_button)
        layout.addLayout(button_layout)

        self.create_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)

        self._load_users()

    def _load_users(self):
        # Load Employees
        try:
            response_emp = requests.get(f"{BASE_URL}/get_users_by_role/employee")
            if response_emp.status_code == 200 and response_emp.json().get('success'):
                employees = response_emp.json().get('users', [])
                self.employee_combo.clear()
                if not employees:
                    self.employee_combo.addItem("No employees found", -1)
                else:
                    self.employee_combo.addItem("-- Select Employee --", -1) # Placeholder
                    for emp in employees:
                        self.employee_combo.addItem(emp['full_name'], emp['id'])
            else:
                self.employee_combo.addItem("Error loading employees", -1)
                print(f"Error fetching employees: {response_emp.text}")
        except requests.exceptions.RequestException as e:
            self.employee_combo.addItem("Connection error", -1)
            print(f"Connection error fetching employees: {e}")

        # Load Technicians
        try:
            response_tech = requests.get(f"{BASE_URL}/get_users_by_role/technician")
            if response_tech.status_code == 200 and response_tech.json().get('success'):
                technicians = response_tech.json().get('users', [])
                self.technician_combo.clear()
                if not technicians:
                    self.technician_combo.addItem("No technicians found", -1)
                else:
                    self.technician_combo.addItem("-- Select Technician --", -1) # Placeholder
                    for tech in technicians:
                        self.technician_combo.addItem(tech['full_name'], tech['id'])
            else:
                self.technician_combo.addItem("Error loading technicians", -1)
                print(f"Error fetching technicians: {response_tech.text}")
        except requests.exceptions.RequestException as e:
            self.technician_combo.addItem("Connection error", -1)
            print(f"Connection error fetching technicians: {e}")


    def get_selected_ids(self):
        employee_id = self.employee_combo.currentData()
        technician_id = self.technician_combo.currentData()
        
        # Pastikan ID yang valid terpilih (bukan placeholder -1)
        if employee_id == -1 or technician_id == -1:
            return None 
            
        return {
            "employee_id": employee_id,
            "technician_id": technician_id
        }

# ... (sisa kelas WebSocketThread, BubbleMessage, ConversationItem, dll.) ...
        
class AddUserDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add New User")
        self.setFixedSize(400, 320) # Sedikit lebih tinggi untuk spasi

        layout = QVBoxLayout(self)
        layout.setSpacing(12) # Kurangi spacing sedikit
        layout.setContentsMargins(20, 20, 20, 20)

        # Username
        self.username_label = QLabel("Username:")
        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Enter username")
        layout.addWidget(self.username_label)
        layout.addWidget(self.username_input)

        # Full Name
        self.fullname_label = QLabel("Full Name:")
        self.fullname_input = QLineEdit()
        self.fullname_input.setPlaceholderText("Enter full name")
        layout.addWidget(self.fullname_label)
        layout.addWidget(self.fullname_input)

        # Role
        self.role_label = QLabel("Role:")
        self.role_combo = QComboBox()
        self.role_combo.addItems(["employee", "technician"])
        layout.addWidget(self.role_label)
        layout.addWidget(self.role_combo)

        # Password
        self.password_label = QLabel() # Label akan di-set oleh update_password_prompt
        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Enter password if required/desired")
        self.password_input.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.password_label)
        layout.addWidget(self.password_input)
        
        # Spacer agar tombol tidak terlalu mepet
        layout.addStretch(1)


        # Buttons
        button_layout = QHBoxLayout()
        self.ok_button = QPushButton("Add User")
        self.ok_button.setStyleSheet("""
            QPushButton {
                background-color: #4A90E2; color: white; padding: 10px;
                border-radius: 5px; font-weight: bold;
            }
            QPushButton:hover { background-color: #357ABD; }
        """)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setStyleSheet("""
            QPushButton {
                background-color: #E0E0E0; color: #333333; padding: 10px;
                border-radius: 5px;
            }
            QPushButton:hover { background-color: #D0D0D0; }
        """)

        button_layout.addStretch()
        button_layout.addWidget(self.ok_button)
        button_layout.addWidget(self.cancel_button)
        layout.addLayout(button_layout)

        self.ok_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
        
        self.role_combo.currentIndexChanged.connect(self.update_password_prompt) # Hubungkan sinyal
        self.update_password_prompt() # Panggil sekali saat inisialisasi

    def update_password_prompt(self):
        current_role = self.role_combo.currentText()
        if current_role == 'employee':
            self.password_label.setText("Password (Optional for Employee):")
        else: # technician
            self.password_label.setText("Password (Required for Technician):")

    def get_data(self):
        return {
            "username": self.username_input.text().strip(),
            "full_name": self.fullname_input.text().strip(),
            "password": self.password_input.text(), # Kirim apa adanya, server yang validasi
            "role": self.role_combo.currentText()
        }

class LoginWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setup_ui()
    
    def setup_ui(self):
        self.setWindowTitle("Login - IT Support Chat")
        self.setFixedSize(480, 740)
        
        # Main container
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Top section with gradient
        top_widget = QWidget()
        top_widget.setFixedHeight(200)
        top_widget.setStyleSheet("""
            QWidget {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #4A90E2, stop:0.5 #357ABD, stop:1 #6C7CE7);
            }
        """)
        
        top_layout = QVBoxLayout()
        top_layout.setContentsMargins(40, 40, 40, 40)
        top_layout.setSpacing(20)
        
        # Logo/Icon
        logo_label = QLabel("💬")
        logo_label.setStyleSheet("font-size: 48px;")
        logo_label.setAlignment(Qt.AlignCenter)
        top_layout.addWidget(logo_label)
        
        # Title
        title = QLabel("IT Support Chat")
        title.setStyleSheet("""
            QLabel {
                font-size: 28px; 
                font-weight: 700; 
                color: white;
                text-align: center;
            }
        """)
        title.setAlignment(Qt.AlignCenter)
        top_layout.addWidget(title)
        
        subtitle = QLabel("Connect with our support team")
        subtitle.setStyleSheet("""
            QLabel {
                font-size: 16px; 
                color: rgba(255,255,255,0.9);
                text-align: center;
            }
        """)
        subtitle.setAlignment(Qt.AlignCenter)
        top_layout.addWidget(subtitle)
        
        top_widget.setLayout(top_layout)
        main_layout.addWidget(top_widget)
        
        # Bottom section with form
        bottom_widget = QWidget()
        bottom_widget.setStyleSheet("background-color: #FFFFFF;")
        
        form_layout = QVBoxLayout()
        form_layout.setContentsMargins(40, 20, 20, 20)
        form_layout.setSpacing(10)
        
        # Welcome text
        welcome_label = QLabel("Welcome back!")
        welcome_label.setStyleSheet("""
            QLabel {
                font-size: 20px;
                font-weight: 600;
                color: #2C3E50;
                margin-bottom: 1px;
            }
        """)
        form_layout.addWidget(welcome_label)
        
        welcome_sub = QLabel("Please sign in to your account")
        welcome_sub.setStyleSheet("""
            QLabel {
                font-size: 14px;
                color: #7F8C8D;
                margin-bottom: 1px;
            }
        """)
        form_layout.addWidget(welcome_sub)
        
        # Username input
        username_label = QLabel("Email ")
        username_label.setStyleSheet("""
            QLabel {
                font-size: 14px;
                color: #2C3E50;
                font-weight: 500;
                margin-bottom: 5px;
            }
        """)
        form_layout.addWidget(username_label)
        
        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Enter your email")
        self.username_input.setStyleSheet("""
            QLineEdit {
                padding: 16px;
                font-size: 14px;
                border: 2px solid #E8ECEF;
                border-radius: 12px;
                background-color: #F8F9FA;
            }
            QLineEdit:focus {
                border: 2px solid #4A90E2;
                background-color: #FFFFFF;
            }
        """)
        form_layout.addWidget(self.username_input)
        
        # Password input
        password_label = QLabel("Password")
        password_label.setStyleSheet("""
            QLabel {
                font-size: 14px;
                color: #2C3E50;
                font-weight: 500;
                margin-bottom: 5px;
            }
        """)
        form_layout.addWidget(password_label)
        
        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Enter your password")
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.setStyleSheet("""
            QLineEdit {
                padding: 16px;
                font-size: 14px;
                border: 2px solid #E8ECEF;
                border-radius: 12px;
                background-color: #F8F9FA;
            }
            QLineEdit:focus {
                border: 2px solid #4A90E2;
                background-color: #FFFFFF;
            }
        """)
        form_layout.addWidget(self.password_input)
        
        # Login button
        login_btn = QPushButton("Sign In")
        login_btn.clicked.connect(self.handle_login)
        login_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                    stop:0 #4A90E2, stop:1 #357ABD);
                color: white;
                border: none;
                padding: 16px;
                font-size: 16px;
                font-weight: 600;
                border-radius: 12px;
                margin-top: 10px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                    stop:0 #357ABD, stop:1 #2E6DA4);
            }
            QPushButton:pressed {
                background: #2E6DA4;
            }
        """)
        form_layout.addWidget(login_btn)
        
        # Error label
        self.error_label = QLabel()
        self.error_label.setStyleSheet("""
            QLabel {
                color: #E74C3C; 
                background-color: #FADBD8;
                padding: 12px;
                border-radius: 8px;
                font-size: 14px;
                margin-top: 10px;
            }
        """)
        self.error_label.hide()
        form_layout.addWidget(self.error_label)
        
        # Add stretch to push content up
        form_layout.addStretch()
        
        # Footer
        footer_label = QLabel("Copyright © 2025 @iqbal.rian & @Dvim261 . All rights reserved..")
        footer_label.setStyleSheet("""
            QLabel {
                color: #95A5A6;
                font-size: 12px;
                text-align: center;
                margin-top: 20px;
            }
        """)
        footer_label.setAlignment(Qt.AlignCenter)
        form_layout.addWidget(footer_label)
        
        bottom_widget.setLayout(form_layout)
        main_layout.addWidget(bottom_widget)
        
        self.setLayout(main_layout)
        
        # Set overall window style
        self.setStyleSheet("""
            QWidget {
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            }
        """)
    
    def handle_login(self):
        username = self.username_input.text()
        password = self.password_input.text()
        
        if not username or not password:
            self.show_error("Username and password are required")
            return
        
        data = {
            'username': username,
            'password': password
        }
        
        try:
            response = requests.post(f"{BASE_URL}/login_it", json=data)
            if response.status_code == 200:
                result = response.json()
                if result['success']:
                    self.chat_window = ChatWindow(result['user'])
                    self.chat_window.show()
                    self.close()
                else:
                    self.show_error("Invalid username or password. Please try again.")
            else:
                self.show_error("Server error occurred. Please try again later.")
        except requests.exceptions.ConnectionError:
            self.show_error("Cannot connect to server. Please check your connection.")
    
    def show_error(self, message):
        self.error_label.setText(f"⚠️ {message}")
        self.error_label.show()
        
        # Hide error after 5 seconds
        QTimer.singleShot(5000, self.error_label.hide)
# ... (Impor lain yang sudah ada) ...



# ... (sisa kelas) ...




if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    # Set application icon if available
    # app.setWindowIcon(QIcon("icon.png"))
    
    login_window = LoginWindow()
    login_window.show()
    
    sys.exit(app.exec_())