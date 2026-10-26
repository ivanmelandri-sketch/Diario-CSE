import os
import re
import time
from datetime import datetime
import pytz
from flask import Flask, render_template_string, request, redirect, url_for, send_file
import requests
import psycopg2
import psycopg2.extras

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
DATABASE_URL = os.environ.get("DATABASE_URL")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ITALY_TZ = pytz.timezone("Europe/Rome")

PENDING_EDITS = {}

def get_db_connection():
    if DATABASE_URL:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        return conn, "postgres"
    else:
        import sqlite3
        db_file = os.path.join(BASE_DIR, "diario.db")
        conn = sqlite3.connect(db_file)
        conn.row_factory = sqlite3.Row
        return conn, "sqlite"

def init_db():
    conn, db_type = get_db_connection()
    cursor = conn.cursor()
    if db_type == "postgres":
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS entries (
                id SERIAL PRIMARY KEY,
                timestamp TEXT NOT NULL,
                operator TEXT NOT NULL,
                text TEXT NOT NULL
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS operators (
                chat_id BIGINT PRIMARY KEY,
                name TEXT NOT NULL,
                registered_at TEXT NOT NULL
            )
        ''')
    else:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                operator TEXT NOT NULL,
                text TEXT NOT NULL
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS operators (
                chat_id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                registered_at TEXT NOT NULL
            )
        ''')
    conn.commit()
    conn.close()

init_db()

def register_operator(chat_id, name):
    conn, db_type = get_db_connection()
    cursor = conn.cursor()
    now_str = datetime.now(ITALY_TZ).strftime("%d/%m/%Y %H:%M")
    try:
        if db_type == "postgres":
            cursor.execute(
                "INSERT INTO operators (chat_id, name, registered_at) VALUES (%s, %s, %s) ON CONFLICT (chat_id) DO UPDATE SET name = EXCLUDED.name",
                (chat_id, name, now_str)
            )
        else:
            cursor.execute(
                "INSERT OR REPLACE INTO operators (chat_id, name, registered_at) VALUES (?, ?, ?)",
                (chat_id, name, now_str)
            )
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()

def get_all_operators_chat_ids():
    conn, db_type = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT chat_id FROM operators")
    rows = cursor.fetchall()
    conn.close()
    if db_type == "postgres":
        return [row[0] for row in rows]
    else:
        return [row["chat_id"] for row in rows]

def load_entries(search_query=None):
    conn, db_type = get_db_connection()
    cursor = conn.cursor()
    
    if search_query:
        if db_type == "postgres":
            cursor.execute("SELECT timestamp, operator, text FROM entries WHERE text ILIKE %s OR operator ILIKE %s ORDER BY id DESC", (f"%{search_query}%", f"%{search_query}%"))
        else:
            cursor.execute("SELECT timestamp, operator, text FROM entries WHERE text LIKE ? OR operator LIKE ? ORDER BY id DESC", (f"%{search_query}%", f"%{search_query}%"))
    else:
        cursor.execute("SELECT timestamp, operator, text FROM entries ORDER BY id DESC")
        
    rows = cursor.fetchall()
    conn.close()
    
    if db_type == "postgres":
        return [{"timestamp": row[0], "operator": row[1], "text": row[2]} for row in rows]
    else:
        return [{"timestamp": row["timestamp"], "operator": row["operator"], "text": row["text"]} for row in rows]

def save_entry(timestamp, operator, text):
    conn, db_type = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO entries (timestamp, operator, text) VALUES (%s, %s, %s)" if db_type == "postgres" else "INSERT INTO entries (timestamp, operator, text) VALUES (?, ?, ?)", (timestamp, operator, text))
    conn.commit()
    conn.close()

def delete_entry_by_index(index):
    conn, db_type = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM entries ORDER BY id DESC")
    ids = [row[0] for row in cursor.fetchall()]
    if 0 <= index < len(ids):
        target_id = ids[index]
        cursor.execute("DELETE FROM entries WHERE id = %s" if db_type == "postgres" else "DELETE FROM entries WHERE id = ?", (target_id,))
        conn.commit()
    conn.close()

