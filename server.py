import eventlet
eventlet.monkey_patch()  # Patch untuk mendukung Socket.IO dengan Flask

from flask import Flask, request, jsonify
from flask_mysqldb import MySQL
from flask_socketio import SocketIO
from flask_cors import CORS
import hashlib
import pandas as pd
from datetime import datetime, timedelta
import os
from werkzeug.utils import secure_filename
from flask import Flask, request, jsonify, send_from_directory
from apscheduler.schedulers.background import BackgroundScheduler

IP = "192.168.29.125"
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


def cleanup_old_messages_job():
    print(f"[{datetime.now()}] Menjalankan job terjadwal: Pembersihan pesan mingguan (Skenario B).")
    # Pastikan kita memiliki konteks aplikasi Flask
    with app.app_context():
        cur = None
        try:
            cur = mysql.connection.cursor()
            
            today = datetime.now()
            # Job ini dijadwalkan berjalan pada hari Minggu.
            # Kita ingin menghapus semua pesan SEBELUM hari Senin dari minggu yang baru saja berakhir.
            # today.weekday(): Senin=0, Selasa=1, ..., Minggu=6.
            # Jika hari ini Minggu (weekday == 6), Senin minggu ini adalah (today - timedelta(days=6)).
            # Ini adalah batas tanggalnya. Pesan SEBELUM tanggal ini akan dihapus.
            start_of_current_week_monday = today - timedelta(days=today.weekday()) 
            cleanup_threshold_date = start_of_current_week_monday.replace(hour=0, minute=0, second=0, microsecond=0)
            
            cleanup_threshold_date_str = cleanup_threshold_date.strftime('%Y-%m-%d %H:%M:%S')
            print(f"DEBUG: Cleanup (Skenario B) - Akan menghapus semua pesan yang dikirim sebelum {cleanup_threshold_date_str}.")

            # Langkah 1: Atur last_message_id menjadi NULL di tabel conversations
            # untuk pesan-pesan yang akan dihapus agar tidak melanggar foreign key.
            sql_update_conversations = """
                UPDATE conversations c
                SET c.last_message_id = NULL
                WHERE c.last_message_id IS NOT NULL AND c.last_message_id IN (
                    SELECT id FROM messages WHERE sent_at < %s
                );
            """
            cur.execute(sql_update_conversations, (cleanup_threshold_date_str,))
            updated_convs_count = cur.rowcount
            print(f"DEBUG: Cleanup (Skenario B) - last_message_id di-NULL-kan untuk {updated_convs_count} percakapan.")

            # Langkah 2: Ambil daftar file_path dari pesan lama yang akan dihapus (jika ada)
            sql_select_files = """
                SELECT file_path FROM messages 
                WHERE sent_at < %s AND file_path IS NOT NULL AND file_path != ''
            """
            cur.execute(sql_select_files, (cleanup_threshold_date_str,))
            files_to_delete_on_disk = [row[0] for row in cur.fetchall()]
            print(f"DEBUG: Cleanup (Skenario B) - Menemukan {len(files_to_delete_on_disk)} file untuk potensi penghapusan dari disk.")

            # Langkah 3: Hapus pesan lama dari tabel messages
            sql_delete_messages = "DELETE FROM messages WHERE sent_at < %s;"
            cur.execute(sql_delete_messages, (cleanup_threshold_date_str,))
            deleted_messages_count = cur.rowcount
            print(f"DEBUG: Cleanup (Skenario B) - {deleted_messages_count} pesan lama berhasil dihapus dari database.")
            
            mysql.connection.commit()
            print(f"DEBUG: Cleanup (Skenario B) - Transaksi database di-commit.")

            # # Langkah 4: (Opsional) Hapus file fisik dari folder 'uploads'
            # if files_to_delete_on_disk:
            #     upload_folder = app.config.get('UPLOAD_FOLDER', 'uploads')
            #     for filename in files_to_delete_on_disk:
            #         try:
            #             file_location = os.path.join(upload_folder, filename)
            #             if os.path.exists(file_location):
            #                 os.remove(file_location)
            #                 print(f"DEBUG: Cleanup (Skenario B) - File fisik '{filename}' berhasil dihapus.")
            #             # else:
            #                 # print(f"DEBUG: Cleanup (Skenario B) - File fisik '{filename}' tidak ditemukan di disk.")
            #         except Exception as e_file_delete:
            #             print(f"DEBUG: Cleanup (Skenario B) - Error saat menghapus file fisik '{filename}': {e_file_delete}")
            
            print(f"[{datetime.now()}] Scheduled job: Pembersihan pesan mingguan (Skenario B) selesai.")

        except Exception as e:
            if cur:
                mysql.connection.rollback()
            print(f"[{datetime.now()}] ERROR selama pembersihan pesan mingguan terjadwal (Skenario B): {e}")
        finally:
            if cur:
                cur.close()

