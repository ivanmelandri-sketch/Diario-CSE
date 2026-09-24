import os
import requests
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
    print("Dati ricevuti da Telegram:", data)
    
    # Verifichiamo se c'è un messaggio
    if "message" in data:
        message = data["message"]
        chat_id = message["chat"]["id"]
        user_name = message["from"].get("first_name", "Operatore")
        
        # Se un'operatrice manda un testo o un vocale al bot
        if "text" in message:
            text_received = message["text"]
            invia_messaggio_telegram(chat_id, f"Ciao {user_name}! Ho ricevuto il tuo testo: '{text_received}'")
        elif "voice" in message:
            invia_messaggio_telegram(chat_id, f"Ciao {user_name}! Ho ricevuto il tuo vocale. (Presto lo trascriveremo e pubblicheremo sul diario).")
            
    return jsonify({"status": "ok"})

def invia_messaggio_telegram(chat_id, testo):
    if not TELEGRAM_TOKEN:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": testo}
    requests.post(url, json=payload)

@app.route('/set_webhook', methods=['GET'])
def set_webhook():
    # Questa pagina collega automaticamente Telegram al nostro sito su Render
    render_url = request.host_url.rstrip('/') + '/webhook'
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook?url={render_url}"
    response = requests.get(url)
    return jsonify(response.json())

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
