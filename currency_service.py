from flask import Flask, request, jsonify

app = Flask(__name__)

# Статические курсы валют (курс к рублю)
EXCHANGE_RATES = {
    'USD': 95.50,
    'EUR': 103.25
}

@app.route('/rate', methods=['GET'])
def get_exchange_rate():
    """Получение курса валюты"""
    try:
        currency = request.args.get('currency')
        
        if not currency:
            return jsonify({
                "message": "UNKNOWN CURRENCY"
            }), 400
        
        currency = currency.upper()
        
        if currency not in EXCHANGE_RATES:
            return jsonify({
                "message": "UNKNOWN CURRENCY"
            }), 400
        
        return jsonify({
            "rate": EXCHANGE_RATES[currency]
        }), 200
        
    except Exception as e:
        return jsonify({
            "message": "UNEXPECTED ERROR"
        }), 500

@app.route('/health', methods=['GET'])
def health_check():
    """Проверка работоспособности сервиса"""
    return jsonify({"status": "OK"}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)