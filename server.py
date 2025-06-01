from flask import Flask, request, jsonify
from flask_mysqldb import MySQL
from flask_socketio import SocketIO, emit
from flask_cors import CORS
import hashlib
from datetime import datetime
import os
from werkzeug.utils import secure_filename
from flask import Flask, request, jsonify, send_from_directory

IP = "192.168.56.1"

app = Flask(__name__)
# CORS(app)
CORS(app, resources={
    r"/*": {
        "origins": ["http://localhost:5000", f"http://{IP}:5000"]
    }
})
socketio = SocketIO(app, cors_allowed_origins="*")

# MySQL configuration
app.config['MYSQL_HOST'] = IP
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = ''
app.config['MYSQL_DB'] = 'it_support_chat'

mysql = MySQL(app)

# Helper functions
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data['username']
    # password = hash_password(data['password'])
    
    cur = mysql.connection.cursor()
    cur.execute("SELECT id, username, role, full_name FROM users WHERE username = %s AND role = 'employee'", 
               (username,))
    user = cur.fetchone()
    cur.close()
    
    if user:
        return jsonify({
            'success': True,
            'user': {
                'id': user[0],
                'username': user[1],
                'role': user[2],
                'full_name': user[3]
            }
        })
    return jsonify({'success': False, 'message': 'Invalid credentials'})

@app.route('/login_it', methods=['POST'])
def login_it():
    data = request.get_json()
    username = data['username']
    password = hash_password(data['password'])
    
    cur = mysql.connection.cursor()
    cur.execute("SELECT id, username, role, full_name FROM users WHERE username = %s AND password = %s", 
               (username, password))
    user = cur.fetchone()
    cur.close()
    
    if user:
        return jsonify({
            'success': True,
            'user': {
                'id': user[0],
                'username': user[1],
                'role': user[2],
                'full_name': user[3]
            }
        })
    return jsonify({'success': False, 'message': 'Invalid credentials'})

@app.route('/get_conversations/<int:user_id>')
def get_conversations(user_id):
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT c.id, c.status, 
               e.full_name as employee_name, 
               t.full_name as tech_name
        FROM conversations c
        JOIN users e ON c.employee_id = e.id
        LEFT JOIN users t ON c.technician_id = t.id
        WHERE c.employee_id = %s OR c.technician_id = %s
        ORDER BY c.last_updated DESC

    """, (user_id, user_id))
    
    conversations = []
    for conv in cur.fetchall():
        conversations.append({
            'id': conv[0],
            'status': conv[1],
            'employee_name': conv[2],
            'tech_name': conv[3] if conv[3] else 'Belum ditugaskan'
        })
    cur.close()
    return jsonify(conversations)

@app.route('/get_messages/<int:conversation_id>')
def get_messages(conversation_id):
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT m.id, m.sender_id, u.full_name, m.message, m.sent_at, m.read_at, m.file_path
        FROM messages m
        JOIN users u ON m.sender_id = u.id
        WHERE m.conversation_id = %s
        ORDER BY m.sent_at
    """, (conversation_id,))
    
    messages = []
    for msg in cur.fetchall():
        messages.append({
            'id': msg[0],
            'sender_id': msg[1],
            'sender_name': msg[2],
            'message': msg[3],
            'sent_at': msg[4].strftime('%Y-%m-%d %H:%M:%S'),
            'read_at': msg[5].strftime('%Y-%m-%d %H:%M:%S') if msg[5] else None,
            'file_path': msg[6]  # This correctly includes file_path
        })
    cur.close()
    return jsonify(messages)

