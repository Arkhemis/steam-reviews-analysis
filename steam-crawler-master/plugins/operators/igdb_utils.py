import requests
import sys
import pandas as pd
import time
from pathlib import Path
from dotenv import load_dotenv
import logging

# --- Configuration ---
load_dotenv()  # Charge les variables depuis le fichier .env
logger = logging.getLogger(__name__)
DATA_DUMP_DIR = Path("igdb_datadumps")
TOKEN_URL = "https://id.twitch.tv/oauth2/token"
API_BASE_URL = "https://api.igdb.com/v4"


def get_api_headers(client_id, client_secret):
    """Récupère un token d'accès Twitch/IGDB."""

    logging.info("Récupération du token d'accès Twitch...")
    if not client_id or not client_secret:
        logging.error("ERREUR: CLIENT_ID ou CLIENT_SECRET manquant.")
        sys.exit()
    try:
        response = requests.post(
            TOKEN_URL,
            params={
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "client_credentials",
            },
            timeout=15,
        )  # Timeout légèrement augmenté
        token_data = response.json()
        access_token = token_data.get("access_token")
        api_headers = {
            "Client-ID": client_id,
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        }
        return api_headers
    except requests.exceptions.RequestException as e:
        logging.error(f"Erreur lors de la récupération du token : {e}")
        sys.exit()


def download_dump(url, dest_path):
    try:
        with requests.get(
            url, stream=True, timeout=600
        ) as r:  # Timeout long pour gros fichiers
            r.raise_for_status()
            total_size = int(r.headers.get("content-length", 0))
            downloaded_size = 0
            last_print_time = time.time()
            print(
                f"  Taille totale: {total_size / 1024 / 1024:.1f} Mo"
                if total_size > 0
                else "  Taille inconnue."
            )
            with open(dest_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192 * 34):  # Chunk de 128Ko
                    if chunk:  # Filtre les keep-alive chunks
                        f.write(chunk)
                        downloaded_size += len(chunk)
                        now = time.time()
                        if total_size > 0 and (
                            now - last_print_time > 1
                        ):  # MAJ toutes les secondes
                            percent = (downloaded_size / total_size) * 100
                            print(
                                f"    -> {downloaded_size / 1024 / 1024:.1f} / {total_size / 1024 / 1024:.1f} Mo ({percent:.1f}%)",
                                end="\r",
                            )
                            last_print_time = now
            # Assurer que la ligne de progression est effacée
            print(" " * 80, end="\r")
            print(f"  {dest_path.name} téléchargé avec succès.")
        return True
    except requests.exceptions.Timeout:
        print(f"\n  ERREUR: Timeout pendant le téléchargement de {dest_path.name}.")
    except requests.exceptions.RequestException as e:
        print(f"\n  ERREUR pendant le téléchargement de {dest_path.name} : {e}")
    except Exception as e:
        print(
            f"\n  ERREUR inconnue pendant le téléchargement de {dest_path.name} : {e}"
        )


def check_and_download_dump(endpoint, headers, local_dir):
    """Vérifie si un dump local est à jour et le télécharge si nécessaire."""
    print(f"\n--- Vérification Endpoint: {endpoint} ---")
    try:
        url = f"{API_BASE_URL}/dumps/{endpoint}"
        response = requests.get(url, headers=headers, timeout=20)
    except Exception as e:
        logging.error(f"An error occured for this endpoint: {endpoint} - {e}")
        sys.exit()
    local_file_path = local_dir / (endpoint + ".csv")

    url = f"{API_BASE_URL}/dumps/{endpoint}"
    response = requests.get(url, headers=headers, timeout=20)
    s3_url = response.json().get("s3_url")
    if s3_url:
        # Supprimer l'ancien fichier avant de télécharger le nouveau
        if local_file_path.exists():
            print(f"  Suppression de l'ancien fichier {local_file_path.name}...")
            try:
                local_file_path.unlink()
            except OSError as e_del:
                print(
                    f"  ERREUR lors de la suppression de l'ancien {local_file_path.name}: {e_del}"
                )

        # Lancer le téléchargement
        download_dump(s3_url, local_file_path)
    else:
        logging.error(
            f"Impossible d'obtenir l'URL de téléchargement pour '{endpoint}'."
        )
        sys.exit()

    # Si on arrive ici, c'est que needs_download était False
    return local_file_path


def convert_ids_to_names(df, column, target_column):
    """
    Convertit ids en noms à partir d'un DataFrame de référence.
    """
    # Dictionnaire id -> nom
    reference_df = pd.read_csv(f"igdb_datadumps/{column}.csv")
    mapping = reference_df.set_index("id")[target_column].to_dict()

    def convert(value):
        if pd.isna(value) or value == "{}":
            return None

        # Extraire les IDs et les convertir en noms
        ids = [int(x.strip()) for x in str(value).strip("{}").split(",") if x.strip()]
        names = [mapping.get(id, f"Unknown_{id}") for id in ids]
        return ", ".join(names)

    return df[column].apply(convert)
