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

# Memoria temporanea per la nota in attesa di conferma (chat_id -> dati_nota)
pending_notes = {}

def sintetizza_e_formalizza(testo_grezzo):
    if not GEMINI_API_KEY:
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
        
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=f"{prompt_sistema}\n\nTesto da elaborare:\n{testo_grezzo}"
        )
        
        if response and response.text:
            return response.text.strip()
    except Exception as e:
        print(f"ERRORE DI GEMINI: {str(e)}")
        
    return testo_grezzo

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
    if 'message' in data and 'text' in data['message']:
        chat_id = data['message']['chat']['id']
        testo_ricevuto = data['message']['text']
        
        user_info = data['message'].get('from', {})
        # Se non c'è il nome su Telegram, usa "Ivan" come default
        nome = user_info.get('first_name', 'Ivan')
        cognome = user_info.get('last_name', '')
        autore = f"{nome} {cognome}".strip()
        if not autore:
            autore = "Ivan"

        # Se l'utente risponde con "ok" o "conferma" e ha una nota in sospeso, la pubblichiamo
        if chat_id in pending_notes and testo_ricevuto.lower() in ["ok", "conferma", "pubblica", "sì", "si"]:
            nota_da_salvare = pending_notes[chat_id]
            successo = salva_diario_su_github(nota_da_salvare, autore)
            
            del pending_notes[chat_id] # ripuliamo la memoria
            
            if successo:
                msg_risposta = "Nota pubblicata ufficialmente sulla pergamena! ✨"
            else:
                msg_risposta = "Errore durante il salvataggio su GitHub."

        elif chat_id in pending_notes and testo_ricevuto.lower().startswith("modifica:"):
            # L'utente ha scritto "modifica: [nuovo testo]"
            nuovo_testo = testo_ricevuto[9:].strip()
            pending_notes[chat_id] = nuovo_testo
            msg_risposta = f"Testo aggiornato:\n\n\"{nuovo_testo}\"\n\nVa bene ora? Rispondi **OK** per pubblicare o scrivi un'altra **Modifica: ...**"

        else:
            # Primo messaggio: elaboriamo con Gemini e mettiamo in attesa di conferma
            testo_professionale = sintetizza_e_formalizza(testo_ricevuto)
            pending_notes[chat_id] = testo_professionale
            
            msg_risposta = (
                f"Ecco la bozza elaborata:\n\n\"{testo_professionale}\"\n\n"
                f"Rispondi **OK** per pubblicarla sulla pergamena, oppure scrivi **Modifica: [tuo testo]** se vuoi cambiarla."
            )
            
        requests.post(f"{TELEGRAM_API_URL}/sendMessage", json={
            "chat_id": chat_id,
            "text": msg_risposta,
            "parse_mode": "Markdown"
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
