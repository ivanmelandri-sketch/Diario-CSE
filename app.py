import os
import requests
from flask import Flask, request
from google import genai

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
REPO_NAME = "ivanmelandri-sketch/Diario-CSE"
FILE_PATH = "diario.json"

TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

def sintetizza_e_formalizza(testo_grezzo):
    """Usa Google Gemini per ripulire, sintetizzare e dare un tono professionale al testo."""
    if not GEMINI_API_KEY:
        print("ATTENZIONE: GEMINI_API_KEY non è impostata nelle variabili d'ambiente di Render.")
        return testo_grezzo
        
    try:
        # Inizializzazione corretta del client Google GenAI
        client = genai.Client(api_key=GEMINI_API_KEY)
        prompt_sistema = (
            "Sei un assistente di redazione professionale per un team socio-educativo. "
            "Il tuo compito è prendere appunti rapidi, informali o confusi inviati via Telegram "
            "e trasformarli in una nota di diario strutturata, sintetica, chiara "
            "e scritta con un tono formale e professionale. "
            "Mantieni intatti i concetti chiave, i dati o le decisioni prese, eliminando le "
            "ripetizioni o i riempitivi verbali."
        )
        
        response = client.models.generate_content(
            model="gemini-3.8-flash",
            contents=f"{prompt_sistema}\n\nTesto da elaborare:\n{testo_grezzo}"
        )
        
        if response and response.text:
            return response.text.strip()
        return testo_grezzo
        
    except Exception as e:
        print(f"ERRORE CRITICO durante la chiamata a Gemini: {str(e)}")
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

def salva_diario_su_github(nuova_nota):
    import base64
    import json
    from datetime import datetime
    
    diario_list, sha = leggi_diario_da_github()
    
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = {
        "timestamp": timestamp,
        "testo": nuova_nota
    }
    
    diario_list.insert(0, entry)
    
    url = f"https://api.github.com/repos/{REPO_NAME}/contents/{FILE_PATH}"
    headers = {"Authorization": f"Bearer {GITHUB_TOKEN}", "Accept": "application/vnd.github+json"}
    
    updated_content_bytes = json.dumps(diario_list, indent=4, ensure_ascii=False).encode('utf-8')
    encoded_content = base64.b64encode(updated_content_bytes).decode('utf-8')
    
    data = {
        "message": "Aggiornamento diario con sintesi professionale",
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
        
        # 1. Tentativo di sintesi con l'intelligenza artificiale
        testo_professionale = sintetizza_e_formalizza(testo_grezzo)
        
        # 2. Salvataggio su GitHub del risultato (elaborato o grezzo in fallback)
        successo = salva_diario_su_github(testo_professionale)
        
        if successo:
            msg_risposta = f"Nota elaborata e salvata con successo:\n\n{testo_professionale}"
        else:
            msg_risposta = "Errore durante il salvataggio su GitHub."
            
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
            h1 { text-align: center; border-bottom: 2px solid #bfa181; padding-bottom: 10px; }
            .note { background: #fffaf0; border-left: 4px solid #8b5a2b; padding: 15px; margin-bottom: 20px; box-shadow: 2px 2px 5px rgba(0,0,0,0.05); }
            .time { font-size: 0.85em; color: #7f6a55; margin-bottom: 5px; }
        </style>
    </head>
    <body>
        <h1>Diario Digitale CSE</h1>
        <div id="notes-container">
    """
    for entry in diario_list:
        html += f"""
            <div class="note">
                <div class="time">{entry.get('timestamp', '')}</div>
                <div>{entry.get('testo', '')}</div>
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
