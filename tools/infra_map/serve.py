"""Régénère data.json depuis le code puis sert la carte en local.

uv run python tools/infra_map/serve.py            # http://127.0.0.1:8765
uv run python tools/infra_map/serve.py --port 9000 --no-build
"""

import argparse
import functools
import http.server
import webbrowser

from build import HERE, main as build

parser = argparse.ArgumentParser()
parser.add_argument("--port", type=int, default=8765)
parser.add_argument(
    "--no-build", action="store_true", help="réutilise le data.json existant"
)
parser.add_argument("--open", action="store_true", help="ouvre le navigateur")
args = parser.parse_args()

if not args.no_build:
    build()


class NoCache(http.server.SimpleHTTPRequestHandler):
    # Sans ça, le navigateur garde un vieil index.html après un pull.
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


handler = functools.partial(NoCache, directory=str(HERE))
# 127.0.0.1 seulement : la page embarque le code et la config du déploiement.
with http.server.ThreadingHTTPServer(("127.0.0.1", args.port), handler) as server:
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Carte servie sur {url} (Ctrl+C pour arrêter)")
    if args.open:
        webbrowser.open(url)
    server.serve_forever()