def start_scheduler():
    scheduler = BackgroundScheduler(daemon=True)
    # Jalankan job cleanup_old_messages_job:
    # 'cron' digunakan untuk jadwal yang lebih spesifik.
    # day_of_week='sun' berarti setiap hari Minggu.
    # hour=1, minute=0 berarti jam 01:00 pagi.

    scheduler.add_job(
        cleanup_old_messages_job, 
        trigger='cron', 
        day_of_week='sun',  # 0=Senin, 1=Selasa, ..., 6=Minggu ATAU 'sun', 'mon', etc.
        hour=1,             # Jam 1 pagi
        minute=0,           # Menit ke-0
        misfire_grace_time=3600 # Toleransi jika server down saat jadwal (1 jam)
    )
    
    try:
        scheduler.start()
        print("APScheduler untuk pembersihan pesan mingguan (setiap Minggu pukul 01:00) telah dimulai.")
    except Exception as e_scheduler:
        print(f"Error starting APScheduler: {e_scheduler}")



# Helper function
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

@app.route('/get_support_staff', methods=['GET'])
def get_support_staff():
    # Endpoint ini khusus untuk mengambil semua user yang merupakan support staff (technician dan GA)
    cur = None
    try:
        cur = mysql.connection.cursor()
        # Ambil semua data yang mungkin diperlukan oleh dialog di klien
        cur.execute("""
            SELECT id, username, full_name, role 
            FROM users 
            WHERE role = 'technician' OR role = 'ga' 
            ORDER BY full_name ASC
        """)
        
        support_staff_list = []
        for row in cur.fetchall():
            support_staff_list.append({
                "id": row[0],
                "username": row[1],
                "full_name": row[2],
                "role": row[3]
            })
        
        # Sertakan juga total jumlah technician untuk validasi di klien
        technician_count = sum(1 for user in support_staff_list if user['role'] == 'technician')
        
        cur.close()
        return jsonify({
            'success': True, 
            'users': support_staff_list,
            'technician_count': technician_count
        })
    except Exception as e:
        if cur:
            cur.close()
        print(f"SERVER_ERROR di /get_support_staff: {e}") 
        return jsonify({'success': False, 'message': f'Gagal mengambil daftar support staff: {str(e)}'}), 500

@app.route('/update_support_user/<int:user_id>', methods=['PUT'])
def update_support_user(user_id):
    """Endpoint untuk mengupdate data support staff (technician/ga)."""
    data = request.get_json()
    new_full_name = data.get('full_name')
    new_password = data.get('password') # Bisa None

    if not new_full_name:
        return jsonify({'success': False, 'message': 'Nama lengkap tidak boleh kosong.'}), 400

    cur = None
    try:
        cur = mysql.connection.cursor()
        
        # Cek apakah user ada dan merupakan support staff
        cur.execute("SELECT role FROM users WHERE id = %s", (user_id,))
        user = cur.fetchone()
        if not user:
            cur.close()
            return jsonify({'success': False, 'message': 'User tidak ditemukan.'}), 404
        if user[0] not in ['technician', 'ga']:
            cur.close()
            return jsonify({'success': False, 'message': 'Hanya role technician atau GA yang bisa diubah.'}), 403

        # Siapkan query update
        query_parts = ["full_name = %s"]
        params = [new_full_name]

        if new_password:
            hashed_password = hash_password(new_password)
            query_parts.append("password = %s")
            params.append(hashed_password)
        
        params.append(user_id)
        
        sql_query = f"UPDATE users SET {', '.join(query_parts)} WHERE id = %s"
        
        cur.execute(sql_query, tuple(params))
        mysql.connection.commit()
        
        cur.close()
        return jsonify({'success': True, 'message': f'User {new_full_name} berhasil diupdate.'})

    except Exception as e:
        if cur:
            mysql.connection.rollback()
            cur.close()
        print(f"SERVER_ERROR di /update_support_user/{user_id}: {e}")
        return jsonify({'success': False, 'message': f'Error pada server: {e}'}), 500

