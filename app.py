import os
import time
import requests
from flask import Flask, request, jsonify, redirect, url_for, Response
from datetime import datetime
from zoneinfo import ZoneInfo
import base64
import json

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
REPO_NAME = "ivanmelandri-sketch/Diario-CSE"
FILE_PATH = "diario.json"

TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

pending_notes = {}
waiting_for_edit = {}

COLORI_OPERATORI = [
    {"bg": "#fffaf0", "border": "#8b5a2b", "meta": "#7f6a55", "line": "#e6d7be"},  # 1. Caldo / Terra
    {"bg": "#f0f4f1", "border": "#557a62", "meta": "#435e4d", "line": "#d0dec7"},  # 2. Verde Salvia
    {"bg": "#f0f3f7", "border": "#546e8a", "meta": "#43566b", "line": "#d1dae6"},  # 3. Azzurro Polvere
    {"bg": "#f5f0f6", "border": "#7a5482", "meta": "#604266", "line": "#e5d4e8"},  # 4. Lavanda Tenue
    {"bg": "#f7f3f0", "border": "#9e6b52", "meta": "#7d5541", "line": "#eadeD5"},  # 5. Pesca / Terracotta chiara
    {"bg": "#f2f2f0", "border": "#6e6d6b", "meta": "#545351", "line": "#dedddb"},  # 6. Grigio Caldo / Tortora
    {"bg": "#f7f6f0", "border": "#8a7e54", "meta": "#6b6242", "line": "#eae6d1"}   # 7. Giallo Paglierino / Sabbia
]

def ottieni_stile_operatore(autore):
    indice = abs(hash(autore.lower())) % len(COLORI_OPERATORI)
    return COLORI_OPERATORI[indice]

def sintetizza_e_formalizza(testo_grezzo):
    if not GEMINI_API_KEY:
        return "[ERRORE: GEMINI_API_KEY non impostata su Render]"
        
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
    
    tentativi = 3
    for tentativo in range(tentativi):
        try:
            response = requests.post(url, json=payload, timeout=15)
            if response.status_code == 200:
                data = response.json()
                return data['candidates'][0]['content']['parts'][0]['text'].strip()
            elif response.status_code == 503 and tentativo < tentativi - 1:
                time.sleep(2)
                continue
            else:
                return f"[ERRORE API REST ({response.status_code}): {response.text}]"
        except Exception as e:
            if tentativo < tentativi - 1:
                time.sleep(2)
                continue
            return f"[ERRORE DI SISTEMA: {str(e)}]"
            
    return "[ERRORE: Servizio temporaneamente sovraccarico, riprova tra qualche istante.]"

def leggi_diario_da_github():
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

def salva_lista_su_github(diario_list, messaggio_commit):
    _, sha = leggi_diario_da_github()
    url = f"https://api.github.com/repos/{REPO_NAME}/contents/{FILE_PATH}"
    headers = {"Authorization": f"Bearer {GITHUB_TOKEN}", "Accept": "application/vnd.github+json"}
    
    updated_content_bytes = json.dumps(diario_list, indent=4, ensure_ascii=False).encode('utf-8')
    encoded_content = base64.b64encode(updated_content_bytes).decode('utf-8')
    
    data = {
        "message": messaggio_commit,
        "content": encoded_content,
        "sha": sha
    }
    
    response = requests.put(url, headers=headers, json=data)
    return response.status_code in [200, 201]

def salva_diario_su_github(testo_nota, autore):
    diario_list, _ = leggi_diario_da_github()
    fuso_italiano = ZoneInfo("Europe/Rome")
    timestamp = datetime.now(fuso_italiano).strftime("%d/%m/%Y alle %H:%M")
    
    entry = {
        "timestamp": timestamp,
        "autore": autore,
        "testo": testo_nota
    }
    
    diario_list.insert(0, entry)
    return salva_lista_su_github(diario_list, "Aggiunta nota di diario confermata")

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    
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
        nome = user_info.get('first_name', 'Ivan')
        cognome = user_info.get('last_name', '')
        autore = f"{nome} {cognome}".strip() or "Ivan"

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

@app.route('/elimina/<int:index>', methods=['POST'])
def elimina_nota(index):
    diario_list, _ = leggi_diario_da_github()
    if 0 <= index < len(diario_list):
        diario_list.pop(index)
        salva_lista_su_github(diario_list, "Eliminazione nota da interfaccia")
    return redirect(url_for('home'))

@app.route('/esporta/txt')
def esporta_txt():
    diario_list, _ = leggi_diario_da_github()
    testo_file = ""
    for entry in diario_list:
        testo_file += "--------------------------------------------------\n"
        testo_file += f"Inserito da: {entry.get('autore', '')} il {entry.get('timestamp', '')}\n"
        testo_file += "--------------------------------------------------\n"
        testo_file += f"{entry.get('testo', '')}\n\n\n"
    
    return Response(
        testo_file,
        mimetype="text/plain;charset=utf-8",
        headers={"Content-Disposition": "attachment;filename=diario_cse_backup.txt"}
    )

