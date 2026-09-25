import os
import json
from datetime import datetime
import pytz
from flask import Flask, render_template_string, request, redirect, url_for, send_file
import requests

app = Flask(__name__)

# Configurazioni token e chiavi dalle variabili d'ambiente di Render
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

DATA_FILE = "diario.json"
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

def process_with_gemini(text):
    if not GEMINI_API_KEY:
        print("DEBUG GEMINI: Chiave API mancante!")
        return text

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent?key={GEMINI_API_KEY}"
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
        "contents": [{
            "parts": [{"text": f"{prompt}\n\nTesto da elaborare:\n{text}"}]
        }]
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=15)
        print(f"DEBUG GEMINI Status: {response.status_code}")
        print(f"DEBUG GEMINI Response: {response.text}")
        
        if response.status_code == 200:
            res_json = response.json()
            return res_json["candidates"][0]["content"]["parts"][0]["text"].strip()
        elif response.status_code == 429:
            cleaned = text.strip()
            return cleaned[0].upper() + cleaned[1:] if cleaned else text
        else:
            return text
    except Exception as e:
        print(f"DEBUG GEMINI Exception: {str(e)}")
        return text

# Template HTML della pergamena
PERGAMENA_HTML = """
<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="UTF-8">
    <title>Diario Operativo</title>
    <style>
        body {
            background-color: #f4ecd8;
            font-family: 'Georgia', serif;
            color: #2c221e;
            margin: 0;
            padding: 20px;
        }
        .container {
            max-width: 800px;
            margin: 0 auto;
            background: #fff8eb;
            border: 2px solid #d4c3a3;
            box-shadow: 0 4px 15px rgba(0,0,0,0.1);
            padding: 40px;
            border-radius: 8px;
        }
        h1 {
            text-align: center;
            color: #5c4033;
            border-bottom: 2px solid #d4c3a3;
            padding-bottom: 15px;
            margin-bottom: 30px;
        }
        .entry {
            margin-bottom: 25px;
            padding-bottom: 20px;
            border-bottom: 1px dashed #d4c3a3;
        }
        .entry-meta {
            font-size: 0.85em;
            color: #7f6e62;
            margin-bottom: 5px;
        }
        .entry-content {
            font-size: 1.1em;
            line-height: 1.6;
            white-space: pre-wrap;
        }
        .actions {
            text-align: center;
            margin-top: 30px;
        }
        .btn {
            background-color: #8b5a2b;
            color: white;
            padding: 10px 20px;
            text-decoration: none;
            border-radius: 4px;
            font-family: sans-serif;
            font-weight: bold;
        }
        .btn:hover {
            background-color: #5c4033;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Diario Operativo</h1>
        {% if entries %}
            {% for entry in entries %}
                <div class="entry">
                    <div class="entry-meta">📅 {{ entry.timestamp }}</div>
                    <div class="entry-content">{{ entry.text }}</div>
                </div>
            {% endfor %}
        {% else %}
            <p style="text-align: center; color: #7f6e62;">Nessuna voce registrata nel diario.</p>
        {% endif %}
        
        <div class="actions">
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

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    
    if not data:
        return "OK", 200

    # Gestione dei pulsanti inline (callback_query)
    if "callback_query" in data:
        cq = data["callback_query"]
        callback_data = cq.get("data")
        message = cq.get("message", {})
        chat_id = message.get("chat", {}).get("id")
        message_id = message.get("message_id")
        text_to_save = message.get("text", "").replace("BOZZA ELABORATA:\n\n", "").strip()
        
        if callback_data == "confirm_ok" and chat_id:
            now_italy = datetime.now(ITALY_TZ).strftime("%d/%m/%Y %H:%M")
            entries = load_entries()
            entries.insert(0, {"timestamp": now_italy, "text": text_to_save})
            save_entries(entries)
            
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageText"
            requests.post(url, json={
                "chat_id": chat_id,
                "message_id": message_id,
                "text": f"✅ PUBBLICATO CON SUCCESSO:\n\n{text_to_save}"
            })
            
        elif callback_data == "edit_mode" and chat_id:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageText"
            requests.post(url, json={
                "chat_id": chat_id,
                "message_id": message_id,
                "text": f"✏️ MODIFICA:\n\nInvia la versione corretta del testo come messaggio."
            })
            
        return "OK", 200

    # Gestione messaggi di testo normali
    if "message" in data and "text" in data["message"]:
        message = data["message"]
        chat_id = message.get("chat", {}).get("id")
        incoming_text = message.get("text")
        
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
            res = requests.post(url, json=payload, timeout=10)
            print("Risposta invio Telegram:", res.status_code, res.text)
        except Exception as e:
            print("Errore invio Telegram:", str(e))

    return "OK", 200

@app.route("/export")
def export():
    entries = load_entries()
    content = ""
    for entry in entries:
        content += f"[{entry['timestamp']}]\n{entry['text']}\n\n" + "-"*40 + "\n\n"
    
    export_path = "backup_diario.txt"
    with open(export_path, "w", encoding="utf-8") as f:
        f.write(content)
        
    return send_file(export_path, as_attachment=True)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