@app.route('/update_employee/<int:user_id>', methods=['PUT'])
def update_employee(user_id):
    """Endpoint untuk mengupdate data employee."""
    data = request.get_json()
    new_full_name = data.get('full_name')

    if not new_full_name:
        return jsonify({'success': False, 'message': 'Nama lengkap tidak boleh kosong.'}), 400

    cur = None
    try:
        cur = mysql.connection.cursor()
        
        # Cek apakah user ada dan merupakan employee
        cur.execute("SELECT role FROM users WHERE id = %s", (user_id,))
        user = cur.fetchone()
        if not user:
            cur.close()
            return jsonify({'success': False, 'message': 'User tidak ditemukan.'}), 404
        if user[0] != 'employee':
            cur.close()
            return jsonify({'success': False, 'message': 'Hanya data employee yang bisa diubah melalui endpoint ini.'}), 403

        # Update nama lengkap
        cur.execute("UPDATE users SET full_name = %s WHERE id = %s", (new_full_name, user_id))
        mysql.connection.commit()
        
        cur.close()
        return jsonify({'success': True, 'message': f'Data employee berhasil diupdate.'})

    except Exception as e:
        if cur:
            mysql.connection.rollback()
            cur.close()
        print(f"SERVER_ERROR di /update_employee/{user_id}: {e}")
        return jsonify({'success': False, 'message': f'Error pada server: {e}'}), 500



