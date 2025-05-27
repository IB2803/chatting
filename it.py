import sys
import os
import requests
import json
import threading
from websocket import create_connection

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QListWidget, QTextEdit,
    QScrollArea, QFrame, QSizePolicy, QListWidgetItem, QGraphicsDropShadowEffect
)
from PyQt5.QtCore import pyqtSignal, Qt, QTimer, QUrl
from PyQt5.QtGui import QColor, QFont, QPainter, QBrush, QPalette, QPixmap, QIcon

# Suppress font warnings
os.environ['QT_LOGGING_RULES'] = 'qt.qpa.fonts=false'

# BASE_URL = "http://localhost:5000"
BASE_URL = "http://192.168.128.125:5000"  # Ganti <IP_KANTOR> dengan IP server

class WebSocketThread(threading.Thread):
    def __init__(self, chat_window):
        super().__init__()
        self.chat_window = chat_window
        self.running = True
        
    def run(self):
        ws = create_connection("ws://192.168.128.125:5000")
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

class BubbleMessage(QLabel):
    def __init__(self, text, is_me, sender_name, time, parent=None):
        super().__init__(parent)
        self.is_me = is_me
        self.sender_name = sender_name
        self.time = time
        
        self.setWordWrap(True)
        self.setMargin(15)
        self.setTextFormat(Qt.RichText)
        
        # Create message bubble styling similar to the image
        if is_me:
            message_html = f"""
            <div style='font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; font-size: 15px; line-height: 1;'>
                <div style='color: #FFFFFF; margin-bottom: 8px;'>{text}</div>
                <div style='color: rgba(255,255,255,0.8); font-size: 11px; text-align: right; margin-top: 4px;'>
                    {time}
                </div>
            </div>
            """
            self.setStyleSheet("""
                BubbleMessage {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                        stop:0 #4A90E2, stop:1 #357ABD);
                    border-radius: 18px;
                    margin: 4px 60px 4px 4px;
                    max-width: 400px;
                }
            """)
        else:
            message_html = f"""
            <div style='font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; font-size: 15px; line-height: 1;'>

                <div style='color: #2C3E50; margin-bottom: 8px;'>{text}</div>
                <div style='color: #95A5A6; font-size: 11px; text-align: left; margin-top: 4px;'>
                    {time}
                </div>
            </div>
            """
            self.setStyleSheet("""
                BubbleMessage {
                    background-color: #FFFFFF;
                    border: 1px solid #E8ECEF;
                    border-radius: 18px;
                    margin: 4px 4px 4px 60px;
                    max-width: 400px;
                }
            """)
        
        self.setText(message_html)
        self.setAlignment(Qt.AlignLeft if not is_me else Qt.AlignRight)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        
        # Add subtle shadow
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(8)
        shadow.setColor(QColor(0, 0, 0, 20))
        shadow.setOffset(0, 2)
        self.setGraphicsEffect(shadow)

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
                border-radius: 24px;
                color: white;
                font-weight: bold;
                font-size: 18px;
            }
        """)
        
        if user_role == 'employee':
            name = conv.get('tech_name', 'Tech')
            avatar.setText(name[0].upper())
        else:
            name = conv.get('employee_name', 'User')
            avatar.setText(name[0].upper())
        
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
        
        name_status_layout.addStretch()
        info_layout.addLayout(name_status_layout)
        
        # Last message preview (if available)
        preview_label = QLabel("Click to start conversation")
        preview_label.setStyleSheet("""
            QLabel {
                color: #7F8C8D;
                font-size: 13px;
            }
        """)
        info_layout.addWidget(preview_label)
        
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
        self.setup_ui()
        self.load_conversations()
        
        # Setup WebSocket
        self.receive_message_signal.connect(self.handle_received_message)
        self.ws_thread = WebSocketThread(self)
        self.ws_thread.start()
        
        # Timer untuk refresh
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_messages)
        self.timer.start(3000)
    
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
                background-color: #EBF3FF;
                border-left: 3px solid #4A90E2;
            }
        """)
        self.conversation_list.itemClicked.connect(self.select_conversation)
        sidebar_layout.addWidget(self.conversation_list)
        
        # New chat button (for employees)
        if self.user['role'] == 'employee':
            button_widget = QWidget()
            button_widget.setFixedHeight(80)
            button_widget.setStyleSheet("background-color: #FFFFFF; border-top: 1px solid #E8ECEF;")
            
            button_layout = QHBoxLayout()
            button_layout.setContentsMargins(20, 20, 20, 20)
            
            self.new_chat_btn = QPushButton("✨ New Ticket")
            self.new_chat_btn.setStyleSheet("""
                QPushButton {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                        stop:0 #4A90E2, stop:1 #357ABD);
                    color: white;
                    border: none;
                    padding: 12px 24px;
                    border-radius: 20px;
                    font-size: 14px;
                    font-weight: 600;
                }
                QPushButton:hover {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                        stop:0 #357ABD, stop:1 #2E6DA4);
                }
                QPushButton:pressed {
                    background: #2E6DA4;
                }
            """)
            self.new_chat_btn.clicked.connect(self.create_new_conversation)
            button_layout.addWidget(self.new_chat_btn)
            button_widget.setLayout(button_layout)
            sidebar_layout.addWidget(button_widget)
        
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
        input_area.setStyleSheet("""
            QWidget {
                background-color: #FFFFFF;
                border-top: 1px solid #E8ECEF;
            }
        """)
        
        input_layout = QHBoxLayout()
        input_layout.setContentsMargins(24, 16, 24, 16)
        input_layout.setSpacing(12)
        
        # Attach button
        attach_btn = QPushButton("📎")
        attach_btn.setFixedSize(40, 40)
        attach_btn.setStyleSheet("""
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
        input_layout.addWidget(attach_btn)
        
        # Message input
        self.message_input = QTextEdit()
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
    
    def load_conversations(self):
        response = requests.get(f"{BASE_URL}/get_conversations/{self.user['id']}")
        if response.status_code == 200:
            conversations = response.json()
            self.conversation_list.clear()
            
            # Urutkan conversations berdasarkan waktu pesan terbaru (descending)
            conversations.sort(key=lambda x: x.get('last_message_time', ''), reverse=True)
            self.conversation_list.clear()

            for conv in conversations:
            # for conv in sorted(conversations, key=lambda x: x['id'], reverse=True):
                item = QListWidgetItem()
                item.setData(Qt.UserRole, conv['id'])
                
                conv_widget = ConversationItem(conv, self.user['role'])
                item.setSizeHint(conv_widget.sizeHint())
                
                self.conversation_list.addItem(item)
                self.conversation_list.setItemWidget(item, conv_widget)
                
                            # Re-select current conversation
                if conv['id'] == self.current_conversation:
                    self.conversation_list.setCurrentItem(item)
    
    def select_conversation(self, item):
        conversation_id = item.data(Qt.UserRole)
        self.current_conversation = conversation_id
        
        # Update chat header
        conv_widget = self.conversation_list.itemWidget(item)
        conv_data = conv_widget.conversation_data
        
        if self.user['role'] == 'employee':
            name = conv_data.get('tech_name', 'Technician')
        else:
            name = conv_data.get('employee_name', 'Employee')
        
        self.chat_name.setText(name)
        self.chat_status.setText("🟢 Active now" if conv_data.get('status') != 'closed' else "⚫ Closed")
        self.chat_avatar.setText(name[0].upper())
        
        self.load_messages(conversation_id)
    
    def load_messages(self, conversation_id):
        response = requests.get(f"{BASE_URL}/get_messages/{conversation_id}")
        if response.status_code == 200:
            messages = response.json()
            
            # Clear existing messages
            while self.messages_layout.count():
                item = self.messages_layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
            
            # Add new messages
            for msg in messages:
                is_me = msg['sender_id'] == self.user['id']
                bubble = BubbleMessage(
                    msg['message'], 
                    is_me,
                    msg['sender_name'],
                    msg['sent_at']
                )
                
                # Create container for proper alignment
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
                self.messages_layout.addWidget(container)
            
            # Scroll to bottom
            QTimer.singleShot(100, self.scroll_to_bottom)
    
    def scroll_to_bottom(self):
        scrollbar = self.scroll_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def refresh_messages(self):
        if self.current_conversation:
            self.load_messages(self.current_conversation)
            

            
    # def handle_received_message(self, data):
    #     if data['conversation_id'] == self.current_conversation:
    #         # Cek apakah message sudah ada di UI
    #         if not self.message_exists(data['message']['id']):
    #             self.add_message_to_ui(data['message'])
    
    def handle_received_message(self, data):
        conv_id = data['conversation_id']
        
        # Jika percakapan sedang dibuka, tampilkan pesannya
        if conv_id == self.current_conversation:
            if not self.message_exists(data['message']['id']):
                self.add_message_to_ui(data['message'])
        self.load_conversations()
        
        # Pindahkan percakapan ke atas
        # self.move_conversation_to_top(conv_id)
        
        
    def move_conversation_to_top(self, conversation_id):
        for i in range(self.conversation_list.count()):
            item = self.conversation_list.item(i)
            if item.data(Qt.UserRole) == conversation_id:
                widget = self.conversation_list.itemWidget(item)

                # Hapus item dari posisinya sekarang
                self.conversation_list.takeItem(i)

                # Tambah ulang ke paling atas
                self.conversation_list.insertItem(0, item)
                self.conversation_list.setItemWidget(item, widget)
                break

            
        
                
    def message_exists(self, msg_id):
        for i in range(self.messages_layout.count()):
            widget = self.messages_layout.itemAt(i).widget()
            if hasattr(widget, 'msg_id') and widget.msg_id == msg_id:
                return True
        return False
    
    def add_message_to_ui(self, message, is_me, sender_name, sent_at):
        bubble = BubbleMessage(message, is_me, sender_name, sent_at)
        
        # Create container for proper alignment
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
        self.messages_layout.addWidget(container)
        
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
        if response.status_code == 200:
            self.message_input.clear()
    
    def create_new_conversation(self):
        data = {
            'employee_id': self.user['id'],
            'technician_id': None
        }
        
        response = requests.post(f"{BASE_URL}/create_conversation", json=data)
        if response.status_code == 200:
            self.load_conversations()
    
    def closeEvent(self, event):
        self.ws_thread.running = False
        self.ws_thread.join()
        super().closeEvent(event)

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

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    # Set application icon if available
    # app.setWindowIcon(QIcon("icon.png"))
    
    login_window = LoginWindow()
    login_window.show()
    
    sys.exit(app.exec_())