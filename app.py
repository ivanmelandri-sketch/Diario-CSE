import os
import time
import requests
import uuid
from flask import Flask, request, jsonify, redirect, send_file
from datetime import datetime
from zoneinfo import ZoneInfo
from io import BytesIO
from docx import Document
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
REPO_NAME = "ivanmelandri-sketch/Diario-CSE"
FILE_PATH = "diario.json"
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

pending_notes = {}
waiting_for_edit = {}
editing_message_id = {}

COLORI_OPERATORI = [
    {"bg": "#fffaf0", "border": "#8b5a2b", "meta": "#7f6a55", "line": "#e6d7be"},
    {"bg": "#f0f4f1", "border": "#557a62", "meta": "#435e4d", "line": "#d0dec7"},
    {"bg": "#f0f3f7", "border": "#546e8a", "meta": "#43566b", "line": "#d1dae6"},
    {"bg": "#f5f0f6", "border": "#7a5482", "meta": "#604266", "line": "#e5d4e8"},
    {"bg": "#f7f3f0", "border": "#9e6b52", "meta": "#7d5541", "line": "#eaded5"},
    {"bg": "#f2f2f0", "border": "#6e6d6b", "meta": "#545351", "line": "#dedddb"},
    {"bg": "#f7f6f0", "border": "#8a7e54", "meta": "#6b6242", "line": "#eae6d1"}
]

def ottieni_stile_operatore(autore):
    indice = abs(hash(autore.lower())) % len(COLORI_OPERATORI)
    return COLORI_OPERATORI[indice]

def sintetizza_e_formalizza(testo_grezzo):
    if not GEMINI_API_KEY:
        return "[ERRORE: GEMINI_API_KEY non impostata su Render]"
        
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    
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
    
    while True:
        try:
            response = requests.post(url, json=payload, timeout=20)
            if response.status_code == 200:
                data = response.json()
                testo_generato = data['candidates'][0]['content']['parts'][0]['text']
                return testo_generato.strip()
            time.sleep(3)
        except Exception:
            time.sleep(3)

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
        
        modificato = False
        for entry in diario_list:
            if "id" not in entry:
                entry["id"] = str(uuid.uuid4())
                modificato = True
        if modificato:
            salva_lista_su_github(diario_list, sha)
            return leggi_diario_da_github()
            
        return diario_list, sha
    return [], None

def salva_lista_su_github(diario_list, sha):
    import base64
    import json
    url = f"https://api.github.com/repos/{REPO_NAME}/contents/{FILE_PATH}"
    headers = {"Authorization": f"Bearer {GITHUB_TOKEN}", "Accept": "application/vnd.github+json"}
    
    updated_content_bytes = json.dumps(diario_list, indent=4, ensure_ascii=False).encode('utf-8')
    encoded_content = base64.b64encode(updated_content_bytes).decode('utf-8')
    
    data = {
        "message": "Aggiornamento diario",
        "content": encoded_content,
        "sha": sha
    }
    response = requests.put(url, headers=headers, json=data)
    return response.status_code in [200, 201]

def salva_diario_su_github(testo_nota, autore):
    diario_list, sha = leggi_diario_da_github()
    
    fuso_italiano = ZoneInfo("Europe/Rome")
    timestamp = datetime.now(fuso_italiano).strftime("%d/%m/%Y alle %H:%M")
    
    entry = {
        "id": str(uuid.uuid4()),
        "timestamp": timestamp,
        "autore": autore,
        "testo": testo_nota
    }
    
    diario_list.insert(0, entry)
    return salva_lista_su_github(diario_list, sha)

def elimina_nota_da_github(nota_id):
    diario_list, sha = leggi_diario_da_github()
    nuovo_diario = [e for e in diario_list if e.get("id") != nota_id]
    if len(nuovo_diario) == len(diario_list):
        return False
    return salva_lista_su_github(nuovo_diario, sha)

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
                editing_message_id.pop(chat_id, None)
                
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
            editing_message_id[chat_id] = message_id
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
            msg_id_da_aggiornare = editing_message_id.get(chat_id)
            
            keyboard = {
                "inline_keyboard": [
                    [
                        {"text": "✅ Pubblica (OK)", "callback_data": "btn_ok"},
                        {"text": "✏️ Modifica (M)", "callback_data": "btn_modifica"}
                    ]
                ]
            }
            
            payload_msg = {
                "chat_id": chat_id,
                "text": f"Ecco la nota aggiornata:\n\n\"{testo_ricevuto}\"\n\nCosa vuoi fare?",
                "reply_markup": keyboard
            }
            if msg_id_da_aggiornare:
                payload_msg["message_id"] = msg_id_da_aggiornare
                requests.post(f"{TELEGRAM_API_URL}/editMessageText", json=payload_msg)
            else:
                requests.post(f"{TELEGRAM_API_URL}/sendMessage", json=payload_msg)
                
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
        
        res = requests.post(f"{TELEGRAM_API_URL}/sendMessage", json={
            "chat_id": chat_id,
            "text": f"Bozza elaborata:\n\n\"{testo_professionale}\"",
            "reply_markup": keyboard
        })
        
        if res.status_code == 200:
            res_json = res.json()
            if 'result' in res_json:
                editing_message_id[chat_id] = res_json['result']['message_id']
        
    return "OK", 200

@app.route('/elimina/<nota_id>', methods=['POST'])
def elimina(nota_id):
    elimina_nota_da_github(nota_id)
    return redirect('/')

