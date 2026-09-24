import os
import requests
from datetime import datetime, timedelta, timezone
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

# Recuperiamo il token di Telegram dalle variabili d'ambiente di Render
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")

# Database temporaneo in memoria per le note
note_database = [
    {
        "id": 1,
        "operatore": "Ivan",
        "data": "24/09/2026 - 18:35",
        "testo": "Avviato il sistema del diario di bordo. Test di visualizzazione della pergamena digitale."
    }
]

@app.route('/')
def index():
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
            # Calcoliamo l'ora italiana corretta (UTC + 2 ore a settembre per l'ora legale)
            orario_italiano = datetime.now(timezone.utc) + timedelta(hours=2)
            data_corrente = orario_italiano.strftime("%d/%m/%Y - %H:%M")
            
            nuova_nota = {
                "id": len(note_database) + 1,
                "operatore": user_name,
                "data": data_corrente,
                "testo": testo_nota
            }
            
            note_database.append(nuova_nota)
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
