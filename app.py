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
        body { background-color: #f4ecd8; font-family: 'Georgia', serif; color: #2c221e; margin: 0; padding: 15px; font-size: 16px; }
        .container { max-width: 850px; margin: 0 auto; background: #fff8eb; border: 2px solid #d4c3a3; box-shadow: 0 4px 15px rgba(0,0,0,0.1); padding: 20px; border-radius: 8px; }
        h1 { text-align: center; color: #5c4033; border-bottom: 2px solid #d4c3a3; padding-bottom: 15px; margin-bottom: 25px; font-size: 1.8em; }
        .entry { margin-bottom: 20px; padding: 15px; border-radius: 6px; border: 1px solid rgba(0,0,0,0.08); position: relative; }
        .entry-meta { font-size: 0.95em; color: #555; margin-bottom: 10px; font-weight: bold; display: flex; justify-content: space-between; flex-wrap: wrap; gap: 5px; }
        .entry-content { font-size: 1.15em; line-height: 1.6; white-space: pre-wrap; margin-bottom: 15px; }
        .entry-actions { display: flex; gap: 10px; }
        .btn-small { background-color: #8b5a2b; color: white; border: none; padding: 8px 14px; font-size: 0.95em; border-radius: 4px; cursor: pointer; text-decoration: none; }
        .btn-small:hover { background-color: #5c4033; }
        .btn-delete { background-color: #a94442; }
        .btn-delete:hover { background-color: #761c19; }
        .actions { text-align: center; margin-top: 30px; display: flex; justify-content: center; gap: 15px; flex-wrap: wrap; }
        .btn { background-color: #8b5a2b; color: white; padding: 12px 20px; text-decoration: none; border-radius: 4px; font-family: sans-serif; font-weight: bold; font-size: 1em; }
        .btn:hover { background-color: #5c4033; }
        @media (max-width: 600px) { body { padding: 5px; } .container { padding: 12px; } .entry-content { font-size: 1.2em; } .btn, .btn-small { padding: 10px 16px; font-size: 1em; } }
    </style>
    <script>
        function copyText(id) {
            const text = document.getElementById('content-' + id).innerText;
            navigator.clipboard.writeText(text).then(() => { alert('Testo copiato negli appunti!'); });
        }
    </script>
</head>
<body>
    <div class="container">
        <h1>Diario Operativo</h1>
        <form method="GET" action="/" style="text-align: center; margin-bottom: 25px;">
            <input type="text" name="q" value="{{ search_query if search_query else '' }}" placeholder="Cerca nome utente o parola chiave..." style="padding: 10px; width: 60%; max-width: 350px; border: 1px solid #d4c3a3; border-radius: 4px; background: #fff; font-family: 'Georgia', serif; font-size: 1em;">
            <button type="submit" class="btn-small" style="padding: 10px 15px; margin-left: 5px;">Filtra</button>
            {% if search_query %}
                <a href="/" class="btn-small btn-delete" style="text-decoration: none; padding: 10px 15px; margin-left: 5px; display: inline-block;">Annulla</a>
            {% endif %}
        </form>
        {% if entries %}
            {% for entry in entries %}
                {% set colors = ['#fcf8e3', '#d9edf7', '#dff0d8', '#f2dede', '#fcf8e3', '#e8f4f8'] %}
                {% set color_idx = entry.operator | string | length % colors | length %}
                <div class="entry" style="background-color: {{ colors[color_idx] }};">
                    <div class="entry-meta">
                        <span>👤 <b>{{ entry.operator }}</b></span>
                        <span>📅 {{ entry.timestamp }}</span>
                    </div>
                    <div class="entry-content" id="content-{{ loop.index0 }}">{{ entry.text }}</div>
                    <div class="entry-actions">
                        <button class="btn-small" onclick="copyText('{{ loop.index0 }}')">Copia</button>
                        <a href="/delete/{{ loop.index0 }}" class="btn-small btn-delete" onclick="return confirm('Eliminare questa voce?');">Elimina</a>
                    </div>
                </div>
            {% endfor %}
        {% else %}
            <p style="text-align: center; color: #7f6e62; font-size: 1.1em;">Nessuna voce registrata nel diario.</p>
        {% endif %}
        <div class="actions">
            <a href="/export-word{% if search_query %}?q={{ search_query }}{% endif %}" class="btn">Stampa Fascicolo (.doc)</a>
            <a href="/export{% if search_query %}?q={{ search_query }}{% endif %}" class="btn">Scarica Backup (.txt)</a>
        </div>
    </div>
</body>
</html>"""

@app.route("/")
def index():
    search_query = request.args.get("q", "").strip()
    entries = load_entries(search_query if search_query else None)
    return render_template_string(PERGAMENA_HTML, entries=entries, search_query=search_query)

@app.route("/delete/<int:index>")
def delete_entry(index):
    delete_entry_by_index(index)
    return redirect(url_for('index'))

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json(silent=True)
        if not data:
            return "OK", 200

        if "callback_query" in data:
            cq = data["callback_query"]
            callback_data = cq.get("data")
            message = cq.get("message", {})
            chat_id = message.get("chat", {}).get("id")
            message_id = message.get("message_id")
            operator_name = cq.get("from", {}).get("first_name", "Operatore")
            
            if chat_id:
                register_operator(chat_id, operator_name)
            
            raw_text = message.get("text", "")
            text_to_save = raw_text
            if "BOZZA ELABORATA:" in raw_text:
                text_to_save = raw_text.split("BOZZA ELABORATA:")[-1].strip()
            text_to_save = text_to_save.strip()

            if callback_data == "confirm_ok" and chat_id:
                PENDING_EDITS.pop(chat_id, None)
                now_italy = datetime.now(ITALY_TZ).strftime("%d/%m/%Y %H:%M")
                
                if text_to_save:
                    save_entry(now_italy, operator_name, text_to_save)
                
                url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageText"
                requests.post(url, json={
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "text": f"✅ PUBBLICATO CON SUCCESSO DA {operator_name.upper()}:\n\n{text_to_save}"
                })
                
                all_operators = get_all_operators_chat_ids()
                notif_text = f"🔔 **Nuova voce pubblicata nel Diario Operativo!**\n👤 Operatore: {operator_name}\n📅 Data: {now_italy}\n\n\"{text_to_save}\""
                
                for op_chat_id in all_operators:
                    notif_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
                    try:
                        requests.post(notif_url, json={
                            "chat_id": op_chat_id,
                            "text": notif_text,
                            "parse_