@app.route('/delete_support_user/<int:user_id>', methods=['DELETE'])
def delete_support_user(user_id):
    """Endpoint untuk menghapus support staff (technician/ga)."""
    cur = None
    try:
        cur = mysql.connection.cursor()

        # 1. Validasi: Pastikan user ada dan merupakan support staff
        cur.execute("SELECT role, full_name FROM users WHERE id = %s", (user_id,))
        user_to_delete = cur.fetchone()
        if not user_to_delete:
            cur.close()
            return jsonify({'success': False, 'message': 'User tidak ditemukan.'}), 404
        
        role, full_name = user_to_delete
        if role not in ['technician', 'ga']:
            cur.close()
            return jsonify({'success': False, 'message': 'Hanya role technician atau GA yang bisa dihapus.'}), 403

        # 2. Validasi Keamanan: Jangan biarkan teknisi terakhir dihapus
        if role == 'technician':
            cur.execute("SELECT COUNT(*) FROM users WHERE role = 'technician'")
            technician_count = cur.fetchone()[0]
            if technician_count <= 1:
                cur.close()
                return jsonify({'success': False, 'message': 'Tidak bisa menghapus teknisi terakhir yang tersisa.'}), 400

        # 3. Penanganan Percakapan: Set technician_id menjadi NULL pada percakapan yang ditangani
        #    Ini akan membuat tiket menjadi "unassigned" daripada menghapus seluruh percakapan.
        cur.execute("UPDATE conversations SET technician_id = NULL WHERE technician_id = %s", (user_id,))
        print(f"DEBUG: {cur.rowcount} percakapan yang ditangani oleh user {user_id} telah di-unassign.")
        
        cur.execute("SELECT id FROM conversations WHERE employee_id = %s", (user_id,))
        conversation_ids_tuples = cur.fetchall()
        conversation_ids_to_delete = [conv_tuple[0] for conv_tuple in conversation_ids_tuples]
        
        all_files_to_delete_on_disk = []

        if conversation_ids_to_delete:
            for conv_id in conversation_ids_to_delete:
                # a. (Opsional) Ambil file_path dari pesan yang akan dihapus
                cur.execute("SELECT file_path FROM messages WHERE conversation_id = %s AND file_path IS NOT NULL", (conv_id,))
                files_in_conv = [row[0] for row in cur.fetchall()]
                all_files_to_delete_on_disk.extend(files_in_conv)

                # b. Atur last_message_id menjadi NULL di tabel conversations untuk percakapan ini
                cur.execute("UPDATE conversations SET last_message_id = NULL WHERE id = %s", (conv_id,))
                
                # c. Hapus pesan dari percakapan ini
                cur.execute("DELETE FROM messages WHERE conversation_id = %s", (conv_id,))
                print(f"DEBUG: Server - Menghapus pesan dari percakapan ID: {conv_id}")

            # d. Hapus semua percakapan yang terkait setelah pesannya dihapus
            # Gunakan %s placeholder untuk setiap ID dalam list
            format_strings = ','.join(['%s'] * len(conversation_ids_to_delete))
            cur.execute(f"DELETE FROM conversations WHERE id IN ({format_strings})", tuple(conversation_ids_to_delete))
            print(f"DEBUG: Server - Menghapus percakapan dengan ID: {conversation_ids_to_delete}")

        # 4. Hapus User
        cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
        
        mysql.connection.commit()
        cur.close()
        
        return jsonify({'success': True, 'message': f'Support staff {full_name} berhasil dihapus.'})

    except Exception as e:
        if cur:
            mysql.connection.rollback()
            cur.close()
        print(f"SERVER_ERROR di /delete_support_user/{user_id}: {e}")
        return jsonify({'success': False, 'message': f'Error pada server: {e}'}), 500


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
            socketio.emit('conversation_created', {'conversation_data': new_conv_details}) # Contoh emit
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
            c.employee_id,
            c.technician_id,
            e.full_name as employee_name, 
            e.username as employee_username, -- TAMBAHKAN INI
            t.full_name as tech_name,
            c.last_updated,
            m.message as last_message_preview,
            m.sent_at as last_message_time
        FROM conversations c
        JOIN users e ON c.employee_id = e.id
        LEFT JOIN users t ON c.technician_id = t.id
        LEFT JOIN messages m ON c.last_message_id = m.id
        WHERE c.employee_id = %s OR c.technician_id = %s
        ORDER BY c.last_updated DESC
    """, (user_id, user_id))
    
    conversations_data = []
    for conv_row in cur.fetchall():
        conversations_data.append({
            'id': conv_row[0],
            'status': conv_row[1],
            'employee_id': conv_row[2],
            'technician_id': conv_row[3],
            'employee_name': conv_row[4],
            'employee_username': conv_row[5], # TAMBAHKAN INI
            'tech_name': conv_row[6] if conv_row[6] else 'Belum ditugaskan',
            'last_updated': conv_row[7].strftime('%Y-%m-%d %H:%M:%S') if conv_row[7] else None,
            'last_message_preview': conv_row[8] if conv_row[8] else "No messages yet.",
            'last_message_time': conv_row[9].strftime('%Y-%m-%d %H:%M:%S') if conv_row[9] else (conv_row[7].strftime('%Y-%m-%d %H:%M:%S') if conv_row[7] else None)
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
        })
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
    password = data.get('password') 
    role = data.get('role')

    if not all([username, full_name, role]):
        return jsonify({'success': False, 'message': 'Username, Full Name, and Role are required fields'}), 400

    if role not in ['employee', 'technician', 'ga']:
        return jsonify({'success': False, 'message': 'Invalid role specified'}), 400

    hashed_password = None
    if role in ['technician', 'ga']:
        if not password:
            return jsonify({'success': False, 'message': f'Password is required for {role} role'}), 400
        hashed_password = hash_password(password)
    elif role == 'employee' and password:
        hashed_password = hash_password(password)

    cur = mysql.connection.cursor()
    try:
        cur.execute("SELECT id FROM users WHERE username = %s", (username,))
        if cur.fetchone():
            cur.close()
            return jsonify({'success': False, 'message': 'Username already exists'}), 409

        cur.execute("""
            INSERT INTO users (username, full_name, password, role)
            VALUES (%s, %s, %s, %s)
        """, (username, full_name, hashed_password, role))
        mysql.connection.commit()
        new_user_id = cur.lastrowid

        # --- LOGIKA PEMBUATAN PERCAKAPAN OTOMATIS ---
        conversations_created_count = 0
        if role == 'employee':
            # Dapatkan semua ID technician dan GA
            cur.execute("SELECT id FROM users WHERE role = 'technician' OR role = 'ga'")
            support_staff_ids = [row[0] for row in cur.fetchall()]
            for staff_id in support_staff_ids:
                # Buat percakapan: employee baru dengan setiap staff
                cur.execute("""
                    INSERT INTO conversations (employee_id, technician_id, status, last_updated) 
                    VALUES (%s, %s, %s, NOW())
                """, (new_user_id, staff_id, 'open'))
                mysql.connection.commit()
                conversation_id = cur.lastrowid
                conversations_created_count += 1
                emit_new_conversation_details(conversation_id, cur) # Helper function

        elif role == 'technician' or role == 'ga':
            # Dapatkan semua ID employee
            cur.execute("SELECT id FROM users WHERE role = 'employee'")
            employee_ids = [row[0] for row in cur.fetchall()]
            for emp_id in employee_ids:
                # Buat percakapan: setiap employee dengan technician/GA baru
                cur.execute("""
                    INSERT INTO conversations (employee_id, technician_id, status, last_updated) 
                    VALUES (%s, %s, %s, NOW())
                """, (emp_id, new_user_id, 'open')) # Perhatikan urutan ID
                mysql.connection.commit()
                conversation_id = cur.lastrowid
                conversations_created_count += 1
                emit_new_conversation_details(conversation_id, cur) # Helper function

        cur.close()
        return jsonify({
            'success': True, 
            'message': f'User {full_name} ({role}) added successfully.', 
            'user_id': new_user_id,
            'conversations_created_count': conversations_created_count
        })

    except Exception as e:
        mysql.connection.rollback()
        if cur:
            cur.close()
        print(f"Error adding user or creating conversations: {e}")
        return jsonify({'success': False, 'message': f'Database error: {str(e)}'}), 500

@app.route('/bulk_add_users', methods=['POST'])
def bulk_add_users():
    # 1. Cek apakah ada file yang diunggah
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': 'Tidak ada bagian file dalam permintaan'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'message': 'Tidak ada file yang dipilih'}), 400

    # 2. Cek ekstensi file dan baca menggunakan pandas
    try:
        if file.filename.endswith('.csv'):
            df = pd.read_csv(file)
        elif file.filename.endswith(('.xls', '.xlsx')):
            df = pd.read_excel(file)
        else:
            return jsonify({'success': False, 'message': 'Jenis file tidak didukung. Harap gunakan .csv atau .xlsx'}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': f'Gagal membaca file: {str(e)}'}), 500

    # 3. Proses setiap baris dalam DataFrame
    cur = None
    added_count = 0
    skipped_count = 0
    error_list = []

    try:
        cur = mysql.connection.cursor()
        
        for index, row in df.iterrows():
            username = str(row.get('username', '')).strip()
            full_name = str(row.get('full_name', '')).strip()
            role = str(row.get('role', '')).strip().lower()
            password = str(row.get('password', '')) if not pd.isna(row.get('password')) else None

            # Validasi data per baris
            if not all([username, full_name, role]):
                error_list.append(f"Baris {index + 2}: Data tidak lengkap (username, full_name, role wajib diisi).")
                continue

            if role not in ['employee', 'technician', 'ga']:
                error_list.append(f"Baris {index + 2}: Role '{role}' tidak valid untuk user '{username}'.")
                continue

            # Cek duplikat
            cur.execute("SELECT id FROM users WHERE username = %s", (username,))
            if cur.fetchone():
                skipped_count += 1
                continue

            # Logika hashing password (sama seperti di /add_user)
            hashed_password = None
            if role in ['technician', 'ga']:
                if not password:
                    error_list.append(f"Baris {index + 2}: Password wajib untuk role '{role}' (user: {username}).")
                    continue
                hashed_password = hash_password(password)
            elif role == 'employee' and password:
                hashed_password = hash_password(password)
            
            # Insert ke database
            cur.execute("""
                INSERT INTO users (username, full_name, password, role)
                VALUES (%s, %s, %s, %s)
            """, (username, full_name, hashed_password, role))
            mysql.connection.commit()
            new_user_id = cur.lastrowid
            added_count += 1
            
            # Logika pembuatan percakapan otomatis (disalin dari /add_user)
            if role == 'employee':
                cur.execute("SELECT id FROM users WHERE role = 'technician' OR role = 'ga'")
                support_staff_ids = [r[0] for r in cur.fetchall()]
                for staff_id in support_staff_ids:
                    cur.execute("INSERT INTO conversations (employee_id, technician_id, status, last_updated) VALUES (%s, %s, 'open', NOW())", (new_user_id, staff_id))
                    mysql.connection.commit()
                    emit_new_conversation_details(cur.lastrowid, cur)
            elif role in ['technician', 'ga']:
                cur.execute("SELECT id FROM users WHERE role = 'employee'")
                employee_ids = [r[0] for r in cur.fetchall()]
                for emp_id in employee_ids:
                    cur.execute("INSERT INTO conversations (employee_id, technician_id, status, last_updated) VALUES (%s, %s, 'open', NOW())", (emp_id, new_user_id))
                    mysql.connection.commit()
                    emit_new_conversation_details(cur.lastrowid, cur)

    except Exception as e:
        mysql.connection.rollback()
        print(f"Error saat bulk add users: {e}")
        return jsonify({'success': False, 'message': f'Terjadi error di server: {str(e)}'}), 500
    finally:
        if cur:
            cur.close()


    # 4. Kirim ringkasan hasil ke klien
    summary_message = f"Proses selesai. Ditambahkan: {added_count}, Duplikat dilewati: {skipped_count}, Error: {len(error_list)}."
    return jsonify({
        'success': True, 
        'message': summary_message,
        'details': {
            'added': added_count,
            'skipped_duplicates': skipped_count,
            'errors': len(error_list),
            'error_list': error_list
        }
    })


def emit_new_conversation_details(conversation_id, cursor):
    """
    Helper untuk mengambil detail percakapan dan meng-emit via Socket.IO.
    Pastikan cursor masih valid dan transaksi untuk pembuatan percakapan sudah di-commit.
    """
    try:
        cursor.execute("""
            SELECT 
                c.id, c.status, c.employee_id, c.technician_id,
                e.full_name as employee_name, t.full_name as tech_name,
                c.last_updated,
                m.message as last_message_preview,
                m.sent_at as last_message_time 
            FROM conversations c
            JOIN users e ON c.employee_id = e.id
            LEFT JOIN users t ON c.technician_id = t.id
            LEFT JOIN messages m ON c.last_message_id = m.id
            WHERE c.id = %s
        """, (conversation_id,))
        conv_row = cursor.fetchone()

        if conv_row:
            conv_details = {
                'id': conv_row[0],
                'status': conv_row[1],
                'employee_id': conv_row[2],
                'technician_id': conv_row[3],
                'employee_name': conv_row[4],
                'tech_name': conv_row[5] if conv_row[5] else 'N/A', # Tech might be null if created by system before assignment
                'last_updated': conv_row[6].strftime('%Y-%m-%d %H:%M:%S') if conv_row[6] else None,
                'last_message_preview': conv_row[7] if conv_row[7] else "Conversation started.",
                'last_message_time': (conv_row[8].strftime('%Y-%m-%d %H:%M:%S') if conv_row[8] 
                                     else (conv_row[6].strftime('%Y-%m-%d %H:%M:%S') if conv_row[6] else None))
            }
            socketio.emit('conversation_created', {'conversation_data': conv_details})
            print(f"SERVER: Emitted 'conversation_created' for conv_id: {conversation_id}")
        else:
            print(f"SERVER_WARNING: Could not fetch details for new conv_id: {conversation_id} to emit.")
    except Exception as e:
        print(f"SERVER_ERROR: Failed to emit new conversation details for conv_id {conversation_id}: {e}")
        
# @app.route('/add_user', methods=['POST'])
# def add_user():
#     data = request.get_json()
#     username = data.get('username')
#     full_name = data.get('full_name')
#     password = data.get('password') # Bisa kosong jika role employee
#     role = data.get('role')

#     # Validasi field inti
#     if not all([username, full_name, role]):
#         return jsonify({'success': False, 'message': 'Username, Full Name, and Role are required fields'}), 400

#     if role not in ['employee', 'technician', 'ga']:
#         return jsonify({'success': False, 'message': 'Invalid role specified'}), 400

#     hashed_password = None # Default ke None (untuk employee tanpa password)

#     if role == 'technician' or role == 'ga':
#         if not password: # Password wajib untuk teknisi
#             return jsonify({'success': False, 'message': 'Password is required for technician role'}), 400
#         hashed_password = hash_password(password)
    
        
#     elif role == 'employee':
#         if password: # Jika employee mengisi password, kita hash
#             hashed_password = hash_password(password)
#         # Jika password kosong untuk employee, hashed_password tetap None

#     cur = mysql.connection.cursor()
#     try:
#         # Cek apakah username sudah ada
#         cur.execute("SELECT id FROM users WHERE username = %s", (username,))
#         if cur.fetchone():
#             cur.close()
#             return jsonify({'success': False, 'message': 'Username already exists'}), 409

#         # Insert pengguna baru
#         # Kolom password di DB harus bisa menerima NULL
#         cur.execute("""
#             INSERT INTO users (username, full_name, password, role)
#             VALUES (%s, %s, %s, %s)
#         """, (username, full_name, hashed_password, role))
#         mysql.connection.commit()
#         new_user_id = cur.lastrowid
#         cur.close()
#         return jsonify({'success': True, 'message': 'User added successfully', 'user_id': new_user_id})

