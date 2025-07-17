import threading
import requests
import socketio
import socket
import json
import time
import sys
import os

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QListWidget, QTextEdit,
    QScrollArea, QFrame, QSizePolicy, QListWidgetItem, QGraphicsDropShadowEffect,
    QFileDialog, QMessageBox, QComboBox, QCheckBox
)
from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply # Untuk memuat gambar secara asinkron
from PyQt5.QtCore import QSettings, pyqtSignal, Qt, QTimer, QUrl, QMimeData, QDir, QStandardPaths, QThread, QObject
from PyQt5.QtGui import QColor,QKeyEvent, QFont, QPainter, QBrush, QPalette, QPixmap, QIcon, QDesktopServices, QImage


# Suppress font warnings
os.environ['QT_LOGGING_RULES'] = 'qt.qpa.fonts=false'

# IP = "192.168.47.72" 
# IP = "192.168.1.7" 
SERVER_IP = None
SERVER_PORT = None
BASE_URL = None
DISCOVERY_PORT = 60000 # Port untuk discovery service

# BASE_URL = "http://localhost:5000"
# BASE_URL = f"http://{IP}:{PORT}"   # Ganti <IP_KANTOR> dengan IP server

def find_server():
    """
    Mengirim broadcast UDP untuk menemukan server.
    Mengembalikan tuple (ip, port) jika ditemukan, atau (None, None) jika gagal.
    """
    global SERVER_IP, SERVER_PORT, BASE_URL
    print("Mencari server helpdesk di jaringan...")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.settimeout(3) # Tunggu balasan selama 3 detik
        try:
            s.sendto(b'DISCOVER_ITHELPDESK_SERVER', ('<broadcast>', DISCOVERY_PORT))
            data, addr = s.recvfrom(1024)
            response_str = data.decode('utf-8')
            if response_str.startswith('ITHELPDESK_SERVER_AT_PORT_'):
                port = response_str.split('_')[-1]
                SERVER_IP = addr[0]
                SERVER_PORT = int(port)
                BASE_URL = f"http://{SERVER_IP}:{SERVER_PORT}"
                print(f"✅ Server ditemukan di: {BASE_URL}")
                return SERVER_IP, SERVER_PORT
        except socket.timeout:
            print("❌ Tidak ada server yang merespons. Pencarian gagal.")
            return None, None
        except Exception as e:
            print(f"Error saat mencari server: {e}")
            return None, None
    return None, None

class ServerFinder(QObject):
    finished = pyqtSignal(str, int)
    not_found = pyqtSignal()
    search_stopped = pyqtSignal() # Sinyal baru untuk menandakan pencarian selesai (baik berhasil atau gagal)

    def __init__(self):
        super().__init__()
        self._running = True

    def find_continuously(self):
        """Mencari server terus menerus sampai ditemukan atau dihentikan."""
        while self._running:
            ip, port = find_server()
            if ip and port:
                self.finished.emit(ip, port)
                self._running = False
            else:
                self.not_found.emit()
                if self._running:
                    QThread.sleep(5)
        self.search_stopped.emit()

    def stop(self):
        self._running = False



