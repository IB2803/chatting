from flask import Flask, request, jsonify
from flask_mysqldb import MySQL
from flask_socketio import SocketIO, emit
from flask_cors import CORS
import hashlib
from datetime import datetime

app = Flask(__name__)
# CORS(app)
CORS(app, resources={
    r"/*": {
        "origins": ["http://localhost:5000", "http://192.168.128.125:5000"]
    }
})
socketio = SocketIO(app, cors_allowed_origins="*")

# MySQL configuration
# app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_HOST'] = '192.168.128.125'
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
        SELECT m.id, m.sender_id, u.full_name, m.message, m.sent_at, m.read_at
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
            'read_at': msg[5].strftime('%Y-%m-%d %H:%M:%S') if msg[5] else None
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

# Socket.IO Events
# @socketio.on('send_message')
# def handle_send_message(data):
#     cur = mysql.connection.cursor()
#     cur.execute("""
#         INSERT INTO messages (conversation_id, sender_id, message)
#         VALUES (%s, %s, %s)
#     """, (data['conversation_id'], data['sender_id'], data['message']))
#     mysql.connection.commit()
    
#     cur.execute("SELECT * FROM messages WHERE id = %s", (cur.lastrowid,))
#     message = cur.fetchone()
#     cur.close()
    
#     emit('receive_message', {
#         'conversation_id': data['conversation_id'],
#         'message': {
#             'id': message[0],
#             'sender_id': message[2],
#             'message': message[3],
#             'sent_at': message[4].strftime('%Y-%m-%d %H:%M:%S')
#         }
#     }, broadcast=True)

if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)