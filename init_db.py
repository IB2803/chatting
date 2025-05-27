import hashlib
import mysql.connector
from mysql.connector import Error

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def create_connection(host, user, password):
    try:
        db = mysql.connector.connect(
            host=host,
            user=user,
            password=password
        )
        return db
    except Error as e:
        print(f"Error: '{e}'")

def create_database(db, database_name):
    try:
        cursor = db.cursor()
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS {database_name}")
        cursor.close()
    except Error as e:
        print(f"Error: '{e}'")

def create_tables(db, database_name):
    try:
        cursor = db.cursor()
        cursor.execute(f"USE {database_name}")
        
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INT AUTO_INCREMENT PRIMARY KEY,
            username VARCHAR(50) UNIQUE NOT NULL,
            password VARCHAR(255) NOT NULL,
            role ENUM('employee', 'technician') NOT NULL,
            full_name VARCHAR(100) NOT NULL,
            department VARCHAR(50),
            last_online DATETIME,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """)
        
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id INT AUTO_INCREMENT PRIMARY KEY,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            status ENUM('open', 'closed') DEFAULT 'open',
            employee_id INT NOT NULL,
            technician_id INT,
            FOREIGN KEY (employee_id) REFERENCES users(id),
            FOREIGN KEY (technician_id) REFERENCES users(id)
        )
        """)
        
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INT AUTO_INCREMENT PRIMARY KEY,
            conversation_id INT NOT NULL,
            sender_id INT NOT NULL,
            message TEXT NOT NULL,
            sent_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            read_at DATETIME,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id),
            FOREIGN KEY (sender_id) REFERENCES users(id)
        )
        """)
        db.commit()
        cursor.close()
    except Error as e:
        print(f"Error: '{e}'")

def insert_users(db, database_name, users):
    try:
        cursor = db.cursor()
        cursor.execute(f"USE {database_name}")
        for username, password, role, full_name, department in users:
            hashed_pw = hash_password(password)
            try:
                cursor.execute(
                    "INSERT INTO users (username, password, role, full_name, department) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (username, hashed_pw, role, full_name, department)
                )
            except mysql.connector.IntegrityError:
                print(f"User {username} sudah ada, dilewati...")
        db.commit()
        cursor.close()
    except Error as e:
        print(f"Error: '{e}'")

def main():
    host = "localhost"
    user = "root"
    password = ""  # Sesuaikan dengan password MySQL Anda
    database_name = "it_support_chat"
    
    db = create_connection(host, user, password)
    if db:
        create_database(db, database_name)
        create_tables(db, database_name)
        
        users = [
            ("pegawai1", "password123", "employee", "John Doe", "HR"),
            ("teknisi1", "securepass", "technician", "Jane Smith", "IT Support"),
            ("pegawai2", "userpass", "employee", "Alice Johnson", "Finance"),
            ("teknisi2", "techpass123", "technician", "Bob Williams", "IT Support")
        ]
        insert_users(db, database_name, users)
        print("Database dan user contoh berhasil dibuat!")
        db.close()

if __name__ == "__main__":
    main()