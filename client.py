import sys
import os
import requests
import json
import threading
import time
import socketio
from websocket import create_connection

from PyQt5.QtWidgets import QFileDialog
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QListWidget, QTextEdit,
    QScrollArea, QFrame, QSizePolicy, QListWidgetItem, QGraphicsDropShadowEffect,
    QFileDialog, QMessageBox
)
from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply # Untuk memuat gambar secara asinkron
from PyQt5.QtCore import pyqtSignal, Qt, QTimer, QUrl, QMimeData, QDir, QStandardPaths
from PyQt5.QtGui import QColor, QFont, QPainter, QBrush, QPalette, QPixmap, QIcon, QDesktopServices, QImage


# Suppress font warnings
os.environ['QT_LOGGING_RULES'] = 'qt.qpa.fonts=false'

IP = "192.168.45.141" 
# IP = "192.168.1.7" 
PORT = "5000"

# BASE_URL = "http://localhost:5000"
BASE_URL = "http://192.168.56.1:5000"  # Ganti <IP_KANTOR> dengan IP server
# BASE_URL = "http://192.168.1.7:5000"  # Ganti <IP_KANTOR> dengan IP server

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

        
    def run(self):
        ws = create_connection("ws://192.168.56.1:5000")
        # ws = create_connection(f"ws://{BASE_URL.split('//')[1]}")
        while self.running:
            try:
                message = ws.recv()
                data = json.loads(message)
                if data.get('event') == 'new_message':
                    self.chat_window.receive_message_signal.emit(data['data'])
            except Exception as e:
                print("WebSocket error:", e)
                break
        ws.close()


        
# In client.py
# class BubbleMessage(QLabel):
#     # Tambahkan file_path=None ke konstruktor
#     def __init__(self, text, is_me, sender_name, time, file_path=None, parent=None): # DIPERBARUI
#         super().__init__(parent)
#         self.is_me = is_me
#         self.sender_name = sender_name
#         self.time = time
#         self.file_path = file_path # DITAMBAHKAN
#         self.msg_id = None # Tambahkan untuk menyimpan ID pesan

#         self.setWordWrap(True)
#         self.setMargin(15)
#         self.setTextFormat(Qt.RichText)

#         display_text = text
#         # if self.file_path:
#         #     display_text = f"📄 File: {os.path.basename(self.file_path)}"

#         if is_me:
#             message_html = f"""
#             <div style='font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; font-size: 12px; line-height: 1; white-space: normal; word-wrap: break-word; max-width: 100%;'>
#                 <div style='color: #FFFFFF; margin-bottom: 10px; '>{display_text}</div>
#                 <div style='color: rgba(255,255,255,0.8); font-size: 11px; text-align: right; margin-top: 4px;'>{time}</div>
#             </div>"""
#             self.setStyleSheet("""
#                 BubbleMessage {
#                     background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #4A90E2, stop:1 #357ABD);
#                     border-radius: 18px;
#                     margin: 4px 4px 4px 4px; /* Margin asli dari client.py */
#                     max-width: 400px;
#                 }""")
#         else: # Pesan dari orang lain
#             message_html = f"""
#             <div style='font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; font-size: 12px; line-height: 1; white-space: normal; word-wrap: break-word; max-width: 100%;'>
#                 <div style='color: #2C3E50; margin-bottom: 10px; '>{display_text}</div>
#                 <div style='color: #95A5A6; font-size: 11px; text-align: left; margin-top: 4px;'>{time}</div>
#             </div>"""
#             self.setStyleSheet("""
#                 BubbleMessage {
#                     background-color: #FFFFFF; border: 1px solid #E8ECEF; border-radius: 18px;
#                     margin: 4px 4px 4px 4px; /* Margin asli dari client.py */
#                     max-width: 400px;
#                 }""")

