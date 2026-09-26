import os
import json
import re
import time
from datetime import datetime
import pytz
from flask import Flask, render_template_string, request, redirect, url_for, send_file
import requests

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# Percorso assoluto sicuro per garantire la persistenza dei dati sul server
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, "diario.json")

ITALY_TZ = pytz.timezone("Europe/Rome")

def load_entries():
    if not os.path.exists(DATA_FILE):
        return []
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_entries(entries):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=4)

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
    if not GEMINI_API_KEY:
        return advanced_local_cleaner(text)

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent?key={GEMINI_API_KEY}"
    headers = {"Content-Type": "application/json"}
    
    prompt = (
        "Sei un assistente di redazione per un team socio-educativo. "
        "Il tuo compito è prendere appunti rapidi e informali inviati via Telegram e trasformarli "
        "esclusivamente in un paragrafo descrittivo dell'evento o dell'attività svolta, "
        "scritto con un tono formale e professionale. "
        "Regole tassative: "
        "1. Non inserire data, ora, intestazioni, firme o saluti nel testo. "
        "2. Non aggiungere frasi di chiusura. "
        "3. Restituisci unicamente il testo della descrizione pulita e sintetica."
    )

    payload = {
        "contents": [{"parts": [{"text": f"{prompt}\n\nTesto da elaborare:\n{text}"}]}]
    }

    max_retries = 10
    retry_delay = 3

    for attempt in range(1, max_retries + 1):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=15)
            if response.status_code == 200:
                res_json = response.json()
                return res_json["candidates"][0]["content"]["parts"][0]["text"].strip()
            elif response.status_code in [429, 503]:
                if attempt < max_retries:
                    time.sleep(retry_delay)
                    continue
            else:
                break
        except Exception:
            if attempt < max_retries:
                time.sleep(retry_delay)
                continue

    return advanced_local_cleaner(text)

PERGAMENA_HTML = """
<!DOCTYPE html>
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
            background-color: #8b5a2b;
            color: white;
            padding: 12px 20px;
            text-decoration: none;
            border-radius: 4px;
            font-family: sans-serif;
            font-weight: bold;
            font-size: 1em;
        }
        .btn:hover {
            background-color: #5c4033;
        }

        /* Ottimizzazione specifica per smartphone */
        @media (max-width: 600px) {
            body {
                padding: 5px;
            }
            .container {
                padding: 12px;
            }
            .entry-content {
                font-size: 1.2em;
            }
            .btn, .btn-small {
                padding: 10px 16px;
                font-size: 1em;
            }
        }
    </style>
    <script>
        function copyText(id) {
            const text = document.getElementById('content-' + id).innerText;
            navigator.clipboard.writeText(text).then(() => {
                alert('Testo copiato negli appunti!');
            });
        }
    </script>
</head>
<body>
    <div class="container">
        <h1>Diario Operativo</h1>
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
            <a href="/export-word" class="btn">Scarica Backup (.doc)</a>
            <a href="/export" class="btn">Scarica Backup (.txt)</a>
        </div>
    </div>
</body>
</html>
"""

@app.route("/")
def index():
    entries = load_entries()
    return render_template_string(PERGAMENA_HTML, entries=entries)

@app.route("/delete/<int:index>")
def delete_entry(index):
    entries = load_entries()
    if 0 <= index < len(entries):
        entries.pop(index)
        save_entries(entries)
    return redirect(url_for('index'))

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    if not data:
        return "OK", 200

    if "callback_query" in data:
        cq = data["callback_query"]
        callback_data = cq.get("data")
        message = cq.get("message", {})
        chat_id = message.get("chat", {}).get("id")
        message_id = message.get("message_id")
        
        raw_text = message.get("text", "")
        for prefix in ["BOZZA ELABORATA:\n\n", "✏️ MODIFICA - Invia la correzione o usa questo testo:\n\n"]:
            if raw_text.startswith(prefix):
                raw_text = raw_text.replace(prefix, "")
        text_to_save = raw_text.strip()
        
        operator_name = cq.get("from", {}).get("first_name", "Operatore")
        
        if callback_data == "confirm_ok" and chat_id:
            now_italy = datetime.now(ITALY_TZ).strftime("%d/%m/%Y %H:%M")
            entries = load_entries()
            entries.insert(0, {"timestamp": now_italy, "operator": operator_name, "text": text_to_save})
            save_entries(entries)
            
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageText"
            requests.post(url, json={
                "chat_id": chat_id,
                "message_id": message_id,
                "text": f"✅ PUBBLICATO CON SUCCESSO DA {operator_name.upper()}:\n\n{text_to_save}"
            })
            
        elif callback_data == "edit_mode" and chat_id:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageText"
            keyboard = {
                "inline_keyboard": [
                    [{"text": "✅ Conferma Testo Modificato", "callback_data": "confirm_ok"}]
                ]
            }
            requests.post(url, json={
                "chat_id": chat_id,
                "message_id": message_id,
                "text": f"✏️ MODIFICA - Invia la correzione o usa questo testo:\n\n{text_to_save}",
                "reply_markup": keyboard
            })
            
        return "OK", 200

    if "message" in data and "text" in data["message"]:
        message = data["message"]
        chat_id = message.get("chat", {}).get("id")
        incoming_text = message.get("text")
        operator_name = message.get("from", {}).get("first_name", "Operatore")
        
        if not chat_id or not incoming_text:
            return "OK", 200
            
        if incoming_text.startswith("/"):
            return "OK", 200
            
        processed_text = process_with_gemini(incoming_text)
        
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "✅ Pubblica (OK)", "callback_data": "confirm_ok"},
                    {"text": "✏️ Modifica (M)", "callback_data": "edit_mode"}
                ]
            ]
        }
        
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": f"BOZZA ELABORATA:\n\n{processed_text}",
            "reply_markup": keyboard
        }
        try:
            requests.post(url, json=payload, timeout=40)
        except Exception:
            pass

    return "OK", 200

@app.route("/export-word")
def export_word():
    entries = load_entries()
    html_content = "<html xmlns:o='urn:schemas-microsoft-com:office:office' xmlns:w='urn:schemas-microsoft-com:office:word' xmlns='http://www.w3.org/TR/REC-html40'>"
    html_content += "<head><meta charset='utf-8'><title>Diario Operativo</title></head><body>"
    html_content += "<h1>Diario Operativo - Backup</h1>"
    for entry in entries:
        html_content += f"<p><b>Operatore:</b> {entry.get('operator', 'N/D')} | <b>Data:</b> {entry['timestamp']}</p>"
        html_content += f"<p>{entry['text']}</p><hr/>"
    html_content += "</body></html>"
    
    export_path = os.path.join(BASE_DIR, "backup_diario.doc")
    with open(export_path, "w", encoding="utf-8") as f:
        f.write(html_content)
        
    return send_file(export_path, as_attachment=True, download_name="diario_operativo.doc")

@app.route("/export")
def export():
    entries = load_entries()
    content = ""
    for entry in entries:
        content += f"[{entry['timestamp']}] - Operatore: {entry.get('operator', 'N/D')}\n{entry['text']}\n\n" + "-"*40 + "\n\n"
    
    export_path = os.path.join(BASE_DIR, "backup_diario.txt")
    with open(export_path, "w", encoding="utf-8") as f:
        f.write(content)
        
    return send_file(export_path, as_attachment=True)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
