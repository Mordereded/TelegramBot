import os

from flask import Flask, Response

flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return Response("OK", status=200)

def run_flask():
    port = int(os.environ.get("PORT", 8000))
    flask_app.run(host="0.0.0.0", port=port)