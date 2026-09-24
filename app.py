import os
import requests
from flask import Flask, request
from google import genai
from datetime import datetime

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
REPO_NAME = "ivanmelandri-sketch/Diario-CSE"
FILE_PATH = "diario.json"

TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# Memoria temporanea per le bozze in attesa di conferma (chat_id -> testo_nota)
pending_notes = {}
# Memoria per tracciare se l'utente ha cliccato "Modifica" (chat_id -> True/False)
waiting_for_edit = {}

def sintetizza_e_formalizza(testo_grezzo):
    """Usa Google Gemini per estrarre e formalizzare la sola descrizione dell'evento."""
    if not GEMINI_API_KEY:
        print("GEMINI_API_KEY mancante!")
        return testo_grezzo
        
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        prompt_sistema = (
            "Sei un assistente di redazione per un team socio-educativo. "
            "Il tuo compito è prendere appunti rapidi e informali inviati via Telegram e trasformarli "
            "esclusivamente in un paragrafo descrittivo dell'evento o dell'attività svolta, "
            "scritto con un tono formale e professionale. "
            "Regole tassative: "
            "1. Non inserire data, ora, intestazioni, firme o saluti nel testo. "
            "2. Non aggiungere frasi di chiusura (es. 'seguiranno aggiornamenti'). "
            "3. Restituisci unicamente il testo della descrizione pulita e sintetica."
        )
        
        # Tentativo con il modello standard
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=f"{prompt_sistema}\n\nTesto da elaborare:\n{testo_grezzo}"
        )
        
        if response and response.text:
            return response.text.strip()
            
    except Exception as e:
        print(f"ERRORE DI GEMINI: {str(e)}")
        # Tentativo di fallback con il modello di backup se il primo fallisce
        try:
            client = genai.Client(api_key=GEMINI_API_KEY)
            response = client.models.generate_content(
                model="gemini-3.8-flash",
                contents=f"Rendi questo testo formale e professionale, rimuovendo data, ora e saluti:\n{testo_grezzo}"
            )
            if response and response.text:
                return response.text.strip()
        except Exception as e2:
            print(f"ERRORE ANCHE NEL FALLBACK: {str(e2)}")
            
    # Se tutto fallisce, restituisce comunque una pulizia basilare anziché il testo grezzo identico
    return testo_grezzo.strip()

def leggi_diario_da_github():
    import base64
    import json
    url = f"https://api.github.com/repos/{REPO_NAME}/contents/{FILE_PATH}"
    headers = {"Authorization": f"Bearer {GITHUB_TOKEN}"}
    response = requests.get(url, headers=headers)
    
    if response.status_code == 200:
        file_data = response.json()
        content_encoded = file_data.get("content", "")
        sha = file_data.get("sha", "")
        decoded_bytes = base64.b64decode(content_encoded)
        diario_list = json.loads(decoded_bytes.decode('utf-8'))
        return diario_list, sha
    return [], None