#         self.setText(message_html)
#         self.setWordWrap(True)
#         self.setMaximumWidth(400)
#         self.setAlignment(Qt.AlignLeft if not is_me else Qt.AlignRight) # client.py menggunakan perataan langsung
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

        display_text = text # Server sudah mengirim format [File: namafile.ext]

        # Tambahkan sedikit style jika ini adalah file untuk membuatnya terlihat seperti link
        if self.filename_to_download and text.startswith("[File:"):
            # Ambil nama file dari teks seperti "[File: namafile.PNG]"
            actual_filename_in_text = text[len("[File: "):-1]
            display_text = f"<a href='#' style='color: inherit; text-decoration: underline;'>📄 File: {actual_filename_in_text}</a>"

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
        
        # name_status_layout.addStretch()
        # info_layout.addLayout(name_status_layout)
        
        # Last message preview (if available)
        # preview_label = QLabel("Click to start conversation")
        # preview_label.setStyleSheet("""
        #     QLabel {
        #         color: #7F8C8D;
        #         font-size: 13px;
        #     }
        # """)
        # info_layout.addWidget(preview_label)
        
        layout.addLayout(info_layout)
        self.setLayout(layout)
        
        # Hover effect
        self.setStyleSheet("""
            ConversationItem {
                background-color: transparent;
                border-radius: 8px;
            }
            ConversationItem:hover {
                background-color: #F8F9FA;
            }
        """)