@app.route('/backup.docx')
def backup_word():
    diario_list, _ = leggi_diario_da_github()
    
    doc = Document()
    titolo = doc.add_heading('Diario Digitale CSE', 0)
    titolo.alignment = WD_ALIGN_PARAGRAPH.CENTER
    
    fuso = ZoneInfo("Europe/Rome")
    data_export = datetime.now(fuso).strftime("%d/%m/%Y alle %H:%M")
    p = doc.add_paragraph(f"Esportato il {data_export}")
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph()
    
    if not diario_list:
        doc.add_paragraph("Nessuna nota presente nel diario.")
    else:
        for entry in diario_list:
            meta = doc.add_paragraph()
            run = meta.add_run(f"Inserito da {entry.get('autore', 'Sconosciuto')} il {entry.get('timestamp', '')}")
            run.bold = True
            run.font.size = Pt(11)
            run.font.color.rgb = RGBColor(0x55, 0x44, 0x33)
            
            testo = doc.add_paragraph(entry.get('testo', ''))
            testo.paragraph_format.space_after = Pt(18)
            doc.add_paragraph("─" * 40)
    
    buffer = BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    
    nome_file = f"Diario_CSE_{datetime.now().strftime('%Y%m%d_%H%M')}.docx"
    return send_file(
        buffer,
        as_attachment=True,
        download_name=nome_file,
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
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
            body { 
                font-family: Georgia, serif; 
                background: #f4ecd8; 
                color: #2c221e; 
                max-width: 800px; 
                margin: 0 auto; 
                padding: 20px; 
            }
            h1 { 
                text-align: center; 
                border-bottom: 2px solid #bfa181; 
                padding-bottom: 10px; 
                margin-bottom: 20px; 
            }
            .toolbar {
                text-align: center;
                margin-bottom: 25px;
            }
            .btn-backup {
                background: #8b5a2b;
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 6px;
                font-size: 1em;
                cursor: pointer;
                text-decoration: none;
                display: inline-block;
            }
            .btn-backup:hover {
                background: #6d4520;
            }
            .note { 
                padding: 15px; 
                margin-bottom: 20px; 
                box-shadow: 2px 2px 5px rgba(0,0,0,0.05); 
                border-radius: 4px; 
                position: relative;
            }
            .text { 
                font-size: 1.05em; 
                line-height: 1.5; 
                margin-bottom: 12px;
            }
            .azioni {
                display: flex;
                gap: 10px;
                margin-top: 10px;
            }
            .btn {
                border: none;
                padding: 6px 12px;
                border-radius: 4px;
                font-size: 0.85em;
                cursor: pointer;
                font-family: Georgia, serif;
            }
            .btn-copia {
                background: #e8f0e8;
                color: #2d5a2d;
            }
            .btn-copia:hover {
                background: #d0e0d0;
            }
            .btn-elimina {
                background: #f8e8e8;
                color: #8b2a2a;
            }
            .btn-elimina:hover {
                background: #f0d0d0;
            }
            .copia-ok {
                color: #2d5a2d;
                font-size: 0.85em;
                margin-left: 8px;
            }
        </style>
        <script>
            if ('serviceWorker' in navigator) {
                navigator.serviceWorker.register('/sw.js');
            }
            
            function copiaTesto(id, testo) {
                navigator.clipboard.writeText(testo).then(function() {
                    var span = document.getElementById('ok-' + id);
                    if (span) {
                        span.style.display = 'inline';
                        setTimeout(function() {
                            span.style.display = 'none';
                        }, 2000);
                    }
                }).catch(function() {
                    alert('Impossibile copiare. Seleziona il testo manualmente.');
                });
            }
            
            function confermaElimina(form) {
                return confirm('Sei sicuro di voler eliminare questa nota? L\\'operazione non si può annullare.');
            }
        </script>
    </head>
    <body>
        <h1>Diario Digitale CSE</h1>
        
        <div class="toolbar">
            <a href="/backup.docx" class="btn-backup">📄 Scarica backup Word</a>
        </div>
        
        <div id="notes-container">
    """
    
    if not diario_list:
        html += """
            <p style="text-align:center; color:#7f6a55;">Nessuna nota presente. Invia un messaggio al bot Telegram per iniziare.</p>
        """
    else:
        for entry in diario_list:
            autore = entry.get('autore', 'Ivan')
            stile = ottieni_stile_operatore(autore)
            nota_id = entry.get('id', '')
            testo = entry.get('testo', '')
            testo_html = testo.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            testo_js = testo.replace('\\', '\\\\').replace("'", "\\'").replace('"', '\\"').replace('\n', '\\n')
            
            html += f"""
            <div class="note" style="background-color: {stile['bg']}; border-left: 4px solid {stile['border']};">
                <div style="font-size: 0.85em; color: {stile['meta']}; margin-bottom: 8px; font-weight: bold; border-bottom: 1px dashed {stile['line']}; padding-bottom: 4px;">
                    Inserito da {autore} il {entry.get('timestamp', '')}
                </div>
                <div class="text">{testo_html}</div>
                <div class="azioni">
                    <button class="btn btn-copia" onclick="copiaTesto('{nota_id}', '{testo_js}')">📋 Copia</button>
                    <span id="ok-{nota_id}" class="copia-ok" style="display:none;">Copiato!</span>
                    <form method="POST" action="/elimina/{nota_id}" style="display:inline;" onsubmit="return confermaElimina(this);">
                        <button type="submit" class="btn btn-elimina">🗑️ Elimina</button>
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
