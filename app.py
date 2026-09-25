import os
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# Usiamo TELEGRAM_TOKEN per coerenza
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN")
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
    
    user_text = message.get("text") or message.get("caption", "")

    if not user_text:
        send_telegram_message(chat_id, "Ho ricevuto il messaggio, ma è vuoto.")
        return jsonify({"status": "ok"}), 200

    # Elaborazione tramite Gemini con gestione del limite 429
    processed_text = process_with_gemini(user_text)

    # Invio del risultato su Telegram con i pulsanti
    send_message_with_buttons(chat_id, processed_text)

    return jsonify({"status": "ok"}), 200

def process_with_gemini(text):
    if not GEMINI_API_KEY:
        return text

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent?key={GEMINI_API_KEY}"
    headers = {"Content-Type": "application/json"}
    
    prompt = (
        "Sei un assistente professionale per la stesura di un diario di servizio/lavorativo. "
        "Prendi il seguente testo grezzo e formattalo in modo chiaro, "
        "strutturato, formale e professionale, correggendo eventuali errori:\n\n"
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
            return res_json["candidates"][0]["content"]["parts"][0]["text"]
        elif response.status_code == 429:
            # Errore 429: Troppe richieste, usiamo il testo originale come fallback
            return f"[⚠️ Limite richieste Gemini esaurito - Errore 429. Testo originale salvato]\n\n{text}"
        else:
            return f"[Errore API Gemini: {response.status_code}]\n\n{text}"
    except Exception as e:
        return f"[Errore di connessione a Gemini: {str(e)}]\n\n{text}"

def send_telegram_message(chat_id, text):
    url = f"{TELEGRAM_API_URL}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    requests.post(url, json=payload)

def send_message_with_buttons(chat_id, text):
    url = f"{TELEGRAM_API_URL}/sendMessage"
    
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
        "text": f"<b>Bozza:</b>\n\n{text}",
        "parse_mode": "HTML",
        "reply_markup": keyboard
    }
    requests.post(url, json=payload)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
