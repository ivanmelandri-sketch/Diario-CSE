import os
import requests
import base64
import json
from datetime import datetime, timedelta, timezone
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "ivanmelandri-sketch/Diario-CSE")
FILE_PATH = "diario.json"

def leggi_note_da_github():
    if not GITHUB_TOKEN:
        return [{"id": 1, "operatore": "Sistema", "data": "24/09/2026 - 18:35", "testo": "Avviato il sistema."}]
    
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{FILE_PATH}"
    headers = {"Authorization": f"Bearer {GITHUB_TOKEN}", "Accept": "application/vnd.github+json"}
    response = requests.get(url, headers=headers)
    
    if response.status_code == 200:
        try:
            file_content = response.json()
            decoded_bytes = base64.b64decode(file_content["content"])
            return json.loads(decoded_bytes.decode("utf-8"))
        except Exception:
            return [{"id": 1, "operatore": "Sistema", "data": "24/09/2026 - 18:35", "testo": "Avviato il sistema."}]
    else:
        return [{"id": 1, "operatore": "Sistema", "data": "24/09/2026 - 18:35", "testo": "Avviato il sistema."}]

def salva_nota_su_github(nuova_nota):
    if not GITHUB_TOKEN:
        return
    
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{FILE_PATH}"
    headers = {"Authorization": f"Bearer {GITHUB_TOKEN}", "Accept": "application/vnd.github+json"}
    
    response = requests.get(url, headers=headers)
    note_esistenti = []
    sha = None
    
    if response.status_code == 200:
        try:
            file_data = response.json()
            sha = file_data["sha"]
            decoded_bytes = base64.b64decode(file_data["content"])
            note_esistenti = json.loads(decoded_bytes.decode("utf-8"))
        except Exception:
            note_esistenti = []
            
    note_esistenti.append(nuova_nota)
    
    nuovo_contenuto_str = json.dumps(note_esistenti, indent=4, ensure_ascii=False)
    content_encoded = base64.b64encode(nuovo_contenuto_str.encode("utf-8")).decode("utf-8")
    
    payload = {
        "message": f"Aggiunta nuova nota di {nuova_nota['operatore']}",
        "content": content_encoded
    }
    if sha:
        payload["sha"] = sha
        
    requests.put(url, headers=headers, json=payload)

@app.route('/')
def index():
    note_database = leggi_note_da_github()
    return render_template('index.html', notes=note_database[::-1])

@app.route('/webhook', methods=['POST'])
def telegram_webhook():
    data = request.json
    
    if "message" in data:
        message = data["message"]
        chat_id = message["chat"]["id"]
        user_name = message["from"].get("first_name", "Operatore")
        
        testo_nota = ""
        if "text" in message:
            testo_nota = message["text"]
        elif "voice" in message:
            testo_nota = "[Messaggio Vocale registrato da équipe]"
            
        if testo_nota:
            orario_italiano = datetime.now(timezone.utc) + timedelta(hours=2)
            data_corrente = orario_italiano.strftime("%d/%m/%Y - %H:%M")
            
            note_attuali = leggi_note_da_github()
            nuova_nota = {
                "id": len(note_attuali) + 1,
                "operatore": user_name,
                "data": data_corrente,
                "testo": testo_nota
            }
            
            salva_nota_su_github(nuova_nota)
            invia_messaggio_telegram(chat_id, f"✅ Nota pubblicata con successo sul diario, {user_name}!")
        else:
            invia_messaggio_telegram(chat_id, "Invia un testo o un vocale da aggiungere al diario.")
            
    return jsonify({"status": "ok"})

def invia_messaggio_telegram(chat_id, testo):
    if not TELEGRAM_TOKEN:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": testo}
    requests.post(url, json=payload)

@app.route('/set_webhook', methods=['GET'])
def set_webhook():
    render_url = request.host_url.rstrip('/') + '/webhook'
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook?url={render_url}"
    response = requests.get(url)
    return jsonify(response.json())

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
