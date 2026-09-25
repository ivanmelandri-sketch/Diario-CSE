import os
import requests
import uuid
import base64
import json
from flask import Flask, request, jsonify, redirect, send_file
from datetime import datetime
from zoneinfo import ZoneInfo
from io import BytesIO
from docx import Document
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

app = Flask(__name__)

# Credenziali e configurazioni
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
REPO_NAME = "ivanmelandri-sketch/Diario-CSE"
FILE_PATH = "diario.json"

TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

# Palette colori operatori
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
    
    # Fuso orario italiano corretto (Europe/Rome)
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

@app.route("/", methods=["GET"])
def home():
    diario_list, _ = leggi_diario_da_github()
    
    html = """
    <!DOCTYPE html>
    <html lang="it">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Diario CSE - Pergamena</title>
        <link rel="manifest" href="/manifest.json">
        <meta name="theme-color" content="#8b5a2b">
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
                white-space: pre-wrap;
            }
            .azioni {
                display: flex;
                gap: 10px;
                margin-top: 10px;
                align-items: center;
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
                    alert('Impossibile copiare.');
                });
            }
            
            function confermaElimina(form) {
                return confirm('Sei sicuro di voler eliminare questa nota?');
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
        html += '<p style="text-align:center; color:#7f6a55;">Nessuna nota presente nel diario.</p>'
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
    
    nome_file = f"Diario_CSE_{datetime.now(ZoneInfo('Europe/Rome')).strftime('%Y%m%d_%H%M')}.docx"
    return send_file(
        buffer,
        as_attachment=True,
        download_name=nome_file,
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )

@app.route('/webhook', methods=['POST'])
def telegram_webhook():
    data = request.get_json()
    
    if not data:
        return jsonify({"status": "ok"}), 200

    if 'callback_query' in data:
        callback = data['callback_query']
        chat_id = callback['message']['chat']['id']
        message_id = callback['message']['message_id']
        data_azione = callback['data']
        
        user_info = callback.get('from', {})
        nome = user_info.get('first_name', 'Ivan')
        cognome = user_info.get('last_name', '')
        autore = f"{nome} {cognome}".strip() or "Ivan"
        
        if data_azione == "save_entry":
            testo_da_salvare = callback['message'].get('text', '').replace("Bozza elaborata:\n\n", "").replace("Bozza:\n\n", "")
            
            successo = salva_diario_su_github(testo_da_salvare, autore)
            risposta_testo = "Nota pubblicata ufficialmente sulla pergamena! ✨" if successo else "Errore durante il salvataggio."
            
            requests.post(f"{TELEGRAM_API_URL}/editMessageText", json={
                "chat_id": chat_id,
                "message_id": message_id,
                "text": f"✅ {risposta_testo}"
            })
        elif data_azione == "cancel_entry":
            requests.post(f"{TELEGRAM_API_URL}/editMessageText", json={
                "chat_id": chat_id,
                "message_id": message_id,
                "text": "❌ Operazione annullata."
            })
            
        return jsonify({"status": "ok"}), 200

    if 'message' in data and 'text' in data['message']:
        message = data["message"]
        chat_id = message["chat"]["id"]
        user_text = message.get("text") or message.get("caption", "")
        
        user_info = message.get('from', {})
        nome = user_info.get('first_name', 'Ivan')
        cognome = user_info.get('last_name', '')
        autore = f"{nome} {cognome}".strip() or "Ivan"

        if not user_text:
            send_telegram_message(chat_id, "Ho ricevuto il messaggio, ma è vuoto.")
            return jsonify({"status": "ok"}), 200

        # Elaborazione IA con il modello 3.8-flash richiesto
        processed_text = process_with_gemini(user_text)
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
            return res_json["candidates"][0]["content"]["parts"][0]["text"].strip()
        else:
            # Fallback in caso di errore API o 429
            return text
    except Exception:
        return text

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
                {"text": "❌ Annulla", "callback_data": "cancel_entry"}
            ]
        ]
    }

    payload = {
        "chat_id": chat_id,
        "text": f"Bozza elaborata:\n\n{text}",
        "reply_markup": keyboard
    }
    requests.post(url, json=payload)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