class ChatWindow(QWidget):
    receive_message_signal = pyqtSignal(dict)
    
    def __init__(self, user, parent=None):
        super().__init__(parent)
        self.user = user
        self.current_conversation = None
        self.unread_map = {}
        self.message_cache = {}
        self.setup_ui()
        self.load_conversations()
        
        # Timer untuk refresh
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_messages)
        self.timer.start(5000)
        
        # Setup WebSocket
        self.receive_message_signal.connect(self.handle_received_message)
        self.ws_thread = WebSocketThread(self)
        self.ws_thread.start()
        
    
    def setup_ui(self):
        self.setWindowTitle(f"IT Support Chat - {self.user['full_name']} ({self.user['role'].title()})")
        # self.resize(500, 700)
        self.setFixedSize(600, 900)
        
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
        
        # # Message icon
        # icon_label = QLabel("💬")
        # icon_label.setStyleSheet("font-size: 20px;")
        # title_layout.addWidget(icon_label)
        
        # title_label = QLabel("Messages")
        # title_label.setStyleSheet("""
        #     QLabel {
        #         font-size: 20px;
        #         font-weight: 700;
        #         color: #2C3E50;
        #     }
        # """)
        # title_layout.addWidget(title_label)
        # title_layout.addStretch()
        
        # header_layout.addLayout(title_layout)
        # header_widget.setLayout(header_layout)
        # sidebar_layout.addWidget(header_widget)
        
        # # Search bar
        # search_widget = QWidget()
        # search_widget.setFixedHeight(60)
        # search_widget.setStyleSheet("background-color: #FFFFFF;")
        
        # search_layout = QHBoxLayout()
        # search_layout.setContentsMargins(20, 10, 20, 10)
        
        # search_input = QLineEdit()
        # search_input.setPlaceholderText("🔍 Search messages...")
        # search_input.setStyleSheet("""
        #     QLineEdit {
        #         background-color: #F1F3F4;
        #         border: none;
        #         border-radius: 20px;
        #         padding: 10px 16px;
        #         font-size: 14px;
        #         color: #2C3E50;
        #     }
        #     QLineEdit:focus {
        #         background-color: #FFFFFF;
        #         border: 2px solid #4A90E2;
        #     }
        # """)
        # search_layout.addWidget(search_input)
        # search_widget.setLayout(search_layout)
        # sidebar_layout.addWidget(search_widget)
        
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
                background-color: #EBF3FF;
                border-left: 3px solid #4A90E2;
            }
        """)
        self.conversation_list.itemClicked.connect(self.select_conversation)
        sidebar_layout.addWidget(self.conversation_list)
        
        # New chat button (for employees)
        # if self.user['role'] == 'employee':
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
                border-bottom: 1px solid #E8ECEF;
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
        self.message_input.setMaximumHeight(48)
        self.message_input.setPlaceholderText("Add a comment...")
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
        else:
            name = conv_data.get('employee_name', 'Employee')
        
        self.chat_name.setText(name)
        self.chat_status.setText("🟢 Active now" if conv_data.get('status') != 'closed' else "⚫ Closed")
        self.chat_avatar.setText(name[0].upper())
        
        self.load_messages(conversation_id)
        
        # Reset style saat dibuka
        item.setSelected(False)
        conv_widget.setStyleSheet("")  # Hapus efek biru
        if hasattr(conv_widget, 'unread_dot'):
            conv_widget.unread_dot.deleteLater()
            del conv_widget.unread_dot
    
    # def load_messages(self, conversation_id):
    #     response = requests.get(f"{BASE_URL}/get_messages/{conversation_id}")
    #     if response.status_code == 200:
    #         messages = response.json()
            
    #         # Clear existing messages
    #         while self.messages_layout.count():
    #             item = self.messages_layout.takeAt(0)
    #             widget = item.widget()
    #             if widget is not None:
    #                 widget.deleteLater()
            
    #         # Add new messages
    #         for msg in messages:
    #             is_me = msg['sender_id'] == self.user['id']
    #             bubble = BubbleMessage(
    #                 msg['message'], 
    #                 is_me,
    #                 msg['sender_name'],
    #                 msg['sent_at']
    #             )
                
    #             # Create container for proper alignment
    #             container = QWidget()
    #             container_layout = QHBoxLayout()
    #             container_layout.setContentsMargins(0, 0, 0, 0)
                
    #             if is_me:
    #                 container_layout.addStretch()
    #                 container_layout.addWidget(bubble)
    #             else:
    #                 container_layout.addWidget(bubble)
    #                 container_layout.addStretch()
                
    #             container.setLayout(container_layout)
    #             self.messages_layout.addWidget(container)
            
    #         # Scroll to bottom
    #         QTimer.singleShot(100, self.scroll_to_bottom)
    
    def load_messages(self, conversation_id , scroll_to_bottom=False): 
        response = requests.get(f"{BASE_URL}/get_messages/{conversation_id}") #
        if response.status_code == 200:
            messages = response.json()
            
            while self.messages_layout.count() > 1: # Sisakan item 'stretch'
                item = self.messages_layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
            
            for msg in messages:
                is_me = msg['sender_id'] == self.user['id']
                bubble = BubbleMessage(
                    msg['message'], 
                    is_me,
                    msg['sender_name'],
                    msg['sent_at'],
                    file_path=msg.get('file_path') # DIPERBARUI: Teruskan file_path
                )
                bubble.msg_id = msg.get('id') # Simpan ID pesan di bubble

                container = QWidget()
                container_layout = QHBoxLayout()
                container_layout.setContentsMargins(0, 0, 0, 0)
                
                if is_me:
                    container_layout.addStretch()
                    container_layout.addWidget(bubble)
                else:
                    container_layout.addWidget(bubble)
                    container_layout.addStretch()
                
                container.setLayout(container_layout)
                self.messages_layout.insertWidget(self.messages_layout.count() - 1, container) # Masukkan sebelum 'stretch'
            if scroll_to_bottom:
                QTimer.singleShot(100, self.scroll_to_bottom)

    def handle_received_message(self, data): # data adalah dict berisi detail pesan
        conv_id = data['conversation_id'] #
        print("📨 Pesan baru diterima (Client):", data)

        message_details = data['message'] # Ini adalah dictionary untuk pesan itu sendiri

        if conv_id == self.current_conversation:
            if not self.message_exists(message_details.get('id')): # Periksa menggunakan ID pesan
                self.add_message_to_ui(message_details, scroll_to_bottom=True) # DIPERBARUI
                
                scrollbar = self.scroll_area.verticalScrollBar()
                if scrollbar.value() >= scrollbar.maximum() - 20:
                    QTimer.singleShot(100, self.scroll_to_bottom)
        else:
            self.mark_conversation_unread(data['conversation_id']) # Panggil dengan conv_id

    # Modifikasi add_message_to_ui untuk menerima seluruh dictionary pesan
    def add_message_to_ui(self, msg_data, scroll_to_bottom=True): # Tanda tangan DIPERBARUI, tambahkan scroll_to_bottom opsional
        is_me = msg_data['sender_id'] == self.user['id']
        bubble = BubbleMessage(
            msg_data['message'],
            is_me,
            msg_data['sender_name'],
            msg_data['sent_at'],
            file_path=msg_data.get('file_path') # DIPERBARUI: Teruskan file_path
        )
        bubble.msg_id = msg_data.get('id') # Simpan ID pesan di bubble

        container = QWidget()
        container_layout = QHBoxLayout()
        container_layout.setContentsMargins(0, 0, 0, 0)
        
        if is_me:
            container_layout.addStretch()
            container_layout.addWidget(bubble)
        else:
            container_layout.addWidget(bubble)
            container_layout.addStretch()
        
        container.setLayout(container_layout)
        self.messages_layout.insertWidget(self.messages_layout.count() - 1, container) # Masukkan sebelum 'stretch'
        
        if scroll_to_bottom: # Tambahkan kondisi ini
            QTimer.singleShot(100, self.scroll_to_bottom)

    def message_exists(self, msg_id):
        if not msg_id: return False
        for i in range(self.messages_layout.count() - 1): # Abaikan item 'stretch'
            container_widget = self.messages_layout.itemAt(i).widget()
            if container_widget:
                bubble_widget = None
                for j in range(container_widget.layout().count()):
                    item = container_widget.layout().itemAt(j)
                    if item and item.widget() and isinstance(item.widget(), BubbleMessage):
                        bubble_widget = item.widget()
                        break
                if bubble_widget and hasattr(bubble_widget, 'msg_id') and bubble_widget.msg_id == msg_id:
                    return True
        return False
    
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
                    message_content.get('id')
                )
        else: # Pesan untuk percakapan yang tidak aktif
            if item_found_in_sidebar:
                print(f"DEBUG: IT/handle_received_message - Pesan untuk percakapan TIDAK aktif {conv_id}. Menandai belum dibaca dan pindah ke atas.")
                self.mark_conversation_unread(conv_id, message_content.get("message")) # Ini akan set preview_label ke "🔵 New message"
            else:
                # Percakapan ini belum ada di list, mungkin percakapan baru yang dibuat oleh employee lain
                print(f"DEBUG: IT/handle_received_message - Pesan untuk percakapan BARU {conv_id} (tidak ada di list). Memuat ulang semua.")
                self.load_conversations() # Muat ulang semua untuk menampilkan percakapan baru ini
                self.unread_map[conv_id] = True # Tandai sebagai belum dibaca di map

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
    def add_message_to_ui(self, message, is_me, sender_name, sent_at, msg_id):
        bubble = BubbleMessage(message, is_me, sender_name, sent_at)
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
        print("DEBUG: ChatWindow - Menutup ChatWindow, menghentikan WebSocket thread.")
        if hasattr(self, 'ws_thread') and self.ws_thread.is_alive():
            self.ws_thread.stop()  # Panggil metode stop dari WebSocketThread yang baru
            self.ws_thread.join(timeout=2) # Tunggu thread selesai (opsional, dengan timeout)
        super().closeEvent(event)
        
class LoginWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setup_ui()
    
    def setup_ui(self):
        self.setWindowTitle("Login - IT Support Chat")
        self.setFixedSize(480, 650)
        
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
        form_layout.setContentsMargins(40, 40, 40, 40)
        form_layout.setSpacing(24)
        
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
        
        welcome_sub = QLabel("Please sign in to your account")
        welcome_sub.setStyleSheet("""
            QLabel {
                font-size: 14px;
                color: #7F8C8D;
                margin-bottom: 20px;
            }
        """)
        form_layout.addWidget(welcome_sub)
        
        # Username input
        username_label = QLabel("Username")
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
        self.username_input.setPlaceholderText("Enter your username")
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
        # password_label = QLabel("Password")
        # password_label.setStyleSheet("""
        #     QLabel {
        #         font-size: 14px;
        #         color: #2C3E50;
        #         font-weight: 500;
        #         margin-bottom: 5px;
        #     }
        # """)
        # form_layout.addWidget(password_label)
        
        # self.password_input = QLineEdit()
        # self.password_input.setPlaceholderText("Enter your password")
        # self.password_input.setEchoMode(QLineEdit.Password)
        # self.password_input.setStyleSheet("""
        #     QLineEdit {
        #         padding: 16px;
        #         font-size: 14px;
        #         border: 2px solid #E8ECEF;
        #         border-radius: 12px;
        #         background-color: #F8F9FA;
        #     }
        #     QLineEdit:focus {
        #         border: 2px solid #4A90E2;
        #         background-color: #FFFFFF;
        #     }
        # """)
        # form_layout.addWidget(self.password_input)
        
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
        footer_label = QLabel("Need help? Contact your system administrator")
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
        # password = self.password_input.text()
        
        if not username :
            self.show_error("Username and password are required")
            return
        
        data = {
            'username': username,
            # 'password': password
        }
        
        try:
            response = requests.post(f"{BASE_URL}/login", json=data)
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

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    # Set application icon if available
    # app.setWindowIcon(QIcon("icon.png"))
    
    login_window = LoginWindow()
    login_window.show()
    
    sys.exit(app.exec_())