@app.route('/create_conversation', methods=['POST'])
def create_conversation():
    data = request.get_json()
    employee_id = data['employee_id']
    
    # Cari teknisi yang tersedia
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT id FROM users 
        WHERE role = 'technician' 
        ORDER BY RAND() LIMIT 1
    """)
    tech = cur.fetchone()
    technician_id = tech[0] if tech else None
    
    # Buat percakapan baru
    cur.execute("""
        INSERT INTO conversations (employee_id, technician_id)
        VALUES (%s, %s)
    """, (employee_id, technician_id))
    mysql.connection.commit()
    
    conversation_id = cur.lastrowid
    cur.close()
    
    return jsonify({
        'success': True,
        'conversation_id': conversation_id,
        'technician_id': technician_id
    })

# Endpoint untuk mengirim pesan
@app.route('/send_message', methods=['POST'])
def send_message():
    data = request.get_json()
    conversation_id = data['conversation_id']
    sender_id = data['sender_id']
    message = data['message']
    
    cur = mysql.connection.cursor()
    cur.execute("""
        INSERT INTO messages (conversation_id, sender_id, message)
        VALUES (%s, %s, %s)
    """, (conversation_id, sender_id, message))
    cur.execute("UPDATE conversations SET last_updated = NOW() WHERE id = %s", (conversation_id,))

    mysql.connection.commit()
    
    # Dapatkan detail pesan yang baru dikirim
    cur.execute("""
        SELECT m.id, m.sender_id, u.full_name, m.message, m.sent_at
        FROM messages m
        JOIN users u ON m.sender_id = u.id
        WHERE m.id = %s
    """, (cur.lastrowid,))
    
    message_data = cur.fetchone()
    cur.close()
    
    # Kirim notifikasi real-time via Socket.IO
    socketio.emit('new_message', {
        'conversation_id': conversation_id,
        'message': {
            'id': message_data[0],
            'sender_id': message_data[1],
            'sender_name': message_data[2],
            'message': message_data[3],
            'sent_at': message_data[4].strftime('%Y-%m-%d %H:%M:%S')
        }
    }, broadcast=True)
    
    return jsonify({'success': True})

# Konfigurasi folder upload
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf', 'doc', 'docx', 'mp4', 'mov', 'avi', 'zip', 'rar', 'mkv'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/upload_file', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': 'No file part'})
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'message': 'No selected file'})
    
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        # Simpan informasi file ke database
        conversation_id = request.form.get('conversation_id')
        sender_id = request.form.get('sender_id')
        
        cur = mysql.connection.cursor()
        cur.execute("""
            INSERT INTO messages (conversation_id, sender_id, message, file_path)
            VALUES (%s, %s, %s, %s)
        """, (conversation_id, sender_id, f"[File: {filename}]", filepath))
        
        cur.execute("UPDATE conversations SET last_updated = NOW() WHERE id = %s", (conversation_id,))
        mysql.connection.commit()
        
        # Dapatkan detail pesan yang baru dikirim
        cur.execute("""
            SELECT m.id, m.sender_id, u.full_name, m.message, m.sent_at, m.file_path
            FROM messages m
            JOIN users u ON m.sender_id = u.id
            WHERE m.id = %s
        """, (cur.lastrowid,))
        
        message_data = cur.fetchone()
        cur.close()
        
        # Kirim notifikasi real-time via Socket.IO
        socketio.emit('new_message', {
            'conversation_id': conversation_id,
            'message': {
                'id': message_data[0],
                'sender_id': message_data[1],
                'sender_name': message_data[2],
                'message': message_data[3],
                'file_path': message_data[5],
                'sent_at': message_data[4].strftime('%Y-%m-%d %H:%M:%S')
            }
        }, broadcast=True)
        
        return jsonify({'success': True, 'file_path': filepath})
    
    return jsonify({'success': False, 'message': 'File type not allowed'})

# Tambahkan endpoint baru untuk menyajikan file dari folder 'uploads'
@app.route('/uploads/<path:filename>')
def uploaded_file_serve(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

if __name__ == '__main__':
    # Pastikan UPLOAD_FOLDER sudah didefinisikan di konfigurasi app
    if not os.path.exists(app.config['UPLOAD_FOLDER']):
        os.makedirs(app.config['UPLOAD_FOLDER'])
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)