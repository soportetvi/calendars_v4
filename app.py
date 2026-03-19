from flask import Flask
from controllers import controllers
import os  # 👈 necesario para leer el puerto de Railway

app = Flask(__name__)
app.register_blueprint(controllers)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))  # Railway asigna el puerto
    app.run(host='0.0.0.0', port=port)        # host 0.0.0.0 para acceso público
