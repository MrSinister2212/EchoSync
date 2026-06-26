import sqlite3

def get_connection():
    conn = sqlite3.connect('echosync.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS stats (
            user_id TEXT PRIMARY KEY,
            songs_played INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()

def add_song_played(user_id: str):
    conn = get_connection()
    c = conn.cursor()
    c.execute('''
        INSERT INTO stats (user_id, songs_played)
        VALUES (?, 1)
        ON CONFLICT(user_id) DO UPDATE SET songs_played = songs_played + 1
    ''', (user_id,))
    conn.commit()
    conn.close()

def get_top_users(limit=10):
    conn = get_connection()
    c = conn.cursor()
    c.execute('SELECT user_id, songs_played FROM stats ORDER BY songs_played DESC LIMIT ?', (limit,))
    results = c.fetchall()
    conn.close()
    return results
