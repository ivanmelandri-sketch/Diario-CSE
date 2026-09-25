import os
import requests
from flask import Flask, request
from datetime import datetime, timezone, timedelta

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
REPO_NAME = "ivanmelandri-sketch/Diario-CSE"
FILE_PATH = "diario.json"

TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

pending_notes = {}
waiting_for_edit = {}

# Mappa dei colori delicati (stile pastello/pergamena) associati agli autori
# Puoi aggiungere o modificare i nomi delle colleghe qui sotto
COLORI_AUTORI = {
    "Ivan": "#fffaf0",       # Avorio classico
    "Chiara": "#f4f1ea",     # Grigio perla caldo
    "Sara": "#f4eae2",       # Rosa cipria molto tenue
    "Aurora": "#eaf2f4",     # Azzurro carta da zucchero chiaro
    "Elisa": "#eef4ea",      # Verde salvia chiaro
    "Giorgia": "#f4f2ea",    # Sabbia delicato
    "Carmen": "#f4eae8",     # Pesca pastello
    "Adi": "#eaeef4"         # Lavanda tenue
}

def get_colore_autore(autore):
    """Restituisce un colore delicato basato sul nome dell'autore, con un default neutro."""
    for nome_chiave, colore in COLORI_AUTORI.items():
        if nome_chiave.lower() in autore.lower():
            return colore
    return "#fffaf0" # Colore di fallback se il nome non è in lista

def sintetizza_e_formalizza(testo_grezzo):
    """Usa direttamente l'API REST di Google Gemini con il modello aggiornato."""
    if not GEMINI_API_KEY:
        return "[ERRORE: GEMINI_API_KEY non impostata su Render]"
        
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent?key={GEMINI_API_KEY}"
        
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
        
        payload = {
            "contents": [{
                "parts": [{"text": f"{prompt_sistema}\n\nTesto da elaborare:\n{testo_grezzo}"}]
            }]
        }
        
        response = requests.post(url, json=payload)
        
        if response.status_code == 200:
            data = response.json()
            testo_generato = data['candidates'][0]['content']['parts'][0]['text']
            return testo_generato.strip()
        else:
            return f"[ERRORE API REST ({response.status_code}): {response.text}]"
            
    except Exception as e:
        return f"[ERRORE DI SISTEMA: {str(e)}]"

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
    
    # Fuso orario italiano (gestione ora legale con offset +2)
    fuso_orario_italia = timezone(timedelta(hours=2))
    timestamp = datetime.now(fuso_orario_italia).strftime("%d/%m/%Y alle %H:%M")
    
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
    
    if 'callback_query' in data:
        callback = data['callback_query']
        chat_id = callback['message']['chat']['id']
        message_id = callback['message']['message_id']
        data_azione = callback['data']
        
        user_info = callback.get('from', {})
        nome = user_info.get('first_name', 'Educatrice/Educatore')
        cognome = user_info.get('last_name', '')
        autore = f"{nome} {cognome}".strip() or "Staff"
        
        if data_azione == "btn_ok":
            if chat_id in pending_notes:
                testo_da_salvare = pending_notes[chat_id]
                successo = salva_diario_su_github(testo_da_salvare, autore)
                
                del pending_notes[chat_id]
                waiting_for_edit.pop(chat_id, None)
                
                risposta_testo = "Nota pubblicata ufficialmente sulla pergamena! ✨" if successo else "Errore durante il salvataggio."
            else:
                risposta_testo = "Nessuna nota in sospeso trovata."
                
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

    if 'message' in data and 'text' in data['message']:
        chat_id = data['message']['chat']['id']
        testo_ricevuto = data['message']['text']
        
        user_info = data['message'].get('from', {})
        nome = user_info.get('first_name', 'Educatrice/Educatore')
        cognome = user_info.get('last_name', '')
        autore = f"{nome} {cognome}".strip() or "Staff"

        if chat_id in waiting_for_edit and waiting_for_edit[chat_id]:
            waiting_for_edit[chat_id] = False
            pending_notes[chat_id] = testo_ricevuto
            
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

        testo_professionale = sintetizza_e_formalizza(testo_ricevuto)
        pending_notes[chat_id] = testo_professionale
        
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
            h1 { text-align: center; border-bottom: 2px solid #bfa181; padding-bottom: 10px; margin-bottom: 15px; }
            .header-bar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 30px; }
            .btn-aggiorna { background-color: #8b5a2b; color: #fff; border: none; padding: 8px 14px; font-family: Georgia, serif; font-size: 0.9em; border-radius: 4px; cursor: pointer; text-decoration: none; box-shadow: 1px 1px 3px rgba(0,0,0,0.2); }
            .btn-aggiorna:hover { background-color: #6f4521; }
            .note { border-left: 4px solid #8b5a2b; padding: 15px; margin-bottom: 20px; box-shadow: 2px 2px 5px rgba(0,0,0,0.05); border-radius: 4px; }
            .meta { font-size: 0.85em; color: #7f6a55; margin-bottom: 8px; font-weight: bold; border-bottom: 1px dashed #e6d7be; padding-bottom: 4px; }
            .text { font-size: 1.05em; line-height: 1.5; }
        </style>
        <script>
            // Aggiorna automaticamente la pagina ogni 30 secondi in background
            setTimeout(function(){
                location.reload();
            }, 30000);
        </script>
    </head>
    <body>
        <h1>Diario Digitale CSE</h1>
        <div class="header-bar">
            <span style="font-size: 0.9em; color: #7f6a55; font-style: italic;">Aggiornamento in tempo reale attivo</span>
            <a href="javascript:location.reload();" class="btn-aggiorna">🔄 Aggiorna ora</a>
        </div>
        <div id="notes-container">
    """
    for entry in diario_list:
        autore_nota = entry.get('autore', 'Ivan')
        colore_sfondo = get_colore_autore(autore_nota)
        html += f"""
            <div class="note" style="background-color: {colore_sfondo};">
                <div class="meta">Inserito da {autore_nota} il {entry.get('timestamp', '')}</div>
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