class FilePasteTextEdit(QTextEdit):
    def __init__(self, parent_chat_window, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.parent_chat_window = parent_chat_window
        self.setAcceptRichText(True)
        
    def keyPressEvent(self, event: QKeyEvent) -> None:
        # Qt.Key_Return adalah tombol Enter utama
        # Qt.Key_Enter adalah tombol Enter di numpad
        # event.modifiers() mengembalikan kombinasi modifier (Shift, Ctrl, Alt, dll.)
        
        # Cek apakah tombol Enter ditekan DAN modifier Alt aktif
        is_enter_key = (event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter)
        alt_is_pressed = bool(event.modifiers() & Qt.AltModifier) # Cara aman mengecek flag Alt

        if is_enter_key and alt_is_pressed:
            # Jika Alt + Enter terdeteksi
            if hasattr(self.parent_chat_window, 'send_message'):
                print("DEBUG: Alt+Enter pressed, calling send_message.") # Debugging
                self.parent_chat_window.send_message()
                event.accept()  # Tandai event sudah ditangani, jangan proses lebih lanjut (mis. jangan buat baris baru)
                return          # Keluar dari fungsi setelah menangani
            else:
                # Fallback jika karena suatu alasan send_message tidak ada
                super().keyPressEvent(event)
        else:
            # Jika bukan Alt+Enter, biarkan QTextEdit menangani event seperti biasa
            # (misalnya, Enter biasa akan membuat baris baru, ketikan lain akan muncul, dll.)
            super().keyPressEvent(event)

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

        @self.sio.on('status_updated')
        def on_status_updated(data):
            print(f"DEBUG: WebSocketThread (client) - Menerima 'status_updated': {data}")
            # Emit sinyal ke ChatWindow dengan data status baru
            self.chat_window.status_update_signal.emit(data)
                
    def run(self):
        # MODIFIKASI DI SINI: Tambahkan /socket.io/ pada URL
        try:
            # Lakukan koneksi. Pustaka akan menangani handshake Engine.IO/Socket.IO.
            # Ia akan mencoba path default /socket.io/
            # 'transports=['websocket']' memaksa penggunaan WebSocket.
            self.sio.connect(BASE_URL, transports=['websocket'])
            
            # sio.wait() akan menjaga thread ini tetap aktif dan memproses event
            # sampai sio.disconnect() dipanggil atau koneksi terputus.
            self.sio.emit('join', {'user_id': self.chat_window.user['id']}) 
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
        display_text = processed_text.replace('\n', '<br>')

        # display_text = text # Server sudah mengirim format [File: namafile.ext]

        # Tambahkan sedikit style jika ini adalah file untuk membuatnya terlihat seperti link
        if self.filename_to_download and text.startswith("[File:"):
            # Ambil nama file dari teks seperti "[File: namafile.PNG]"
            actual_filename_in_text = text[len("[File: "):-1]
            display_text = f"<a href='#' style='color: inherit; text-decoration: underline;'>📄 File: {actual_filename_in_text}</a>"
        
        # Create message bubble styling similar to the image
        if is_me:
            message_html = f"""
            <div style='font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; font-size: 12px; line-height: 1; white-space: normal; word-wrap: break-word; max-width: 100%;'>
                <div style='color: #FFFFFF; margin-bottom: 10px; '>{display_text}</div>
                <div style='color: rgba(255,255,255,0.8); font-size: 11px; text-align: right; margin-top: 4px;'>{time}</div>
            </div>"""
            self.setStyleSheet("""
                BubbleMessage {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #4A90E2, stop:1 #357ABD);
                    border-radius: 18px;
                    margin: 4px 4px 4px 4px;
                    max-width: 400px;
                }""")
        else:
            message_html = f"""
            <div style='font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; font-size: 12px; line-height: 1; white-space: normal; word-wrap: break-word; max-width: 100%;'>
                <div style='color: #2C3E50; margin-bottom: 10px; '>{display_text}</div>
                <div style='color: #95A5A6; font-size: 11px; text-align: left; margin-top: 4px;'>{time}</div>
            </div>"""
            self.setStyleSheet("""
                BubbleMessage {
                    background-color: #FFFFFF; border: 1px solid #E8ECEF; border-radius: 18px;
                    margin: 4px 4px 4px 4px;
                    max-width: 400px;
                }""")

        self.setText(message_html)
        self.setWordWrap(True)
        self.setMaximumWidth(400)
        self.setAlignment(Qt.AlignLeft if not is_me else Qt.AlignRight)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)

        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(8); shadow.setColor(QColor(0, 0, 0, 20)); shadow.setOffset(0, 2)
        self.setGraphicsEffect(shadow)
        
        # Jika ada file, aktifkan link opening
        if self.filename_to_download:
            self.setOpenExternalLinks(False) # Kita handle kliknya manual
            # self.linkActivated.connect(self.handle_link_click) # Tidak perlu jika mousePressEvent cukup

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.filename_to_download:
            # Pastikan BASE_URL di client.py dan it.py sudah benar
            download_url_str = f"{BASE_URL}/uploads/{self.filename_to_download}"
            print(f"Attempting to open URL for download: {download_url_str}")
            QDesktopServices.openUrl(QUrl(download_url_str))
            event.accept() # Tandai event sudah dihandle
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
    def __init__(self, conversation_data, user_role):
        super().__init__()
        self.conversation_data = conversation_data
        self.setup_ui(conversation_data, user_role)
    
    def setup_ui(self, conv, user_role):
        layout = QHBoxLayout()
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(12)
        
        # Avatar circle
        avatar = QLabel()
        avatar.setFixedSize(48, 48)
        avatar.setStyleSheet("""
            QLabel {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #6C7CE7, stop:1 #A8E6CF);
                border-radius: 20px;
                color: white;
                font-weight: bold;
                font-size: 18px;
            }
        """)
        
        if user_role == 'employee':
            name = conv.get('tech_name', 'Tech')
            avatar.setText(name[:2].upper())
        else:
            name = conv.get('employee_name', 'User')
            avatar.setText(name[:2].upper())
        
        avatar.setAlignment(Qt.AlignCenter)
        layout.addWidget(avatar)
        
        # Message info
        info_layout = QVBoxLayout()
        info_layout.setSpacing(4)
        
        # Name and status
        name_status_layout = QHBoxLayout()
        name_label = QLabel(name)
        name_label.setStyleSheet("""
            QLabel {
                font-size: 15px;
                font-weight: 600;
                color: #2C3E50;
            }
        """)
        name_status_layout.addWidget(name_label)
        
        if conv.get('status') == 'closed':
            status_label = QLabel("• Closed")
            status_label.setStyleSheet("color: #95A5A6; font-size: 12px;")
            name_status_layout.addWidget(status_label)
                
        layout.addLayout(info_layout)
        self.setLayout(layout)
        
        # Hover effect
        self.setStyleSheet("""
            ConversationItem {
                background-color: #4A90E2;
                border: 20px solid #4A90E2;
                border-radius: 8px;
            }
            ConversationItem:hover {
                background-color: #F8F9FA;
            }
        """)