def salva_diario_su_github(testo_nota, autore):
    import base64
    import json
    
    diario_list, sha = leggi_diario_da_github()
    
    timestamp = datetime.now().strftime("%d/%m/%Y alle %H:%M")
    entry = {
        "timestamp": timestamp,
        "autore": autore,
        "testo": testo_nota
    }
    
    diario_list.insert(0, entry)
    
    url = f"https://api.github.com/repos/{REPO_NAME}/contents/{FILE_PATH}"
    headers = {"Authorization": f"Bearer {GITHUB_TOKEN}", "Accept": "application/vnd.github+json"}
    
    updated_content_bytes = json.dumps(diario_list, indent=4, ensure_ascii=False).encode('utf-8')
    encoded_content = base64.b64encode(updated_content_bytes).decode('utf-8')
    
    data = {
        "message": "Aggiunta nota di diario confermata",
        "content": encoded_content,
        "sha": sha
    }
    
    response = requests.put(url, headers=headers, json=data)
    return response.status_code in [200, 201]

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    
    # 1. Gestione dei click sui pulsanti interattivi (Callback Query)
    if 'callback_query' in data:
        callback = data['callback_query']
        chat_id = callback['message']['chat']['id']
        message_id = callback['message']['message_id']
        data_azione = callback['data']
        
        user_info = callback.get('from', {})
        nome = user_info.get('first_name', 'Ivan')
        cognome = user_info.get('last_name', '')
        autore = f"{nome} {cognome}".strip() or "Ivan"
        
        if data_azione == "btn_ok":
            if chat_id in pending_notes:
                testo_da_salvare = pending_notes[chat_id]
                successo = salva_diario_su_github(testo_da_salvare, autore)
                
                del pending_notes[chat_id]
                waiting_for_edit.pop(chat_id, None)
                
                risposta_testo = "Nota pubblicata ufficialmente sulla pergamena! ✨" if successo else "Errore durante il salvataggio."
            else:
                risposta_testo = "Nessuna nota in sospeso trovata."
                
            # Aggiorna il messaggio Telegram rimuovendo i pulsanti
            requests.post(f"{TELEGRAM_API_URL}/editMessageText", json={
                "chat_id": chat_id,
                "message_id": message_id,
                "text": f"✅ {risposta_testo}"
            })
            
        elif data_azione == "btn_modifica":
            waiting_for_edit[chat_id] = True
            requests.post(f"{TELEGRAM_API_URL}/editMessageText", json={
                "chat_id": chat_id,
                "message_id": message_id,
                "text": "✏️ Scrivi qui sotto il testo modificato che vuoi pubblicare:"
            })
            
        return "OK", 200

    # 2. Gestione dei messaggi di testo normali
    if 'message' in data and 'text' in data['message']:
        chat_id = data['message']['chat']['id']
        testo_ricevuto = data['message']['text']
        
        user_info = data['message'].get('from', {})
        nome = user_info.get('first_name', 'Ivan')
        cognome = user_info.get('last_name', '')
        autore = f"{nome} {cognome}".strip() or "Ivan"

        # Se l'utente aveva cliccato "Modifica" e ora sta inviando il testo corretto
        if chat_id in waiting_for_edit and waiting_for_edit[chat_id]:
            waiting_for_edit[chat_id] = False
            pending_notes[chat_id] = testo_ricevuto
            
            # Rimandiamo la bozza aggiornata con i pulsanti
            keyboard = {
                "inline_keyboard": [
                    [
                        {"text": "✅ Pubblica (OK)", "callback_data": "btn_ok"},
                        {"text": "✏️ Modifica (M)", "callback_data": "btn_modifica"}
                    ]
                ]
            }
            requests.post(f"{TELEGRAM_API_URL}/sendMessage", json={
                "chat_id": chat_id,
                "text": f"Ecco la nota aggiornata:\n\n\"{testo_ricevuto}\"\n\nCosa vuoi fare?",
                "reply_markup": keyboard
            })
            return "OK", 200

        # Altrimenti, elaboriamo una nuova nota grezza con Gemini
        testo_professionale = sintetizza_e_formalizza(testo_ricevuto)
        pending_notes[chat_id] = testo_professionale
        
        # Creazione della tastiera con i due pulsanti interattivi
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "✅ Pubblica (OK)", "callback_data": "btn_ok"},
                    {"text": "✏️ Modifica (M)", "callback_data": "btn_modifica"}
                ]
            ]
        }
        
        requests.post(f"{TELEGRAM_API_URL}/sendMessage", json={
            "chat_id": chat_id,
            "text": f"Bozza elaborata:\n\n\"{testo_professionale}\"",
            "reply_markup": keyboard
        })
        
    return "OK", 200

@app.route('/')
def home():
    diario_list, _ = leggi_diario_da_github()
    
    html = """
    <!DOCTYPE html>
    <html lang="it">
    <head>
        <meta charset="UTF-8">
        <title>Diario CSE</title>
        <style>
            body { font-family: Georgia, serif; background: #f4ecd8; color: #2c221e; max-width: 800px; margin: 40px auto; padding: 20px; }
            h1 { text-align: center; border-bottom: 2px solid #bfa181; padding-bottom: 10px; margin-bottom: 30px; }
            .note { background: #fffaf0; border-left: 4px solid #8b5a2b; padding: 15px; margin-bottom: 20px; box-shadow: 2px 2px 5px rgba(0,0,0,0.05); }
            .meta { font-size: 0.85em; color: #7f6a55; margin-bottom: 8px; font-weight: bold; border-bottom: 1px dashed #e6d7be; padding-bottom: 4px; }
            .text { font-size: 1.05em; line-height: 1.5; }
        </style>
    </head>
    <body>
        <h1>Diario Digitale CSE</h1>
        <div id="notes-container">
    """
    for entry in diario_list:
        html += f"""
            <div class="note">
                <div class="meta">Inserito da {entry.get('autore', 'Ivan')} il {entry.get('timestamp', '')}</div>
                <div class="text">{entry.get('testo', '')}</div>
            </div>
        """
    html += """
        </div>
    </body>
    </html>
    """
    return html

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