@app.route('/esporta/word')
def esporta_word():
    diario_list, _ = leggi_diario_da_github()
    html_content = """<html xmlns:o='urn:schemas-microsoft-com:office:office' xmlns:w='urn:schemas-microsoft-com:office:word' xmlns='http://www.w3.org/TR/REC-html40'>
    <head><meta charset='utf-8'><title>Diario CSE Backup</title></head>
    <body style="font-family: Georgia, serif; line-height: 1.6; color: #2c221e; padding: 20px;">
    <h1 style="text-align: center; color: #8b5a2b; border-bottom: 2px solid #bfa181; padding-bottom: 10px;">Diario Digitale CSE - Backup Storico</h1>
    """
    for entry in diario_list:
        html_content += f"""
        <div style="margin-bottom: 25px; padding: 15px; border-left: 4px solid #8b5a2b; background-color: #fffaf0;">
            <p style="font-size: 0.9em; color: #7f6a55; font-weight: bold; margin: 0 0 8px 0; border-bottom: 1px dashed #e6d7be; padding-bottom: 4px;">
                Inserito da {entry.get('autore', '')} il {entry.get('timestamp', '')}
            </p>
            <p style="font-size: 1.1em; margin: 0;">{entry.get('testo', '')}</p>
        </div>
        """
    html_content += "</body></html>"
    
    return Response(
        html_content,
        mimetype="application/msword;charset=utf-8",
        headers={"Content-Disposition": "attachment;filename=diario_cse_backup.doc"}
    )

@app.route('/manifest.json')
def manifest():
    return jsonify({
        "name": "Diario Digitale CSE",
        "short_name": "Diario CSE",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#f4ecd8",
        "theme_color": "#8b5a2b",
        "icons": [
            {
                "src": "https://img.icons8.com/color/192/48/journal.png",
                "sizes": "192x192",
                "type": "image/png"
            }
        ]
    })

@app.route('/sw.js')
def service_worker():
    sw_code = "self.addEventListener('fetch', function(event) {});"
    return sw_code, 200, {'Content-Type': 'application/javascript'}

@app.route('/')
def home():
    diario_list, _ = leggi_diario_da_github()
    
    html = """
    <!DOCTYPE html>
    <html lang="it">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Diario CSE</title>
        <link rel="manifest" href="/manifest.json">
        <meta name="theme-color" content="#8b5a2b">
        <meta name="apple-mobile-web-app-capable" content="yes">
        <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
        <meta name="apple-mobile-web-app-title" content="Diario CSE">
        <style>
            body { font-family: Georgia, serif; background: #f4ecd8; color: #2c221e; max-width: 800px; margin: 0 auto; padding: 20px; }
            h1 { text-align: center; border-bottom: 2px solid #bfa181; padding-bottom: 10px; margin-bottom: 15px; }
            .barra-comandi { display: flex; flex-wrap: wrap; justify-content: center; gap: 8px; margin-bottom: 25px; }
            .btn { background: #8b5a2b; color: white; border: none; padding: 8px 12px; border-radius: 4px; cursor: pointer; font-family: Georgia, serif; font-size: 0.85em; text-decoration: none; display: inline-block; box-shadow: 1px 1px 3px rgba(0,0,0,0.2); }
            .btn:active { background: #6e4621; }
            .note { padding: 15px; margin-bottom: 20px; box-shadow: 2px 2px 5px rgba(0,0,0,0.05); border-radius: 4px; position: relative; }
            .text { font-size: 1.05em; line-height: 1.5; margin-bottom: 12px; }
            .note-footer { display: flex; justify-content: flex-end; gap: 8px; border-top: 1px dashed rgba(0,0,0,0.1); padding-top: 8px; }
            .btn-azione { background: transparent; border: 1px solid #bfa181; color: #554338; padding: 4px 8px; border-radius: 3px; font-size: 0.8em; cursor: pointer; }
            .btn-azione:hover { background: rgba(0,0,0,0.05); }
        </style>
        <script>
            if ('serviceWorker' in navigator) {
                navigator.serviceWorker.register('/sw.js');
            }
            function copiaTesto(testo) {
                navigator.clipboard.writeText(testo).then(function() {
                    alert("Testo copiato negli appunti!");
                }, function(err) {
                    alert("Errore durante la copia.");
                });
            }
            function confermaEliminazione(index) {
                if (confirm("Sei sicuro di voler eliminare questa nota?")) {
                    document.getElementById('form-elimina-' + index).submit();
                }
            }
        </script>
    </head>
    <body>
        <h1>Diario Digitale CSE</h1>
        <div class="barra-comandi">
            <button class="btn" onclick="location.reload()">🔄 Aggiorna</button>
            <a class="btn" href="/esporta/txt">📝 Scarica Blocco Note (.txt)</a>
            <a class="btn" href="/esporta/word">📄 Scarica Word (.doc)</a>
        </div>
        <div id="notes-container">
    """
    
    for index, entry in enumerate(diario_list):
        autore = entry.get('autore', 'Ivan')
        stile = ottieni_stile_operatore(autore)
        
        html += f"""
            <div class="note" style="background-color: {stile['bg']}; border-left: 4px solid {stile['border']};">
                <div style="font-size: 0.85em; color: {stile['meta']}; margin-bottom: 8px; font-weight: bold; border-bottom: 1px dashed {stile['line']}; padding-bottom: 4px;">
                    Inserito da {autore} il {entry.get('timestamp', '')}
                </div>
                <div class="text">{entry.get('testo', '')}</div>
                <div class="note-footer">
                    <button class="btn-azione" onclick="copiaTesto(`{entry.get('testo', '')}`)" title="Copia testo">📋 Copia</button>
                    <form id="form-elimina-{index}" action="/elimina/{index}" method="POST" style="display:inline;">
                        <button type="button" class="btn-azione" onclick="confermaEliminazione({index})" title="Elimina nota" style="color: #a83232; border-color: #d1a1a1;">🗑️ Elimina</button>
                    </form>
                </div>
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
