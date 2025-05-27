import sys
from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QLineEdit, QPushButton,
    QVBoxLayout, QMessageBox, QTextEdit, QHBoxLayout, QListWidget,
    QListWidgetItem
)
from PyQt5.QtCore import Qt, QTimer
import mysql.connector
import datetime

# Fungsi koneksi ke database
def connect_db():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="",
        database="chat_db"
    )

# Form Login
class LoginWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Login Chat")
        self.resize(300, 200)

        layout = QVBoxLayout()

        self.label_user = QLabel("Username:")
        self.input_user = QLineEdit()
        layout.addWidget(self.label_user)
        layout.addWidget(self.input_user)

        self.label_pass = QLabel("Password:")
        self.input_pass = QLineEdit()
        self.input_pass.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.label_pass)
        layout.addWidget(self.input_pass)

        self.btn_login = QPushButton("Login")
        self.btn_login.clicked.connect(self.login)
        layout.addWidget(self.btn_login)
        
        

        self.setLayout(layout)

    def login(self):
        username = self.input_user.text()
        password = self.input_pass.text()
        print("Username:", username)
        print("Password:", password)

        if not username or not password:
            QMessageBox.warning(self, "Error", "Username & Password wajib diisi!")
            return

        try:
            print("Coba koneksi DB...")
            conn = connect_db()
            cursor = conn.cursor()
            query = "SELECT id, role FROM users WHERE username=%s AND password=%s"
            cursor.execute(query, (username, password))
            result = cursor.fetchone()
            print("Result query:", result)
        except Exception as e:
            print("Error saat login:", e)
            return

        if result:
            user_id, role = result
            print("Login berhasil:", username, role)
            self.hide()
            self.chat_window = ChatWindow(user_id, username, role)
            self.chat_window.show()
        else:
            print("Login gagal - result None")
            QMessageBox.critical(self, "Error", "Username / Password salah!")

        cursor.close()
        conn.close()


# Halaman Chat
class ChatWindow(QWidget):
    def __init__(self, user_id, username, role):
        super().__init__()
        print("ChatWindow dibuat!") 
        self.user_id = user_id
        self.username = username
        self.role = role

        self.setWindowTitle(f"Chat - {self.username} ({self.role})")
        self.resize(400, 600)

        # Layout utama
        layout = QVBoxLayout()

        # Area chat
        self.chat_area = QListWidget()
        layout.addWidget(self.chat_area)

        # Input + tombol kirim
        input_layout = QHBoxLayout()
        self.input_message = QLineEdit()
        self.input_message.setPlaceholderText("Ketik pesan...")
        self.btn_send = QPushButton("Kirim")
        self.btn_send.clicked.connect(self.send_message)
        input_layout.addWidget(self.input_message)
        input_layout.addWidget(self.btn_send)

        layout.addLayout(input_layout)
        self.setLayout(layout)

        # Timer refresh chat (polling)
        self.timer = QTimer()
        self.timer.timeout.connect(self.load_messages)
        self.timer.start(2000)  # refresh tiap 2 detik

        self.load_messages()

    def send_message(self):
        message = self.input_message.text()
        if not message:
            return

        # Untuk testing, biar chatting ke 1 orang saja (misal IT teknisi id 2)
        # Nanti logicnya bisa dibuat lebih kompleks (pilih receiver, dll)
        receiver_id = 1 if self.role == "teknisi" else 2

        conn = connect_db()
        cursor = conn.cursor()
        query = "INSERT INTO messages (sender_id, receiver_id, message) VALUES (%s, %s, %s)"
        cursor.execute(query, (self.user_id, receiver_id, message))
        conn.commit()
        cursor.close()
        conn.close()

        self.input_message.clear()
        self.load_messages()

    def load_messages(self):
        conn = connect_db()
        cursor = conn.cursor()
        # Ambil semua pesan antara user & receiver
        query = """
            SELECT u.username, m.message, m.timestamp, m.sender_id
            FROM messages m
            JOIN users u ON m.sender_id = u.id
            WHERE (m.sender_id=%s AND m.receiver_id=%s)
               OR (m.sender_id=%s AND m.receiver_id=%s)
            ORDER BY m.timestamp
        """
        receiver_id = 1 if self.role == "teknisi" else 2
        cursor.execute(query, (self.user_id, receiver_id, receiver_id, self.user_id))
        results = cursor.fetchall()

        self.chat_area.clear()
        for username, message, timestamp, sender_id in results:
            bubble = f"{username}: {message}"
            item = QListWidgetItem(bubble)
            # Bubble style
            if sender_id == self.user_id:
                item.setTextAlignment(Qt.AlignRight)
            else:
                item.setTextAlignment(Qt.AlignLeft)
            self.chat_area.addItem(item)

        cursor.close()
        conn.close()
        

if __name__ == "__main__":
    print("Aplikasi mulai...") 
    app = QApplication(sys.argv)
    # Simpan window di variabel global (biar nggak kehapus!)
    login_window = LoginWindow()
    login_window.show()
    sys.exit(app.exec_())

