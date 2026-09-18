#!/usr/bin/env python3
"""Extrait la charge pyLDAvis du modèle LDA de 2021 depuis la sortie du notebook.

Le modèle MALLET lui-même n'a jamais été sérialisé. Ce qui subsiste est la
structure `PreparedData` que pyLDAvis a inscrite dans la sortie de la cellule,
et que le notebook transporte depuis. Ce script la ressort telle quelle.

Usage : python analysis/thesis-2021/extract_ldavis.py [--check]

--check ne réécrit rien et échoue si le fichier versionné diverge de la source.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

# Ancre de provenance : le blob du notebook, pas un commit. Le notebook a
# changé de chemin et de commit au fil des réorganisations ; son contenu, non.
NOTEBOOK_BLOB = "c446b377d0921c9f19e1d22aba30c97b6f2ece3a"
NOTEBOOK_NAME = "Games_Personality_Project.ipynb"

OUT = Path(__file__).parent / "ldavis_2021.json"

# pyLDAvis sérialise la visualisation dans une affectation JS du HTML de sortie.
LDAVIS_PAYLOAD = re.compile(r"var ldavis_[A-Za-z0-9_]+_data\s*=\s*(\{.*?\});", re.DOTALL)


def read_notebook() -> dict:
    blob = subprocess.run(
        ["git", "cat-file", "blob", NOTEBOOK_BLOB],
        capture_output=True,
        check=True,
    ).stdout
    return json.loads(blob)


def extract(notebook: dict) -> dict:
    for index, cell in enumerate(notebook["cells"]):
        for output in cell.get("outputs", []):
            html = "".join(output.get("data", {}).get("text/html", []))
            match = LDAVIS_PAYLOAD.search(html)
            if match:
                print(f"charge pyLDAvis trouvée cellule {index}", file=sys.stderr)
                return json.loads(match.group(1))
    raise SystemExit(f"aucune sortie pyLDAvis dans {NOTEBOOK_NAME}")


def serialize(payload: dict) -> str:
    # Re-sérialisation canonique : le JSON d'origine est sur une seule ligne,
    # illisible en diff. Le contenu est identique, l'ordre des clés est fixé.
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    text = serialize(extract(read_notebook()))
    digest = hashlib.sha256(text.encode()).hexdigest()

    if args.check:
        if not OUT.exists():
            raise SystemExit(f"{OUT} absent")
        if OUT.read_text() != text:
            raise SystemExit(f"{OUT} diverge de la source (attendu sha256 {digest})")
        print(f"{OUT.name} conforme (sha256 {digest})")
        return

    OUT.write_text(text)
    print(f"{OUT} écrit, sha256 {digest}")


if __name__ == "__main__":
    main()
