from flask import Flask, request
from werkzeug.serving import WSGIRequestHandler

WSGIRequestHandler.protocol_version = "HTTP/1.1"

app = Flask(__name__)

@app.post("/echo")
def echo():
    return request.get_data()

if __name__ == "__main__": app.run(host="0.0.0.0", port=8080, threaded=True)
