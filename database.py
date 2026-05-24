import os
import sqlite3
import hashlib
from flask import g

DATABASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'queue.db')


def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db


def close_db(exception):
    db = g.pop('db', None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DATABASE)
    db.execute("PRAGMA foreign_keys=ON")
    for col in ['next_number', 'instagram', 'facebook', 'youtube', 'whatsapp', 'phone', 'location', 'working_hours', 'hero_title', 'hero_desc']:
        try:
            db.execute(f"ALTER TABLE shops ADD COLUMN {col} TEXT")
        except sqlite3.OperationalError:
            pass
    db.executescript('''
        CREATE TABLE IF NOT EXISTS shops (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL DEFAULT 'Main Barbershop',
            is_open INTEGER NOT NULL DEFAULT 1,
            is_paused INTEGER NOT NULL DEFAULT 0,
            pause_reason TEXT,
            avg_haircut_minutes INTEGER NOT NULL DEFAULT 20,
            next_number INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shop_id INTEGER NOT NULL,
            customer_name TEXT NOT NULL,
            queue_number INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'waiting',
            position INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (shop_id) REFERENCES shops(id)
        );
        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    ''')
    cur = db.execute("SELECT COUNT(*) FROM shops")
    if cur.fetchone()[0] == 0:
        db.execute(
            "INSERT INTO shops (name, instagram, facebook, youtube, whatsapp, phone, location, working_hours, hero_title, hero_desc) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ('Main Barbershop', '', '', '', '', '', '', 'Mon-Fri 9:00-20:00 | Sat 10:00-18:00', 'The Art of\nthe Cut', 'Where precision meets style.')
        )
    cur = db.execute("SELECT COUNT(*) FROM admins")
    if cur.fetchone()[0] == 0:
        db.execute("INSERT INTO admins (username, password) VALUES (?, ?)",
                   ('admin', hash_password('admin123')))
    db.commit()
    db.close()
