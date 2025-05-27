from flask import Flask, request, jsonify
from flask_mysqldb import MySQL
from flask_socketio import SocketIO, emit
from flask_cors import CORS
import hashlib
from datetime import datetime

app = Flask(__name__)
CORS(app, resources={
    r"/*": {
        "origins": ["http://localhost:5000", "http://192.168.128.125:5000"]
    }
})
socketio = SocketIO(app, cors_allowed_origins="*")

# MySQL configuration
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
    
    # Query untuk mendapatkan conversations dengan unread count
    cur.execute("""
        SELECT c.id, c.status, 
               e.full_name as employee_name, 
               t.full_name as tech_name,
               c.last_updated,
               (SELECT COUNT(*) 
                FROM messages m 
                WHERE m.conversation_id = c.id 
                AND m.sender_id != %s 
                AND m.is_read = FALSE) as unread_count,
               (SELECT m.message 
                FROM messages m 
                WHERE m.conversation_id = c.id 
                ORDER BY m.sent_at DESC 
                LIMIT 1) as last_message,
               (SELECT m.sent_at 
                FROM messages m 
                WHERE m.conversation_id = c.id 
                ORDER BY m.sent_at DESC 
                LIMIT 1) as last_message_time
        FROM conversations c
        JOIN users e ON c.employee_id = e.id
        LEFT JOIN users t ON c.technician_id = t.id
        WHERE c.employee_id = %s OR c.technician_id = %s
        ORDER BY c.last_updated DESC
    """, (user_id, user_id, user_id))
    
    conversations = []
    for conv in cur.fetchall():
        conversations.append({
            'id': conv[0],
            'status': conv[1],
            'employee_name': conv[2],
            'tech_name': conv[3] if conv[3] else 'Belum ditugaskan',
            'last_updated': conv[4].strftime('%Y-%m-%d %H:%M:%S') if conv[4] else None,
            'unread_count': conv[5],
            'last_message': conv[6] if conv[6] else 'No messages yet',
            'last_message_time': conv[7].strftime('%Y-%m-%d %H:%M:%S') if conv[7] else None
        })
    cur.close()
    return jsonify(conversations)

@app.route('/get_messages/<int:conversation_id>')
def get_messages(conversation_id):
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT m.id, m.sender_id, u.full_name, m.message, m.sent_at, m.read_at, m.is_read
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
            'is_read': bool(msg[6])
        })
    cur.close()
    return jsonify(messages)

@app.route('/mark_messages_read', methods=['POST'])
def mark_messages_read():
    """Mark all messages in a conversation as read by the current user"""
    data = request.get_json()
    conversation_id = data['conversation_id']
    user_id = data['user_id']
    
    cur = mysql.connection.cursor()
    
    # Mark messages as read (hanya untuk pesan yang bukan dikirim oleh user ini)
    cur.execute("""
        UPDATE messages 
        SET is_read = TRUE, read_at = NOW() 
        WHERE conversation_id = %s 
        AND sender_id != %s 
        AND is_read = FALSE
    """, (conversation_id, user_id))
    
    mysql.connection.commit()
    cur.close()
    
    # Emit event untuk update unread count di semua client
    socketio.emit('messages_read', {
        'conversation_id': conversation_id,
        'user_id': user_id
    }, broadcast=True)
    
    return jsonify({'success': True})

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

@app.route('/send_message', methods=['POST'])
def send_message():
    data = request.get_json()
    conversation_id = data['conversation_id']
    sender_id = data['sender_id']
    message = data['message']
    
    cur = mysql.connection.cursor()
    
    # Insert message dengan is_read = FALSE (akan dibaca nanti)
    cur.execute("""
        INSERT INTO messages (conversation_id, sender_id, message, is_read)
        VALUES (%s, %s, %s, FALSE)
    """, (conversation_id, sender_id, message))
    
    # Update conversation last_updated
    cur.execute("UPDATE conversations SET last_updated = NOW() WHERE id = %s", (conversation_id,))
    mysql.connection.commit()
    
    # Dapatkan detail pesan yang baru dikirim
    message_id = cur.lastrowid
    cur.execute("""
        SELECT m.id, m.sender_id, u.full_name, m.message, m.sent_at
        FROM messages m
        JOIN users u ON m.sender_id = u.id
        WHERE m.id = %s
    """, (message_id,))
    
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
            'sent_at': message_data[4].strftime('%Y-%m-%d %H:%M:%S'),
            'is_read': False
        }
    }, broadcast=True)
    
    return jsonify({'success': True})

if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)