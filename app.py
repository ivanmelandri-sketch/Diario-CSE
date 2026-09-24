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

def sintetizza_e_formalizza(testo_grezzo):
    """Usa Google Gemini per estrarre e formalizzare la sola descrizione dell'evento."""
    if not GEMINI_API_KEY:
        return testo_grezzo
        
    client = genai.Client(api_key=GEMINI_API_KEY)
    prompt_sistema = (
        "Sei un assistente di redazione per un team socio-educativo. "
        "Il tuo compito è prendere appunti rapidi e informali inviati via Telegram e trasformarli "
        "esclusivamente in un paragrafo descrittivo dell'evento o dell'attività svolta, "
        "scritto con un tono formale e professionale. "
        "Regole tassative: "
        "1. Non inserire data, ora, intestazioni, firme o saluti nel testo (verranno aggiunti automaticamente dal sistema). "
        "2. Non aggiungere frasi di chiusura (es. 'seguiranno aggiornamenti'). "
        "3. Restituisci unicamente il testo della descrizione pulita e sintetica."
    )
    
    modelli = ["gemini-3.8-flash", "gemini-2.5-flash"]
    
    for modello in modelli:
        try:
            response = client.models.generate_content(
                model=modello,
                contents=f"{prompt_sistema}\n\nTesto da elaborare:\n{testo_grezzo}"
            )
            if response and response.text:
                return response.text.strip()
        except Exception as e:
            print(f"Tentativo fallito con {modello}: {str(e)}")
            continue
            
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
    
    # Registriamo data, ora e autore in modo strutturato
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
        "message": "Aggiunta nota di diario con data, ora e autore",
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
        testo_grezzo = data['message']['text']
        
        # Estraiamo il nome o il nickname di chi ha scritto su Telegram
        user_info = data['message'].get('from', {})
        nome = user_info.get('first_name', 'Educatore')
        cognome = user_info.get('last_name', '')
        autore = f"{nome} {cognome}".strip()
        
        # 1. Sintesi pulita della descrizione
        testo_professionale = sintetizza_e_formalizza(testo_grezzo)
        
        # 2. Salvataggio su GitHub includendo autore, data e ora
        successo = salva_diario_su_github(testo_professionale, autore)
        
        if successo:
            msg_risposta = f"Nota registrata correttamente per le ore {datetime.now().strftime('%H:%M')} da {autore}."
        else:
            msg_risposta = "Errore durante il salvataggio."
            
        requests.post(f"{TELEGRAM_API_URL}/sendMessage", json={
            "chat_id": chat_id,
            "text": msg_risposta
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
                <div class="meta">Inserito da {entry.get('autore', 'Operatore')} il {entry.get('timestamp', '')}</div>
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
