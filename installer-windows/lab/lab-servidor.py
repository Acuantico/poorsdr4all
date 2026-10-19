#!/usr/bin/env python3
"""Servidor temporal del laboratorio, SOLO en la red virtual de la VM (192.168.122.1).

  GET  /<fichero>          la VM descarga tareas y ficheros del directorio servido
  PUT  /subir/<nombre>     la VM sube resultados y artefactos a <directorio>/subidas/
"""
import http.server
import pathlib
import sys

BASE = pathlib.Path(sys.argv[1])
HOST, PORT = sys.argv[2], int(sys.argv[3])
SUBIDAS = BASE / "subidas"
SUBIDAS.mkdir(exist_ok=True)


class Manejador(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(BASE), **k)

    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path.startswith("/orden-lab.txt") and self.client_address[0] != HOST:
            (BASE / "agente-visto").touch()
        super().do_GET()

    def do_PUT(self):
        if not self.path.startswith("/subir/"):
            return self.send_error(404)
        nombre = pathlib.PurePosixPath(self.path.removeprefix("/subir/")).name
        if not nombre or nombre.startswith("."):
            return self.send_error(400)
        total, recibido = int(self.headers.get("Content-Length", 0)), 0
        parcial = SUBIDAS / (nombre + ".parte")
        with open(parcial, "wb") as f:
            while recibido < total:
                trozo = self.rfile.read(min(1 << 20, total - recibido))
                if not trozo:
                    break
                f.write(trozo)
                recibido += len(trozo)
        if recibido != total:
            parcial.unlink(missing_ok=True)
            return self.send_error(400)
        parcial.replace(SUBIDAS / nombre)
        self.send_response(200)
        self.end_headers()


http.server.ThreadingHTTPServer((HOST, PORT), Manejador).serve_forever()
