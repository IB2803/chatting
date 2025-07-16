import sys
import json
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QMessageBox

CONFIG_FILE = 'config.json'

class ConfigEditor(QWidget):
    def __init__(self):
        super().__init__()
        self.init_ui()
        self.load_current_config()

    def init_ui(self):
        self.setWindowTitle('Pengatur Konfigurasi Server')
        self.setFixedSize(400, 200) # Sedikit lebih tinggi
        layout = QVBoxLayout(self)

        # Input untuk IP
        layout.addWidget(QLabel('Alamat IP Server:'))
        self.ip_input = QLineEdit()
        self.ip_input.setStyleSheet("padding: 5px; font-size: 14px;")
        layout.addWidget(self.ip_input)

        # Input untuk Port
        layout.addWidget(QLabel('Port Server:'))
        self.port_input = QLineEdit()
        self.port_input.setStyleSheet("padding: 5px; font-size: 14px;")
        layout.addWidget(self.port_input)

        # Tombol Simpan
        self.save_button = QPushButton('Simpan Konfigurasi')
        self.save_button.setStyleSheet("padding: 8px; font-size: 14px; background-color: #28a745; color: white;")
        self.save_button.clicked.connect(self.save_config)
        layout.addWidget(self.save_button)

    def load_current_config(self):
        """Memuat IP dan Port saat ini dari config.json."""
        try:
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
                self.ip_input.setText(config.get('ip_address', ''))
                self.port_input.setText(config.get('port', ''))
        except FileNotFoundError:
            QMessageBox.warning(self, 'Error', f"File '{CONFIG_FILE}' tidak ditemukan.")
            self.save_button.setEnabled(False)

    def save_config(self):
        """Menyimpan IP dan Port baru ke config.json."""
        new_ip = self.ip_input.text().strip()
        new_port = self.port_input.text().strip()

        if not new_ip or not new_port:
            QMessageBox.warning(self, 'Input Kosong', 'Alamat IP dan Port tidak boleh kosong.')
            return

        try:
            # Baca data lama untuk mempertahankan struktur lain jika ada
            with open(CONFIG_FILE, 'r') as f:
                config_data = json.load(f)
            
            # Update dengan data baru
            config_data['ip_address'] = new_ip
            config_data['port'] = new_port
            
            # Tulis kembali ke file
            with open(CONFIG_FILE, 'w') as f:
                json.dump(config_data, f, indent=4)
            
            QMessageBox.information(self, 'Sukses', f'Konfigurasi berhasil disimpan!')
            self.close()

        except Exception as e:
            QMessageBox.critical(self, 'Error', f'Gagal menyimpan file konfigurasi: {e}')

if __name__ == '__main__':
    app = QApplication(sys.argv)
    editor = ConfigEditor()
    editor.show()
    sys.exit(app.exec_())