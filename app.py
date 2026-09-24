import os
import requests
from datetime import datetime
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

# Recuperiamo il token di Telegram dalle variabili d'ambiente di Render
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")

# Database temporaneo in memoria per le note (con la nota di benvenuto iniziale)
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
    # Mostra la pagina web passando le note in ordine cronologico inverso (ultime in cima)
    return render_template('index.html', notes=note_database[::-1])

@app.route('/webhook', methods=['POST'])
def telegram_webhook():
    data = request.json
    print("Dati ricevuti da Telegram:", data)
    
    if "message" in data:
        message = data["message"]
        chat_id = message["chat"]["id"]
        user_name = message["from"].get("first_name", "Operatore")
        
        testo_nota = ""
        
        # Se l'utente manda un testo
        if "text" in message:
            testo_nota = message["text"]
            
        # Se l'utente manda un vocale (per ora registriamo la ricezione del vocale in attesa del modulo IA)
        elif "voice" in message:
            testo_nota = "[Messaggio Vocale registrato da équipe]"
            
        if testo_nota:
            # Creiamo la nuova nota da aggiungere al diario
            data_corrente = datetime.now().strftime("%d/%m/%Y - %H:%M")
            nuova_nota = {
                "id": len(note_database) + 1,
                "operatore": user_name,
                "data": data_corrente,
                "testo": testo_nota
            }
            
            # La aggiungiamo al nostro database temporaneo
            note_database.append(nuova_nota)
            
            # Confermiamo all'operatore su Telegram
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
