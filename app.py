import os
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

# Memoria temporanea per le note (poi useremo un file o database)
# Per ora inseriamo una nota di prova per vedere se la grafica funziona
note_database = [
    {
        "id": 1,
        "operatore": "Ivan",
        "data": "24/09/2026 - 18:35",
        "testo": "Avviato il sistema del diario di bordo. Test di visualizzazione della pergamena digitale."
    }
]

@app.route('/')
def index():
    # Mostra la pagina web passando le note in ordine cronologico inverso (ultime in cima)
    return render_template('index.html', notes=note_database[::-1])

@app.route('/webhook', methods=['POST'])
def telegram_webhook():
    # Qui arriveranno i messaggi da Telegram in futuro
    data = request.json
    print("Dati ricevuti da Telegram:", data)
    return jsonify({"status": "ok"})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
