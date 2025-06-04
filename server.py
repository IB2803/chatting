import eventlet
eventlet.monkey_patch()  # Patch untuk mendukung Socket.IO dengan Flask

from flask import Flask, request, jsonify
from flask_mysqldb import MySQL
from flask_socketio import SocketIO
from flask_cors import CORS
import hashlib

from datetime import datetime
import os
from werkzeug.utils import secure_filename
from flask import Flask, request, jsonify, send_from_directory

IP = "192.168.45.171"
# IP = "192.168.1.7"
PORT = "5000"



app = Flask(__name__)
CORS(app, resources={
    r"/*": {
        "origins": [f"http://localhost:{PORT}", f"http://{IP}:{PORT}"]
    }
})
socketio = SocketIO(app, cors_allowed_origins="*")

# MySQL configuration
app.config['MYSQL_HOST'] = IP
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = ''
app.config['MYSQL_DB'] = 'it_support_chat'

mysql = MySQL(app)

# Helper function
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

@app.route('/get_users_by_role/<string:role_name>', methods=['GET'])
def get_users_by_role(role_name):
    # Untuk CreateConversationDialog, client memanggil untuk 'employee' dan 'technician'.
    # Permintaan untuk 'technician' dari client sekarang berarti "berikan saya daftar staf support yang bisa ditugaskan".
    
    # Definisikan role_name apa saja yang valid diterima di path URL endpoint ini
    valid_roles_in_path = ['employee', 'technician'] 
    # Jika Anda juga ingin bisa memanggil /get_users_by_role/ga secara terpisah untuk daftar GA saja, tambahkan 'ga' di sini.
    # Namun untuk kasus dialog, client hanya akan meminta 'technician' (untuk support) dan 'employee'.

    if role_name not in valid_roles_in_path:
        return jsonify({'success': False, 'message': f'Listing untuk role "{role_name}" tidak valid atau tidak didukung.'}), 400

    cur = mysql.connection.cursor()
    try:
        sql_query = ""
        sql_params = []

        if role_name == 'technician': 
            # Jika client meminta daftar 'technician', server memberikan 'technician' DAN 'ga'
            sql_query = "SELECT id, full_name FROM users WHERE role = %s OR role = %s ORDER BY full_name ASC"
            sql_params = ['technician', 'ga']
        elif role_name == 'employee':
            sql_query = "SELECT id, full_name FROM users WHERE role = %s ORDER BY full_name ASC"
            sql_params = [role_name] # role_name akan berisi 'employee'
        # else:
            # Kasus lain seharusnya sudah ditangani oleh validasi 'valid_roles_in_path' di atas.
            # Jika Anda menambahkan 'ga' ke 'valid_roles_in_path' untuk panggilan langsung /get_users_by_role/ga:
            # sql_query = "SELECT id, full_name FROM users WHERE role = %s ORDER BY full_name ASC"
            # sql_params = ['ga']


        if not sql_query: # Fallback jika logika di atas tidak menghasilkan query (seharusnya tidak terjadi)
            cur.close()
            return jsonify({'success': False, 'message': 'Internal server error: Role tidak terdefinisi untuk query.'}), 500

        cur.execute(sql_query, tuple(sql_params))
        users = [{'id': row[0], 'full_name': row[1]} for row in cur.fetchall()]
        cur.close()
        return jsonify({'success': True, 'users': users})
    except Exception as e:
        cur.close()
        # Ini akan mencetak error Python asli ke konsol server, sangat berguna untuk debugging!
        print(f"SERVER_ERROR di /get_users_by_role untuk role '{role_name}': {e}") 
        return jsonify({'success': False, 'message': f'Gagal mengambil pengguna: {str(e)}'}), 500
# @app.route('/get_users_by_role/<string:role_name>', methods=['GET'])
# def get_users_by_role(role_name):
#     # Isi fungsi seperti yang sudah kita diskusikan sebelumnya
#     if role_name not in ['employee', 'technician', 'ga']:
#         return jsonify({'success': False, 'message': 'Invalid role specified'}), 400

