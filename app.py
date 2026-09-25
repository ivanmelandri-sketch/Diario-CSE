import os
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# Recupera le credenziali dalle variabili d'ambiente di Render
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

@app.route("/", methods=["GET"])
def home():
    return "Il server del diario è online e attivo!", 200

@app.route("/webhook", methods=["POST"])
def telegram_webhook():
    data = request.get_json()
    
    if not data or "message" not in data:
        return jsonify({"status": "ok"}), 200

    message = data["message"]
    chat_id = message["chat"]["id"]
    
    # Estrae il testo del messaggio (o la didascalia se è un media)
    user_text = message.get("text") or message.get("caption", "")

    if not user_text:
        send_telegram_message(chat_id, "Ho ricevuto il messaggio, ma è vuoto o non contiene testo leggibile.")
        return jsonify({"status": "ok"}), 200

    # Elaborazione tramite Gemini (usando gemini-3.8-flash)
    processed_text = process_with_gemini(user_text)

    # Invio del risultato su Telegram con i pulsanti di conferma/modifica
    send_message_with_buttons(chat_id, processed_text)

    return jsonify({"status": "ok"}), 200

def process_with_gemini(text):
    if not GEMINI_API_KEY:
        # Fallback se la chiave non è configurata
        return f"[Modalità Fallback - Chiave mancante]\n\n{text}"

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent?key={GEMINI_API_KEY}"
    
    headers = {"Content-Type": "application/json"}
    
    # Prompt di sistema / istruzioni per la formattazione
    prompt = (
        "Sei un assistente professionale per la stesura di un diario di servizio/lavorativo. "
        "Prendi il seguente testo grezzo (dettato o appuntato) e formattalo in modo chiaro, "
        "strutturato, formale e professionale, correggendo eventuali errori di trascrizione:\n\n"
        f"{text}"
    )

    payload = {
        "contents": [{
            "parts": [{"text": prompt}]
        }]
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=15)
        if response.status_code == 200:
            res_json = response.json()
            # Estrae la risposta generata da Gemini
            ai_text = res_json["candidates"][0]["content"]["parts"][0]["text"]
            return ai_text
        else:
            return f"[Errore API Gemini: {response.status_code}]\n\n{text}"
    except Exception as e:
        return f"[Errore di connessione a Gemini: {str(e)}]\n\n{text}"

def send_telegram_message(chat_id, text):
    url = f"{TELEGRAM_API_URL}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text
    }
    requests.post(url, json=payload)

def send_message_with_buttons(chat_id, text):
    url = f"{TELEGRAM_API_URL}/sendMessage"
    
    # Inline keyboard con i pulsanti di gestione bozza
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "✅ Conferma e Salva", "callback_data": "save_entry"},
                {"text": "✏️ Modifica", "callback_data": "edit_entry"}
            ],
            [
                {"text": "❌ Annulla", "callback_data": "cancel_entry"}
            ]
        ]
    }

    payload = {
        "chat_id": chat_id,
        "text": f"<b>Bozza elaborata:</b>\n\n{text}",
        "parse_mode": "HTML",
        "reply_markup": keyboard
    }
    requests.post(url, json=payload)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