def advanced_local_cleaner(text):
    if not text:
        return ""
    cleaned = re.sub(r'\s+', ' ', text).strip()
    if not cleaned:
        return ""
    intro_pattern = r'^(allora|dunque|praticamente|insomma|cioè|aspetta|fammi pensare|dunque fammi pensare)[\s,]+'
    cleaned = re.sub(intro_pattern, '', cleaned, flags=re.IGNORECASE)
    interjections_pattern = r'\b(eh+|ah+|ehm+|mmh+|boh|mah|oh+)\b'
    cleaned = re.sub(interjections_pattern, '', cleaned, flags=re.IGNORECASE)
    bad_words = ['cazzo', 'merda', 'stronzo', 'stronza', 'vaffanculo', 'coglione', 'pirla', 'idiota', 'fanculo']
    for bw in bad_words:
        pattern = r'\b' + bw + r'\b'
        replacement = lambda m: m.group(0)[0] + '*' * (len(m.group(0)) - 2) + m.group(0)[-1] if len(m.group(0)) > 2 else '***'
        cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    if not cleaned:
        return text.strip()
    cleaned = cleaned[0].upper() + cleaned[1:]
    if cleaned[-1] not in ['.', '!', '?']:
        cleaned += '.'
    return cleaned

def process_with_gemini(text):
    if not text:
        return ""
    if not GEMINI_API_KEY:
        return advanced_local_cleaner(text)

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    headers = {"Content-Type": "application/json"}
    
    prompt = (
        "Sei un assistente di redazione per un team socio-educativo. "
        "Il tuo compito è prendere appunti rapidi e informali inviati via Telegram e trasformarli "
        "esclusivamente in un paragrafo descrittivo dell'attività svolta, "
        "scritto in modo chiaro, sintetico e professionale, ma con un tono naturale e scorrevole "
        "(evita termini eccessivamente burocratici o clinici). "
        "Regole tassative: "
        "1. Non inserire data, ora, intestazioni, firme o saluti nel testo. "
        "2. Non aggiungere frasi di chiusura. "
        "3. Restituisci unicamente il testo della descrizione pulita e sintetica."
    )

    payload = {
        "contents": [{"parts": [{"text": f"{prompt}\n\nTesto da elaborare:\n{text}"}]}]
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=15)
        if response.status_code == 200:
            res_json = response.json()
            candidates = res_json.get("candidates", [])
            if candidates:
                return candidates[0]["content"]["parts"][0]["text"].strip()
    except Exception:
        pass

    return advanced_local_cleaner(text)

PERGAMENA_HTML = """<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Diario Operativo</title>
    <style>
        body {
            background-color: #f4ecd8;
            font-family: 'Georgia', serif;
            color: #2c221e;
            margin: 0;
            padding: 15px;
            font-size: 16px;
        }
        .container {
            max-width: 850px;
            margin: 0 auto;
            background: #fff8eb;
            border: 2px solid #d4c3a3;
            box-shadow: 0 4px 15px rgba(0,0,0,0.1);
            padding: 20px;
            border-radius: 8px;
        }
        h1 {
            text-align: center;
            color: #5c4033;
            border-bottom: 2px solid #d4c3a3;
            padding-bottom: 15px;
            margin-bottom: 25px;
            font-size: 1.8em;
        }
        .entry {
            margin-bottom: 20px;
            padding: 15px;
            border-radius: 6px;
            border: 1px solid rgba(0,0,0,0.08);
            position: relative;
        }
        .entry-meta {
            font-size: 0.95em;
            color: #555;
            margin-bottom: 10px;
            font-weight: bold;
            display: flex;
            justify-content: space-between;
            flex-wrap: wrap;
            gap: 5px;
        }
        .entry-content {
            font-size: 1.15em;
            line-height: 1.6;
            white-space: pre-wrap;
            margin-bottom: 15px;
        }
        .entry-actions {
            display: flex;
            gap: 10px;
        }
        .btn-small {
            background-color: #8b5a2b;
            color: white;
            border: none;
            padding: 8px 14px;
            font-size: 0.95em;
            border-radius: 4px;
            cursor: pointer;
            text-decoration: none;
        }
        .btn-small:hover {
            background-color: #5c4033;
        }
        .btn-delete {
            background-color: #a94442;
        }
        .btn-delete:hover {
            background-color: #761c19;
        }
        .actions {
            text-align: center;
            margin-top: 30px;
            display: flex;
            justify-content: center;
            gap: 15px;
            flex-wrap: wrap;
        }
        .btn {
            background-color: #8b