#     except Exception as e:
#         mysql.connection.rollback()
#         cur.close()
#         print(f"Error adding user: {e}")
#         return jsonify({'success': False, 'message': f'Database error: {str(e)}'}), 500

# @app.route('/delete_conversation/<int:conv_id>', methods=['DELETE'])
# def delete_conversation_route(conv_id):
#     cur = None
#     try:
#         cur = mysql.connection.cursor()

#         # Cek dulu apakah percakapan ada
#         cur.execute("SELECT employee_id, technician_id FROM conversations WHERE id = %s", (conv_id,))
#         conversation_exists = cur.fetchone()
#         if not conversation_exists:
#             cur.close()
#             return jsonify({'success': False, 'message': f'Percakapan ID {conv_id} tidak ditemukan.'}), 404

#         # (Opsional) Ambil file_path dari pesan yang akan dihapus jika ingin menghapus file fisik
#         cur.execute("SELECT file_path FROM messages WHERE conversation_id = %s AND file_path IS NOT NULL", (conv_id,))
#         files_to_delete_on_disk = [row[0] for row in cur.fetchall()]

#         # Langkah 1: Atur last_message_id menjadi NULL di tabel conversations untuk percakapan ini.
#         # Ini menghilangkan referensi foreign key ke tabel messages, sehingga pesan bisa dihapus.
#         cur.execute("UPDATE conversations SET last_message_id = NULL WHERE id = %s", (conv_id,))
#         print(f"DEBUG: Server - last_message_id di-set NULL untuk percakapan ID: {conv_id}")