class ChatWindow(QWidget):
    receive_message_signal = pyqtSignal(dict)
    status_update_signal = pyqtSignal(dict)
    
    def __init__(self, user, parent=None):
        super().__init__(parent)
        self.user = user
        self.current_conversation = None
        self.unread_map = {}
        self.message_cache = {}
        self.setup_ui()
        self.load_conversations()
        
        self.status_update_signal.connect(self.handle_status_updated)
        # Timer untuk refresh
        self.timer = QTimer(self)
        # self.timer.timeout.connect(self.refresh_messages)
        # self.timer.start(3000)
        
        # Setup WebSocket
        self.receive_message_signal.connect(self.handle_received_message)
        self.ws_thread = WebSocketThread(self)
        self.ws_thread.start()
        
    
    def setup_ui(self):
        self.setWindowTitle(f"IT Chat (Client) - {self.user['full_name']} ({self.user['role'].title()})")
        self.resize(600, 700)
        # self.setFixedSize(600, 900)
        
        # Main layout
        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Left Sidebar
        sidebar = QFrame()
        sidebar.setFixedWidth(70)
        sidebar.setStyleSheet("""
            QFrame {
                background-color: #FFFFFF;
                border-right: 1px solid #E8ECEF;
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
                background-color: #FFFFFF;
                border-bottom: 1px solid #E8ECEF;
            }
        """)
        
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(20, 15, 20, 15)
        
        # App title with icon
        title_layout = QHBoxLayout()
        title_layout.setSpacing(8)
        
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
                background-color: #EAF3FF; /* biru muda */
                
                border: 20px solid #4A90E2 transparent;
            }
        """)
        self.conversation_list.itemClicked.connect(self.select_conversation)
        sidebar_layout.addWidget(self.conversation_list)
        
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
        
        chat_header_layout = QHBoxLayout()
        chat_header_layout.setContentsMargins(24, 15, 24, 15)
        
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
        info_layout.setSpacing(2)
        
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
        self.show_past_messages = QPushButton("Show Previous Messages")
        self.show_past_messages.setCheckable(True)
        self.show_past_messages.setFixedSize(200, 45)
        self.show_past_messages.setStyleSheet('''
            QPushButton {
                background-color: rgba(74, 144, 226, 0.1);
                color: #4A90E2;
                border: 2px solid #4A90E2;
                border-radius: 18px;
                font-size: 12px;
                font-weight: 500;
                padding: 6px 12px;
                margin: 6px;
            }
            QPushButton:hover {
                background-color: rgba(74, 144, 226, 0.2);
                border-color: #357ABD;
                color: #357ABD;
            }
            QPushButton:pressed {
                background-color: rgba(74, 144, 226, 0.3);
            }
            QPushButton:checked {
                background-color: #4A90E2;
                color: white;
                border-color: #4A90E2;
            }
            QPushButton:checked:hover {
                background-color: #357ABD;
                border-color: #357ABD;
            }
        ''')
        self.show_past_messages.clicked.connect(self.handle_past_message_button) # Handler baru
        
        past_messages_container = QWidget()
        past_messages_container.setStyleSheet("background-color: transparent;")
        past_messages_layout = QHBoxLayout(past_messages_container)
        past_messages_layout.setContentsMargins(0, 0, 0, 0)
        past_messages_layout.addWidget(self.show_past_messages, alignment=Qt.AlignCenter)
        
        chat_area.addWidget(past_messages_container)

        if not self.current_conversation:
            self.show_past_messages.hide()
        
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
        # input_area.setFixedHeight(80)
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
        self.message_input = QTextEdit()
        self.message_input = FilePasteTextEdit(self)
        # self.message_input.setMaximumHeight(48)
        self.message_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
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
                if response.status_code == 200:
                    print("File berhasil dikirim")
                    # Server akan mengirim event socket, yang akan menambahkan pesan ke UI.
                else:
                    print(f"Gagal mengirim file: {response.status_code} - {response.text}")
        except Exception as e:
            print(f"Terjadi kesalahan saat mengirim file: {e}")

    def mark_conversation_unread(self, conversation_id):
        for i in range(self.conversation_list.count()):
            item = self.conversation_list.item(i)
            if item.data(Qt.UserRole) == conversation_id:
                widget = self.conversation_list.itemWidget(item)
                widget.setStyleSheet("""
                    ConversationItem {
                        background-color: #EAF3FF;  /* biru muda */
                        border-radius: 8px;
                    }
                """)
                # Bisa juga kasih tanda titik di pojok kanan:
                if not hasattr(widget, 'unread_dot'):
                    dot = QLabel("•")
                    dot.setStyleSheet("color: #4A90E2; font-size: 20px;")
                    dot.setAlignment(Qt.AlignRight)
                    widget.layout().addWidget(dot)
                    widget.unread_dot = dot
    

    def handle_status_updated(self, data):
        technician_id = data.get('user_id')
        new_status = data.get('status')

        # Pertama, update data di semua ConversationItem yang relevan (untuk konsistensi)
        for i in range(self.conversation_list.count()):
            item = self.conversation_list.item(i)
            widget = self.conversation_list.itemWidget(item)
            if widget and widget.conversation_data.get('technician_id') == technician_id:
                widget.conversation_data['tech_status'] = new_status

        # Kedua, jika percakapan yang sedang aktif adalah dengan teknisi ini, update header
        current_item = self.conversation_list.currentItem()
        if current_item:
            widget = self.conversation_list.itemWidget(current_item)
            if widget and widget.conversation_data.get('technician_id') == technician_id:
                self.chat_status.setText(f"● {new_status}")
                if new_status.lower() == 'online':
                    self.chat_status.setStyleSheet("color: #2ECC71; font-size: 13px;")
                elif new_status.lower() == 'nonaktif':
                    self.chat_status.setStyleSheet("color: #BDC3C7; font-size: 13px;")
                else:
                    self.chat_status.setStyleSheet("color: #F1C40F; font-size: 13px;")

    def load_conversations(self):
        try: 
            response = requests.get(f"{BASE_URL}/get_conversations/{self.user['id']}")
            print(f"DEBUG: ChatWindow - Status load_conversations: {response.status_code}") # DEBUG
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
                
            for conv_data in conversations:
                print(f"DEBUG: ChatWindow - Memproses conv ID: {conv_data.get('id')}") # DEBUG
                item = QListWidgetItem()
                item.setData(Qt.UserRole, conv_data['id'])
                
                conv_widget = ConversationItem(conv_data, self.user['role'])
                item.setSizeHint(conv_widget.sizeHint())
                
                self.conversation_list.addItem(item)
                self.conversation_list.setItemWidget(item, conv_widget)
                
                if self.unread_map.get(conv_data['id'], False) and conv_data['id'] != self.current_conversation:
                    self.mark_conversation_unread(conv_data['id'])

                if conv_data['id'] == self.current_conversation:
                    self.conversation_list.setCurrentItem(item)
                
                print(f"DEBUG: ChatWindow - Unread message: \n {self.unread_map}") # DEBUG

        except requests.exceptions.RequestException as e:
            print(f"DEBUG: Error koneksi saat memuat percakapan: {e}")
        except Exception as e:
            print(f"DEBUG: Error tak terduga di load_conversations: {e}")

    
    def select_conversation(self, item):
        if not item:
            print("DEBUG: ChatWindow - select_conversation dipanggil dengan item None") # DEBUG
            return
        
        self.show_past_messages.show()
        self.show_past_messages.setChecked(True)

        conversation_id = item.data(Qt.UserRole)
        print(f"DEBUG: ChatWindow - Memilih percakapan ID: {conversation_id}") # DEBUG
        self.current_conversation = conversation_id
        QTimer.singleShot(100, self.scroll_to_bottom)
        # Update chat header
        conv_widget = self.conversation_list.itemWidget(item)
        if not conv_widget:
            print(f"DEBUG: ChatWindow - Tidak ada widget untuk item percakapan ID: {conversation_id}") # DEBUG
            return
        conv_data = conv_widget.conversation_data
        
        if self.user['role'] == 'employee':
            name = conv_data.get('tech_name', 'Technician')
            # <<< AMBIL STATUS DARI DATA PERCAKAPAN >>>
            tech_status = conv_data.get('tech_status', 'Nonaktif')
        else: # seharusnya tidak terjadi di client.py
            name = conv_data.get('employee_name', 'User')
            tech_status = "Online"

        self.chat_name.setText(name)
        self.chat_status.setText(f"● {tech_status}") 
        
        # Atur warna berdasarkan status
        if tech_status.lower() == 'online':
            self.chat_status.setStyleSheet("color: #2ECC71; font-size: 13px;") # Hijau
        elif tech_status.lower() == 'nonaktif':
            self.chat_status.setStyleSheet("color: #BDC3C7; font-size: 13px;") # Abu-abu
        else: # Istirahat, Rapat, dll.
            self.chat_status.setStyleSheet("color: #F1C40F; font-size: 13px;") # Kuning

        self.chat_avatar.setText(name[0].upper())
        self.load_messages(conversation_id)
        
        # Reset style saat dibuka
        item.setSelected(False)
        conv_widget.setStyleSheet("")  # Hapus efek biru
        if hasattr(conv_widget, 'unread_dot'):
            conv_widget.unread_dot.deleteLater()
            del conv_widget.unread_dot
    
    def load_messages(self, conversation_id, time="current", scroll_to_bottom=False):
        print(f"DEBUG: ChatWindow - Memuat pesan untuk conv_id: {conversation_id}") # DEBUG
        try:
            response = requests.get(f"{BASE_URL}/get_messages/{conversation_id}/{time}", timeout=5)
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
                            file_path=msg_data.get('file_path') # DIPERBARUI: Teruskan file_path
                        )
                        # bubble.msg_id = msg.get('id') # Simpan ID pesan di bubble
                if scroll_to_bottom:
                    QTimer.singleShot(100, self.scroll_to_bottom)
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
    
    def scroll_to_bottom(self):
        scrollbar = self.scroll_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def refresh_messages(self):
        if self.current_conversation:
            self.load_messages(self.current_conversation)
            return
        
        # Simpan posisi scroll sebelum refresh
        scrollbar = self.scroll_area.verticalScrollBar()
        scroll_position = scrollbar.value()
        at_bottom = scrollbar.value() == scrollbar.maximum()
        
        # Load messages
        self.load_messages(self.current_conversation)
        
        # Jika sebelumnya tidak di bagian bawah, kembalikan ke posisi semula
        if not at_bottom:
            QTimer.singleShot(100, lambda: scrollbar.setValue(scroll_position))
            
    def handle_received_message(self, data):
        conv_id = data['conversation_id']
        message_content = data['message'] # Ini dictionary: {id, message, sender_id, sender_name, sent_at}
        print(f"DEBUG: IT/handle_received_message - 📨 Pesan baru untuk conv_id {conv_id}: {message_content.get('message')}")

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
                    message_content.get('file_path')
                )
        else: # Pesan untuk percakapan yang tidak aktif
            if item_found_in_sidebar:
                print(f"DEBUG: IT/handle_received_message - Pesan untuk percakapan TIDAK aktif {conv_id}. Menandai belum dibaca dan pindah ke atas.")
                self.mark_conversation_unread(conv_id) # Ini akan set preview_label ke "🔵 New message"
            else:
                # Percakapan ini belum ada di list, mungkin percakapan baru yang dibuat oleh employee lain
                print(f"DEBUG: IT/handle_received_message - Pesan untuk percakapan BARU {conv_id} (tidak ada di list). Memuat ulang semua.")
                self.load_conversations() # Muat ulang semua untuk menampilkan percakapan baru ini
                self.unread_map[conv_id] = True # Tandai sebagai belum dibaca di map

    def handle_past_message_button(self):
        if not self.current_conversation:
            QMessageBox.information(self, "Info", "Tidak ada percakapan yang dipilih untuk melihat pesan sebelumnya.")
            return
        print(f"DEBUG: ChatWindow - {self.show_past_messages.isChecked()}.")
        # Cek apakah tombol sudah aktif
        if self.show_past_messages.isChecked():
            # Jika sudah aktif, sembunyikan pesan sebelumnya
            self.show_past_messages.setText("Show Previous Messages")
            print("DEBUG: ChatWindow - Menyembunyikan pesan sebelumnya.")
            self.load_messages(self.current_conversation, time="current")
            
        else:
            # Jika belum aktif, tampilkan pesan sebelumnya
            self.show_past_messages.setText("Hide Previous Messages")
            print("DEBUG: ChatWindow - Menampilkan pesan sebelumnya.")
            # Tampilkan semua pesan sebelumnya
            self.load_messages(self.current_conversation, time="all")

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
    
    # Modifikasi add_message_to_ui untuk menyimpan msg_id
    def add_message_to_ui(self, message, is_me, sender_name, sent_at, msg_id, file_path=None):
        bubble = BubbleMessage(message, is_me, sender_name, sent_at, file_path=file_path)
        bubble.msg_id = msg_id # Simpan ID pesan di bubble

        container = QWidget()
        container_layout = QHBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        
        if is_me:
            container_layout.addStretch()
            container_layout.addWidget(bubble)
        else:
            container_layout.addWidget(bubble)
            container_layout.addStretch()
        
        
        # Sisipkan sebelum stretch item terakhir di self.messages_layout
        self.messages_layout.insertWidget(self.messages_layout.count() - 1, container)
        QTimer.singleShot(100, self.scroll_to_bottom)
    
    def send_message(self):
        if not self.current_conversation or not self.message_input.toPlainText().strip():
            return
        
        message = self.message_input.toPlainText().strip()
        data = {
            'conversation_id': self.current_conversation,
            'sender_id': self.user['id'],
            'message': message
        }
        
        response = requests.post(f"{BASE_URL}/send_message", json=data)
        self.message_input.clear()
        if response.status_code == 200:
            self.message_input.clear()
            QTimer.singleShot(100, self.scroll_to_bottom)
        else:
            QTimer.singleShot(100, self.scroll_to_bottom)
    
    def create_new_conversation(self):
        data = {
            'employee_id': self.user['id'],
            'technician_id': None
        }
        
        response = requests.post(f"{BASE_URL}/create_conversation", json=data)
        if response.status_code == 200:
            self.load_conversations()
    
    def closeEvent(self, event):
        print("DEBUG: ChatWindow - closeEvent triggered. Returning to LoginWindow.")

        # 1. Hentikan WebSocketThread
        if hasattr(self, 'ws_thread') and self.ws_thread.is_alive():
            print("DEBUG: ChatWindow - Stopping WebSocket thread...")
            self.ws_thread.stop()  # Panggil metode stop dari WebSocketThread
            self.ws_thread.join(timeout=2) # Tunggu thread selesai (opsional, dengan timeout)
            if self.ws_thread.is_alive():
                print("DEBUG: ChatWindow - WebSocket thread did not stop in time.")
            else:
                print("DEBUG: ChatWindow - WebSocket thread stopped.")
        else:
            print("DEBUG: ChatWindow - WebSocket thread not found or not alive.")

        # 2. Buat dan tampilkan instance baru dari LoginWindow
        # Kita akan membuat atribut sementara untuk LoginWindow baru agar tidak langsung di-garbage collect
        # sebelum sempat ditampilkan, meskipun .show() biasanya cukup.
        print("DEBUG: ChatWindow - Re-instantiating and showing LoginWindow.")
        self._login_window_after_close = LoginWindow() # Buat instance baru
        self._login_window_after_close.show()

        # 3. Terima event close untuk ChatWindow ini agar benar-benar ditutup dan dihancurkan.
        # Karena LoginWindow baru sudah ditampilkan, aplikasi tidak akan keluar
        # (jika QApplication.quitOnLastWindowClosed() adalah default True).
        print("DEBUG: ChatWindow - Accepting close event to close and destroy current ChatWindow.")
        event.accept()
        # super().closeEvent(event) # bisa juga digunakan sebagai alternatif event.accept()
                                 # jika ada logika closeEvent di parent class QWidget yang ingin dijalankan.
                                 # Untuk kasus umum, event.accept() cukup.
        
class LoginWindow(QWidget):
    def __init__(self):
        super().__init__()
        
        self.settings = QSettings("MyCompany", "ITHelpDesk(Client)") 
        self.saved_accounts = []

        self.search_thread = None
        self.server_finder = None

        self.setup_ui()
        self.load_saved_accounts_to_combo()
        self.load_last_saved_nik()

        self.start_new_search_thread()
    
    def setup_ui(self):
        self.setWindowTitle("Login - IT Chat (Client)")
        # self.setFixedSize(480, 650)
        self.resize(480, 650)
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
        title = QLabel("IT Chat (Client)")
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
        form_layout.setContentsMargins(40, 40, 40, 40)
        form_layout.setSpacing(24)
        
        # --- Saved Accounts ComboBox & Clear Button ---
        saved_accounts_header_layout = QHBoxLayout()
        saved_accounts_label = QLabel("Saved NIK/Usernames:") # Sesuaikan label
        saved_accounts_label.setStyleSheet("font-size: 13px; color: #555; margin-bottom: 0px;")
        saved_accounts_header_layout.addWidget(saved_accounts_label)
        saved_accounts_header_layout.addStretch()

        self.clear_cache_button = QPushButton("Clear")
        self.clear_cache_button.setStyleSheet("""
            QPushButton { font-size: 11px; color: #E74C3C; background-color: transparent;
                          border: 1px solid #E74C3C; border-radius: 4px; padding: 3px 8px; }
            QPushButton:hover { background-color: #FADBD8; }
            QPushButton:pressed { background-color: #F5B7B1; }
        """)
        self.clear_cache_button.setToolTip("Clear all saved NIK/Usernames")
        self.clear_cache_button.clicked.connect(self.clear_saved_accounts)
        saved_accounts_header_layout.addWidget(self.clear_cache_button)
        form_layout.addLayout(saved_accounts_header_layout)

        self.accounts_combo = QComboBox()
        # Stylesheet accounts_combo sama seperti di it.py
        self.accounts_combo.setStyleSheet("""
            QComboBox { padding: 12px; font-size: 14px; border: 1px solid #E0E0E0;
                        border-radius: 8px; background-color: #FDFDFD;
                        selection-background-color: #e6efff; selection-color: #333; }
            QComboBox::drop-down { border: none; }
            QComboBox::down-arrow { image: url(none); }
            QComboBox QAbstractItemView { background-color: white; border: 1px solid #D0D0D0; border-radius: 4px;
                                        selection-background-color: transparent; outline: 0px; }
            QComboBox QAbstractItemView::item { padding: 8px 12px; color: #333; background-color: white; }
            QComboBox QAbstractItemView::item:hover { background-color: #f0f5ff; color: #000; }
            QComboBox QAbstractItemView::item:selected { background-color: #cce0ff; color: #000000; }
        """)
        self.accounts_combo.currentIndexChanged.connect(self.on_account_selected_from_combo)
        form_layout.addWidget(self.accounts_combo)
        # --- End Saved Accounts ComboBox & Clear Button ---
        
        
        # Welcome text
        # welcome_label = QLabel("Welcome back!")
        # welcome_label.setStyleSheet("""
        #     QLabel {
        #         font-size: 20px;
        #         font-weight: 600;
        #         color: #2C3E50;
        #         margin-bottom: 10px;
        #     }
        # """)
        # form_layout.addWidget(welcome_label)
        # --- Remember Me Checkbox (atau "Remember NIK") ---
        self.remember_me_checkbox = QCheckBox("Remember NIK") # Sesuaikan teks
        self.remember_me_checkbox.setStyleSheet("font-size: 14px; color: #333; padding-top: 5px;")
        self.remember_me_checkbox.setChecked(True)
        form_layout.addWidget(self.remember_me_checkbox)
        
        welcome_sub = QLabel("Please sign in to your account")
        welcome_sub.setStyleSheet("""
            QLabel {
                font-size: 14px;
                color: #7F8C8D;
                margin-bottom: 20px;
            }
        """)
        form_layout.addWidget(welcome_sub)
        
        # 1. Buat QHBoxLayout untuk menampung label status dan tombol scan
        status_layout = QHBoxLayout()
        status_layout.setContentsMargins(0, 0, 0, 0) # Hapus margin internal

        # 2. Buat label status seperti biasa
        self.server_status_label = QLabel("🔍 Mencari server di jaringan...")
        self.server_status_label.setAlignment(Qt.AlignCenter)
        self.server_status_label.setStyleSheet("color: #7f8c8d; font-style: italic; margin-bottom: 10px;")
        
        # 3. Buat tombol scan
        self.scan_button = QPushButton("Scan")
        self.scan_button.setFixedSize(60, 28) # Atur ukuran agar pas
        self.scan_button.setStyleSheet("""
            QPushButton { 
                font-size: 12px; 
                color: #3498DB; 
                background-color: transparent;
                border: 1px solid #3498DB; 
                border-radius: 14px; 
                padding: 3px 8px; 
            }
            QPushButton:hover { background-color: #EAF3FF; }
            QPushButton:pressed { background-color: #D4E6F1; }
            QPushButton:disabled {
                color: #BDC3C7;
                border-color: #BDC3C7;
                background-color: transparent;
            }
        """)
        self.scan_button.setToolTip("Pindai ulang jaringan untuk mencari server")
        # Hubungkan tombol ke fungsi yang memulai pencarian
        self.scan_button.clicked.connect(self.start_new_search_thread)
        
        # 4. Tambahkan label dan tombol ke layout horizontal
        status_layout.addStretch() # Pendorong agar konten ke tengah
        status_layout.addWidget(self.server_status_label)
        status_layout.addSpacing(10) # Jarak antara label dan tombol
        status_layout.addWidget(self.scan_button)
        status_layout.addStretch() # Pendorong agar konten ke tengah

        # 5. Tambahkan layout horizontal ini ke form_layout utama
        form_layout.addLayout(status_layout)
        
        # Username input
        username_label = QLabel("NIK (nomor induk karyawan)")
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
        self.username_input.setPlaceholderText("Enter your NIK")
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
        
        # Login button
        self.login_btn = QPushButton("Sign In")
        self.login_btn.clicked.connect(self.handle_login)
        self.login_btn.setStyleSheet("""
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
        self.login_btn.setEnabled(False)
        self.login_btn.setToolTip("Mencari server di jaringan...")
        form_layout.addWidget(self.login_btn)
        
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

    def start_new_search_thread(self):
        """
        Menghentikan thread lama (jika ada) dan memulai thread pencarian yang baru.
        Inilah yang harus dipanggil oleh tombol "Scan".
        """
        # Hentikan dan bersihkan thread lama jika sedang berjalan
        if self.search_thread and self.search_thread.isRunning():
            self.server_finder.stop()
            self.search_thread.quit()
            self.search_thread.wait()

        # Atur ulang UI ke status "Mencari"
        self.server_status_label.setText("🔍 Mencari server di jaringan...")
        self.server_status_label.setStyleSheet("color: #7f8c8d; font-style: italic;")
        self.login_btn.setEnabled(False)
        self.scan_button.setEnabled(False) # Nonaktifkan tombol scan selama pencarian
        self.scan_button.setText("...")

        # Buat instance QThread dan ServerFinder yang BARU
        self.search_thread = QThread()
        self.server_finder = ServerFinder()
        self.server_finder.moveToThread(self.search_thread)

        # Hubungkan sinyal
        self.search_thread.started.connect(self.server_finder.find_continuously)
        self.server_finder.finished.connect(self.on_server_found)
        self.server_finder.not_found.connect(self.on_server_not_found)
        
        # Mulai thread baru
        self.search_thread.start()

    def on_server_found(self, ip, port):
        # Update UI saat server ditemukan
        self.server_status_label.setText(f"✅ Server ditemukan di {ip}:{port}")
        self.server_status_label.setStyleSheet("color: #27ae60; font-weight: bold;")
        self.login_btn.setToolTip("Klik untuk masuk ke server")
        self.login_btn.setEnabled(True)
        
        # Aktifkan kembali tombol scan dan reset teksnya
        self.scan_button.setEnabled(True)
        self.scan_button.setText("Scan")

        # Hentikan thread saat ini karena tugasnya sudah selesai
        if self.search_thread.isRunning():
            self.server_finder.stop()
            self.search_thread.quit()
            self.search_thread.wait()

    def on_server_not_found(self):
        # Update UI saat server TIDAK ditemukan dalam satu siklus pencarian
        self.server_status_label.setText("❌ Server tidak ditemukan. Mencoba lagi...")
        
        # Aktifkan kembali tombol scan agar pengguna bisa mencoba manual jika mau
        self.scan_button.setEnabled(True)
        self.scan_button.setText("Scan")

    def closeEvent(self, event):
        # Pastikan thread dihentikan saat window ditutup
        if self.search_thread and self.search_thread.isRunning():
            self.server_finder.stop()
            self.search_thread.quit()
            self.search_thread.wait()
        super().closeEvent(event)

    def load_saved_accounts_to_combo(self):
        self.accounts_combo.blockSignals(True)
        self.accounts_combo.clear()
        self.accounts_combo.addItem("-- Select a saved NIK --", userData=None) # Placeholder

        self.saved_accounts = self.settings.value("saved_client_accounts", []) # Key berbeda untuk client
        if not isinstance(self.saved_accounts, list):
            self.saved_accounts = []

        for account in self.saved_accounts:
            # Di client, kita hanya menyimpan username (NIK)
            if isinstance(account, dict) and "username" in account:
                self.accounts_combo.addItem(account["username"], userData=account)
        
        self.accounts_combo.blockSignals(False)
        self.clear_cache_button.setVisible(self.accounts_combo.count() > 1)


    def on_account_selected_from_combo(self, index):
        if index <= 0: 
            # self.username_input.clear() # Opsional, agar tidak mengganggu jika pengguna mau ketik manual
            return

        selected_account_data = self.accounts_combo.itemData(index)
        if selected_account_data and isinstance(selected_account_data, dict):
            self.username_input.setText(selected_account_data.get("username", ""))
            # Tidak ada field password di UI login client ini, jadi tidak perlu diisi

    def load_last_saved_nik(self):
        """Memuat NIK terakhir yang disimpan dan menampilkannya di input field."""
        # Kita gunakan key yang berbeda, misal 'last_client_nik'
        last_nik = self.settings.value("last_client_nik", "") 
        if last_nik:
            self.username_input.setText(last_nik)
            print(f"DEBUG: NIK terakhir '{last_nik}' berhasil dimuat.")

    # Tambahkan method ini juga di dalam kelas LoginWindow di client.py

    def save_last_nik(self, nik):
        """Menyimpan NIK yang baru saja berhasil login."""
        self.settings.setValue("last_client_nik", nik)
        self.settings.sync()
        print(f"DEBUG: NIK terakhir '{nik}' berhasil disimpan.")
    
    def handle_login(self):
        username = self.username_input.text() # Ini adalah NIK
        
        if not username: # Hanya NIK yang diperlukan untuk login client
            self.show_error("NIK is required")
            return
        
        data_to_server = {'username': username} # Data yang dikirim ke server
        
        try:
            response = requests.post(f"{BASE_URL}/login", json=data_to_server) # Endpoint login client
            if response.status_code == 200:
                result = response.json()
                if result['success']:
                    if self.remember_me_checkbox.isChecked():
                        self.save_account_to_settings(username) # Simpan NIK
                        self.save_last_nik(username)

                    self.chat_window = ChatWindow(result['user']) # ChatWindow sudah terdefinisi di client.py
                    self.chat_window.show()
                    self.close()
                else:
                    self.show_error(result.get('message', "Invalid NIK."))
            else:
                self.show_error(f"Server error: {response.status_code}. Please try again later.")
        except requests.exceptions.ConnectionError:
            self.show_error("Cannot connect to server. Please check your connection.")
        except Exception as e:
            self.show_error(f"An unexpected error occurred: {str(e)}")


    def save_account_to_settings(self, username_to_save): # Hanya menerima username (NIK)
        current_saved_accounts = self.settings.value("saved_client_accounts", []) # Key berbeda
        if not isinstance(current_saved_accounts, list):
            current_saved_accounts = []

        account_exists = False
        for acc in current_saved_accounts:
            if isinstance(acc, dict) and acc.get("username") == username_to_save:
                account_exists = True
                break 
        
        if not account_exists:
            # Hanya simpan username karena tidak ada input password
            current_saved_accounts.append({"username": username_to_save}) 
        
        max_saved_accounts = 5 
        if len(current_saved_accounts) > max_saved_accounts:
            current_saved_accounts = current_saved_accounts[-max_saved_accounts:]

        self.settings.setValue("saved_client_accounts", current_saved_accounts)
        self.settings.sync()
        self.load_saved_accounts_to_combo()

    def clear_saved_accounts(self):
        reply = QMessageBox.question(self, "Clear Saved NIKs",
                                     "Are you sure you want to clear all saved NIKs?",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.settings.remove("saved_client_accounts") # Key berbeda
            self.settings.sync()
            self.load_saved_accounts_to_combo()
            self.username_input.clear()
            QMessageBox.information(self, "Cleared", "Saved NIKs have been cleared.")

    def show_error(self, message):
        self.error_label.setText(f"⚠️ {message}")
        self.error_label.show()
        
        # Hide error after 5 seconds
        QTimer.singleShot(5000, self.error_label.hide)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    # Set application icon if available
    # app.setWindowIcon(QIcon("icon.png"))
    
    login_window = LoginWindow()
    login_window.show()
    
    sys.exit(app.exec_())