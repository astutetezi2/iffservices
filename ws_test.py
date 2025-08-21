from flask import Flask
from flask_sock import Sock
from hypercorn.config import Config
from hypercorn.asyncio import serve
import asyncio

app = Flask(__name__)
sock = Sock(app)


@sock.route("/ws-echo/<token>")
def ws_echo(ws, token):
    print(f"Connected token: {token}")
    while True:
        data = ws.receive()
        if data is None:
            break
        print(f"Received: {data}")
        ws.send(f"Echo: {data}")


if __name__ == "__main__":
    config = Config()
    config.bind = ["0.0.0.0:5050"]  # listen on IPv4
    config.debug = True
    config.accesslog = '-'
    asyncio.run(serve(app, config))