#         # Langkah 2: Hapus semua pesan yang terkait dengan conversation_id ini.
#         cur.execute("DELETE FROM messages WHERE conversation_id = %s", (conv_id,))
#         deleted_messages_count = cur.rowcount
#         print(f"DEBUG: Server - Menghapus {deleted_messages_count} pesan dari percakapan ID: {conv_id}")

#         # Langkah 3: Hapus percakapan itu sendiri dari tabel conversations.
#         cur.execute("DELETE FROM conversations WHERE id = %s", (conv_id,))
#         deleted_conversations_count = cur.rowcount
#         print(f"DEBUG: Server - Menghapus {deleted_conversations_count} percakapan dengan ID: {conv_id}")
        
#         mysql.connection.commit() # Commit transaksi

#         # Langkah 4: (Opsional Lanjutan) Hapus file fisik dari folder 'uploads'.
#         if files_to_delete_on_disk:
#             print(f"DEBUG: Server - Mencoba menghapus file fisik untuk percakapan ID: {conv_id}")
#             for filename in files_to_delete_on_disk:
#                 if filename:
#                     try:
#                         file_location = os.path.join(app.config['UPLOAD_FOLDER'], filename)
#                         if os.path.exists(file_location):
#                             os.remove(file_location)
#                             print(f"DEBUG: Server - File fisik '{filename}' berhasil dihapus.")
#                         else:
#                             print(f"DEBUG: Server - File fisik '{filename}' tidak ditemukan di disk.")
#                     except Exception as e_file_delete:
#                         print(f"DEBUG: Server - Error saat menghapus file fisik '{filename}': {e_file_delete}")
        