#     cur = mysql.connection.cursor()
#     try:
#         query_sql = "SELECT id, full_name FROM users WHERE "
#         params = []

#         if role_name == 'technician':
#             # Jika client meminta 'technician', berikan daftar semua yang bisa jadi support
#             query_sql += "(role = %s )"
#             params.extend('technician')
#         elif role_name == 'employee':
#             query_sql += "role = %s"
#             params.append('employee')
#         # Jika Anda menambahkan 'ga' ke allowed_roles_for_path dan ingin endpoint khusus untuk list GA:
#         elif role_name == 'ga':
#             query_sql += "role = %s"
#             params.append('ga')
#         else:
#             # Ini seharusnya tidak terjadi jika validasi di atas sudah benar
#             cur.close()
#             return jsonify({'success': False, 'message': 'Internal server error: Unhandled role for query construction.'}), 500

#         query_sql += " ORDER BY full_name ASC"
#         cur.execute(query_sql, tuple(params))
#         users = [{'id': row[0], 'full_name': row[1]} for row in cur.fetchall()]
#         cur.close()
#         return jsonify({'success': True, 'users': users})
#     except Exception as e:
#         cur.close()
#         print(f"Error fetching users by role (custom logic) {role_name}: {e}")
#         return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/admin_create_conversation', methods=['POST'])
def admin_create_conversation():
    data = request.get_json()
    employee_id = data.get('employee_id')
    technician_id = data.get('technician_id')
    ga_id = data.get('ga_id')  # Jika diperlukan, bisa ditambahkan validasi untuk GA

    if not employee_id or not technician_id:
        return jsonify({'success': False, 'message': 'Employee ID and Technician ID are required'}), 400

    cur = mysql.connection.cursor()
    try:
        # Validasi employee
        cur.execute("SELECT role FROM users WHERE id = %s", (employee_id,))
        employee_user = cur.fetchone()
        if not employee_user or employee_user[0] != 'employee': #
            cur.close()
            return jsonify({'success': False, 'message': 'Invalid Employee ID or user is not an employee'}), 400

        # Validasi technician
        cur.execute("SELECT role FROM users WHERE id = %s", (technician_id,))
        technician_user = cur.fetchone()
        if not technician_user or technician_user[0] not in ['technician', 'ga']: #
            cur.close()
            return jsonify({'success': False, 'message': 'Invalid Technician/GA ID or user is not a technician or GA support role'}), 400

        # Opsional: Cek apakah sudah ada percakapan terbuka antara keduanya
        cur.execute("SELECT id FROM conversations WHERE employee_id = %s AND technician_id = %s AND status = 'open'", (employee_id, technician_id)) #
        if cur.fetchone():
            cur.close()
            return jsonify({'success': False, 'message': 'An open conversation already exists between these users'}), 409 # 409 Conflict

        # Insert percakapan baru
        cur.execute("""
            INSERT INTO conversations (employee_id, technician_id, status, last_updated) 
            VALUES (%s, %s, %s, NOW())
        """, (employee_id, technician_id, 'open')) #
        mysql.connection.commit()
        conversation_id = cur.lastrowid

        # Untuk memicu pembaruan di klien, idealnya server akan emit event Socket.IO
        # ke employee_id dan technician_id yang terlibat.
        # Untuk saat ini, klien akan melakukan refresh manual (load_conversations).
        # Anda bisa menambahkan pembuatan pesan sistem awal di sini jika diperlukan.
        
        # Ambil detail percakapan yang baru dibuat untuk dikirim kembali jika perlu (misal, untuk langsung dibuka)
        # atau cukup konfirmasi sukses.
        cur.execute("""
            SELECT 
                c.id, 
                c.status, 
                e.full_name as employee_name, 
                t.full_name as tech_name,
                c.last_updated,
                NULL as last_message_preview,  -- Pesan awal bisa null
                c.last_updated as last_message_time 
            FROM conversations c
            JOIN users e ON c.employee_id = e.id
            LEFT JOIN users t ON c.technician_id = t.id
            WHERE c.id = %s
        """, (conversation_id,))
        new_conv_data_row = cur.fetchone()
        cur.close()

        if new_conv_data_row:
            new_conv_details = {
                'id': new_conv_data_row[0],
                'status': new_conv_data_row[1],
                'employee_name': new_conv_data_row[2],
                'tech_name': new_conv_data_row[3],
                'last_updated': new_conv_data_row[4].strftime('%Y-%m-%d %H:%M:%S'),
                'last_message_preview': new_conv_data_row[5] if new_conv_data_row[5] else "Conversation started.",
                'last_message_time': new_conv_data_row[6].strftime('%Y-%m-%d %H:%M:%S')
            }
            # Emit event ke semua IT client agar list mereka terupdate, atau minimal ke pembuatnya
            socketio.emit('conversation_created', {'conversation_data': new_conv_details}, broadcast=True) # Contoh emit
            return jsonify({'success': True, 'conversation_id': conversation_id, 'message': 'Conversation created successfully', 'conversation_details': new_conv_details})
        else:
            return jsonify({'success': True, 'conversation_id': conversation_id, 'message': 'Conversation created, but failed to fetch details.'})


    except Exception as e:
        mysql.connection.rollback()
        cur.close()
        print(f"Error in admin_create_conversation: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data['username']

    cur = mysql.connection.cursor()
    cur.execute("SELECT id, username, role, full_name FROM users WHERE username = %s AND role = 'employee'", (username,))
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
    cur.execute("SELECT id, username, role, full_name FROM users WHERE username = %s AND password = %s", (username, password))
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
    # Ambil juga pesan terakhir dan waktunya untuk setiap percakapan
    # Ini bisa menjadi query yang lebih kompleks atau beberapa query.
    # Untuk kesederhanaan, kita akan modifikasi query yang ada dan tambahkan data pesan terakhir.
    # Anda mungkin perlu membuat kolom 'last_message_preview' dan 'last_message_time' di tabel 'conversations'
    # dan mengupdatenya setiap kali ada pesan baru. Atau, lakukan join.
    
    # Query yang dimodifikasi untuk mengambil pesan terakhir (contoh, mungkin perlu optimasi)
    cur.execute("""
        SELECT 
            c.id, 
            c.status, 
            e.full_name as employee_name, 
            t.full_name as tech_name,
            c.last_updated,
            m.message as last_message_preview,  -- Ambil teks pesan terakhir
            m.sent_at as last_message_time  -- Ambil waktu pesan terakhir
        FROM conversations c
        JOIN users e ON c.employee_id = e.id
        LEFT JOIN users t ON c.technician_id = t.id
        LEFT JOIN messages m ON c.last_message_id = m.id  -- Join berdasarkan last_message_id
        WHERE c.employee_id = %s OR c.technician_id = %s
        ORDER BY c.last_updated DESC
    """, (user_id, user_id))
    
    conversations_data = []
    for conv_row in cur.fetchall():
        conversations_data.append({
            'id': conv_row[0],
            'status': conv_row[1],
            'employee_name': conv_row[2],
            'tech_name': conv_row[3] if conv_row[3] else 'Belum ditugaskan',
            'last_updated': conv_row[4].strftime('%Y-%m-%d %H:%M:%S') if conv_row[4] else None,
            'last_message_preview': conv_row[5] if conv_row[5] else "No messages yet.", # Teks pesan terakhir
            'last_message_time': conv_row[6].strftime('%Y-%m-%d %H:%M:%S') if conv_row[6] else (conv_row[4].strftime('%Y-%m-%d %H:%M:%S') if conv_row[4] else None) # Waktu pesan terakhir
        })
    cur.close()
    return jsonify(conversations_data)

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

    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT id FROM users 
        WHERE role = 'technician' OR role = 'ga' 
        ORDER BY RAND() LIMIT 1
    """)
    tech = cur.fetchone()
    technician_id = tech[0] if tech else None

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
    message_text = data['message'] # Ganti nama variabel agar tidak bentrok
    
    cur = mysql.connection.cursor()
    # Masukkan pesan baru
    cur.execute("""
        INSERT INTO messages (conversation_id, sender_id, message)
        VALUES (%s, %s, %s)
    """, (conversation_id, sender_id, message_text))
    mysql.connection.commit() # Commit dulu untuk mendapatkan lastrowid
    
    new_message_id = cur.lastrowid # Dapatkan ID dari pesan yang baru saja dimasukkan

    # Update last_updated dan last_message_id di tabel conversations
    cur.execute("""
        UPDATE conversations 
        SET last_updated = NOW(), last_message_id = %s
        WHERE id = %s
    """, (new_message_id, conversation_id))
    mysql.connection.commit()
    
    # Dapatkan detail pesan yang baru dikirim untuk Socket.IO
    cur.execute("""
        SELECT m.id, m.sender_id, u.full_name, m.message, m.sent_at
        FROM messages m
        JOIN users u ON m.sender_id = u.id
        WHERE m.id = %s
    """, (new_message_id,)) # Gunakan new_message_id
    
    message_data_row = cur.fetchone() # Ganti nama variabel
    cur.close()
    
    if message_data_row:
        socketio.emit('new_message', {
            'conversation_id': conversation_id,
            'message': {
                'id': message_data_row[0],
                'sender_id': message_data_row[1],
                'sender_name': message_data_row[2],
                'message': message_data_row[3],
                'sent_at': message_data_row[4].strftime('%Y-%m-%d %H:%M:%S')
            }
        }) # broadcast=True akan mengirim ke semua klien yang terhubung
        return jsonify({'success': True, 'message_id': new_message_id})
    else:
        return jsonify({'success': False, 'message': 'Failed to retrieve sent message details'}), 500

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
        return jsonify({'success': False, 'message': 'No file part'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'message': 'No selected file'}), 400
    
    conversation_id = request.form.get('conversation_id') # Ambil dari form data
    sender_id = request.form.get('sender_id') # Ambil dari form data

    if not conversation_id or not sender_id:
        return jsonify({'success': False, 'message': 'Missing conversation_id or sender_id'}), 400

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        # Buat path unik jika diperlukan atau biarkan overwrite (hati-hati)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        
        try:
            file.save(filepath)
        except Exception as e:
            print(f"Error saving file: {e}")
            return jsonify({'success': False, 'message': f'Error saving file: {e}'}), 500

        cur = mysql.connection.cursor()
        try:
            cur.execute("""
                INSERT INTO messages (conversation_id, sender_id, message, file_path)
                VALUES (%s, %s, %s, %s)
            """, (conversation_id, sender_id, f"[File: {filename}]", filename)) # Simpan nama file, bukan full path server
            
            new_message_id = cur.lastrowid # Dapatkan ID pesan baru

            cur.execute("""
                UPDATE conversations SET last_updated = NOW(), last_message_id = %s 
                WHERE id = %s
            """, (new_message_id, conversation_id))
            mysql.connection.commit()
            
            # Dapatkan detail pesan yang baru dikirim
            cur.execute("""
                SELECT m.id, m.sender_id, u.full_name, m.message, m.sent_at, m.file_path
                FROM messages m
                JOIN users u ON m.sender_id = u.id
                WHERE m.id = %s
            """, (new_message_id,)) # Gunakan new_message_id
            
            message_data_row = cur.fetchone() # Ganti nama variabel
            
            if message_data_row: # <-- PENGECEKAN PENTING
                socketio.emit('new_message', {
                    'conversation_id': int(conversation_id), # Pastikan tipe data konsisten
                    'message': {
                        'id': message_data_row[0],
                        'sender_id': message_data_row[1],
                        'sender_name': message_data_row[2],
                        'message': message_data_row[3], # Ini akan berisi "[File: namafile.ext]"
                        'sent_at': message_data_row[4].strftime('%Y-%m-%d %H:%M:%S'),
                        'file_path': message_data_row[5] # Ini adalah nama file yang disimpan
                    }
                })
                cur.close()
                return jsonify({'success': True, 'file_path': filename}) # Kembalikan nama file
            else:
                cur.close()
                print(f"Error: message_data_row is None for new_message_id {new_message_id}")
                return jsonify({'success': False, 'message': 'Failed to retrieve sent message details after upload'}), 500

        except Exception as e_db:
            mysql.connection.rollback() # Rollback jika ada error DB
            cur.close()
            print(f"Database error during file upload: {e_db}")
            return jsonify({'success': False, 'message': f'Database error: {e_db}'}), 500
    
    return jsonify({'success': False, 'message': 'File type not allowed'}), 400

# Tambahkan endpoint baru untuk menyajikan file dari folder 'uploads'
@app.route('/uploads/<path:filename>')
def uploaded_file_serve(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# ... (kode server.py yang sudah ada) ...

@app.route('/add_user', methods=['POST'])
def add_user():
    data = request.get_json()
    username = data.get('username')
    full_name = data.get('full_name')
    password = data.get('password') # Bisa kosong jika role employee
    role = data.get('role')

    # Validasi field inti
    if not all([username, full_name, role]):
        return jsonify({'success': False, 'message': 'Username, Full Name, and Role are required fields'}), 400

    if role not in ['employee', 'technician', 'ga']:
        return jsonify({'success': False, 'message': 'Invalid role specified'}), 400

    hashed_password = None # Default ke None (untuk employee tanpa password)

    if role == 'technician' or role == 'ga':
        if not password: # Password wajib untuk teknisi
            return jsonify({'success': False, 'message': 'Password is required for technician role'}), 400
        hashed_password = hash_password(password)
    
        
    elif role == 'employee':
        if password: # Jika employee mengisi password, kita hash
            hashed_password = hash_password(password)
        # Jika password kosong untuk employee, hashed_password tetap None

    cur = mysql.connection.cursor()
    try:
        # Cek apakah username sudah ada
        cur.execute("SELECT id FROM users WHERE username = %s", (username,))
        if cur.fetchone():
            cur.close()
            return jsonify({'success': False, 'message': 'Username already exists'}), 409

        # Insert pengguna baru
        # Kolom password di DB harus bisa menerima NULL
        cur.execute("""
            INSERT INTO users (username, full_name, password, role)
            VALUES (%s, %s, %s, %s)
        """, (username, full_name, hashed_password, role))
        mysql.connection.commit()
        new_user_id = cur.lastrowid
        cur.close()
        return jsonify({'success': True, 'message': 'User added successfully', 'user_id': new_user_id})

    except Exception as e:
        mysql.connection.rollback()
        cur.close()
        print(f"Error adding user: {e}")
        return jsonify({'success': False, 'message': f'Database error: {str(e)}'}), 500

# ... (kode server.py yang sudah ada) ...



# ... (sisa kode server.py) ...
# ... (sisa kode server.py) ...





if __name__ == '__main__':
    print("Starting server with Flask-SocketIO (eventlet should be auto-detected)...")
    # Pastikan UPLOAD_FOLDER sudah didefinisikan di konfigurasi app
    if not os.path.exists(app.config['UPLOAD_FOLDER']):
        os.makedirs(app.config['UPLOAD_FOLDER'])
    socketio.run(app, debug=True, host='0.0.0.0', port=5000, use_reloader=False)
