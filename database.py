import sqlite3
import pandas as pd


def create_connection():
    conn = sqlite3.connect('student_system.db', check_same_thread=False)
    return conn


def init_db():
    conn = create_connection()
    cursor = conn.cursor()

    # User Table (for Login)
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
                        username TEXT PRIMARY KEY, 
                        password TEXT, 
                        role TEXT)''')

    # Marks Table (for Analytics)
    cursor.execute('''CREATE TABLE IF NOT EXISTS marks (
                        student_name TEXT, 
                        subject TEXT, 
                        score INTEGER, 
                        attendance INTEGER,
                        class_name TEXT)''')

    # Add a default admin and student if they don't exist
    cursor.execute("INSERT OR IGNORE INTO users VALUES ('admin', 'admin123', 'Teacher')")
    cursor.execute("INSERT OR IGNORE INTO users VALUES ('student', 'pass123', 'Student')")
    cursor.execute("INSERT OR IGNORE INTO users VALUES ('priya', 'priya123', 'Student')")
    cursor.execute("INSERT OR IGNORE INTO users VALUES ('rahul', 'rahul123', 'Student')")
    cursor.execute("INSERT OR IGNORE INTO users VALUES ('teacher_amit', 'amit456', 'Teacher')")


    conn.commit()
    conn.close()

def verify_user(username, password, role):
    conn = create_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE username=? AND password=? AND role=?", (username, password, role))
    result = cursor.fetchone()
    conn.close()
    return result is not None


# Helper function to get data as a DataFrame for Plotly charts
def get_marks_data():
    conn = create_connection()
    df = pd.read_sql_query("SELECT * FROM marks", conn)
    conn.close()
    return df