#         socketio.emit('conversation_deleted', {'conversation_id': conv_id})
#         print(f"DEBUG: Server - Mengirim event 'conversation_deleted' untuk ID: {conv_id}")

#         cur.close()
#         return jsonify({'success': True, 'message': f'Percakapan ID {conv_id} dan semua pesannya berhasil dihapus.'})

#     except Exception as e:
#         if cur:
#             mysql.connection.rollback()
#             cur.close()
#         print(f"DEBUG: Server - Error saat menghapus percakapan ID {conv_id}: {e}")
#         # Error (1451) adalah OperationalError dari PyMySQL/MySQLdb, detailnya ada di e.args
#         error_code = ""
#         if hasattr(e, 'args') and len(e.args) > 0:
#             error_code = f" (Kode Error DB: {e.args[0]})"
#         return jsonify({'success': False, 'message': f'Terjadi kesalahan pada server{error_code}: {str(e)}'}), 500

@app.route('/delete_user/<int:user_id_to_delete>', methods=['DELETE'])
def delete_user_route(user_id_to_delete):
    # TODO: Di aplikasi produksi, tambahkan otorisasi yang kuat di sini.
    # Misalnya, periksa apakah pengguna yang meminta adalah teknisi.
    # Untuk saat ini, kita asumsikan permintaan dari it.py (teknisi) diotorisasi.
    # Juga, pastikan teknisi tidak bisa menghapus dirinya sendiri atau teknisi lain melalui endpoint ini jika tidak diinginkan.

    cur = None
    try:
        cur = mysql.connection.cursor()

        # 1. Pastikan user yang akan dihapus ada dan adalah 'employee' (sesuai asumsi dari klien)
        cur.execute("SELECT role, full_name FROM users WHERE id = %s", (user_id_to_delete,))
        user_to_delete_details = cur.fetchone()

        if not user_to_delete_details:
            cur.close()
            return jsonify({'success': False, 'message': f'User dengan ID {user_id_to_delete} tidak ditemukan.'}), 404
        
        user_role = user_to_delete_details[0]
        user_full_name = user_to_delete_details[1]

        if user_role != 'employee':
            cur.close()
            return jsonify({'success': False, 'message': f'Hanya user dengan peran "employee" yang bisa dihapus melalui endpoint ini. User ID {user_id_to_delete} adalah seorang "{user_role}".'}), 403 # Forbidden

        # 2. Dapatkan semua ID percakapan di mana user ini adalah 'employee_id'
        cur.execute("SELECT id FROM conversations WHERE employee_id = %s", (user_id_to_delete,))
        conversation_ids_tuples = cur.fetchall()
        conversation_ids_to_delete = [conv_tuple[0] for conv_tuple in conversation_ids_tuples]
        
        print(f"DEBUG: Server - Akan menghapus percakapan dengan ID: {conversation_ids_to_delete} yang terkait dengan user ID: {user_id_to_delete}")

        all_files_to_delete_on_disk = []

        if conversation_ids_to_delete:
            for conv_id in conversation_ids_to_delete:
                # a. (Opsional) Ambil file_path dari pesan yang akan dihapus
                cur.execute("SELECT file_path FROM messages WHERE conversation_id = %s AND file_path IS NOT NULL", (conv_id,))
                files_in_conv = [row[0] for row in cur.fetchall()]
                all_files_to_delete_on_disk.extend(files_in_conv)

                # b. Atur last_message_id menjadi NULL di tabel conversations untuk percakapan ini
                cur.execute("UPDATE conversations SET last_message_id = NULL WHERE id = %s", (conv_id,))
                
                # c. Hapus pesan dari percakapan ini
                cur.execute("DELETE FROM messages WHERE conversation_id = %s", (conv_id,))
                print(f"DEBUG: Server - Menghapus pesan dari percakapan ID: {conv_id}")

            # d. Hapus semua percakapan yang terkait setelah pesannya dihapus
            # Gunakan %s placeholder untuk setiap ID dalam list
            format_strings = ','.join(['%s'] * len(conversation_ids_to_delete))
            cur.execute(f"DELETE FROM conversations WHERE id IN ({format_strings})", tuple(conversation_ids_to_delete))
            print(f"DEBUG: Server - Menghapus percakapan dengan ID: {conversation_ids_to_delete}")
        
        # 3. Hapus user itu sendiri dari tabel users
        cur.execute("DELETE FROM users WHERE id = %s AND role = 'employee'", (user_id_to_delete,)) # Dobel cek role
        deleted_user_count = cur.rowcount
        print(f"DEBUG: Server - Menghapus {deleted_user_count} user dengan ID: {user_id_to_delete}")

        mysql.connection.commit() # Commit transaksi jika semua query berhasil

        # 4. (Opsional Lanjutan) Hapus file fisik dari folder 'uploads'
        if all_files_to_delete_on_disk:
            print(f"DEBUG: Server - Mencoba menghapus file fisik yang terkait dengan user ID: {user_id_to_delete}")
            for filename in all_files_to_delete_on_disk:
                if filename:
                    try:
                        file_location = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                        if os.path.exists(file_location):
                            os.remove(file_location)
                            print(f"DEBUG: Server - File fisik '{filename}' berhasil dihapus.")
                        else:
                            print(f"DEBUG: Server - File fisik '{filename}' tidak ditemukan di disk.")
                    except Exception as e_file_delete:
                        print(f"DEBUG: Server - Error saat menghapus file fisik '{filename}': {e_file_delete}")
        
        # Emit event ke klien lain bahwa user dan percakapannya telah dihapus
        socketio.emit('user_deleted', {'user_id': user_id_to_delete, 'deleted_conversation_ids': conversation_ids_to_delete})
        print(f"DEBUG: Server - Mengirim event 'user_deleted' untuk user ID: {user_id_to_delete}")

        cur.close()
        return jsonify({'success': True, 'message': f'User {user_full_name} (ID: {user_id_to_delete}) dan semua data terkait berhasil dihapus.'})

    except Exception as e:
        if cur:
            mysql.connection.rollback()
            cur.close()
        print(f"DEBUG: Server - Error saat menghapus user ID {user_id_to_delete}: {e}")
        error_code = ""
        if hasattr(e, 'args') and len(e.args) > 0:
            error_code = f" (Kode Error DB: {e.args[0]})"
        return jsonify({'success': False, 'message': f'Terjadi kesalahan pada server saat menghapus user{error_code}: {str(e)}'}), 500



if __name__ == '__main__':
    print("Starting server with Flask-SocketIO (eventlet should be auto-detected)...")
    # Pastikan UPLOAD_FOLDER sudah didefinisikan di konfigurasi app
    if not os.path.exists(app.config['UPLOAD_FOLDER']):
        os.makedirs(app.config['UPLOAD_FOLDER'])
    
    start_scheduler()  # Mulai scheduler untuk pembersihan pesan mingguan
    socketio.run(app, debug=True, host='0.0.0.0', port=5000, use_reloader=False)
