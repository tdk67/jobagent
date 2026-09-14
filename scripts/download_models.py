import os
import urllib.request
from pathlib import Path
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants
# Replace these URLs with the actual download links from your GitHub Release once published.
GITHUB_RELEASE_URL_PIPELINE = "https://github.com/tdk67/jobagent/releases/download/v1.0.0/pipeline.pkl"
GITHUB_RELEASE_URL_ENCODER = "https://github.com/tdk67/jobagent/releases/download/v1.0.0/label_encoder.pkl"

MODELS_DIR = Path("models/email_classifier")

def download_file(url: str, dest_path: Path):
    if dest_path.exists():
        logger.info(f"File {dest_path.name} already exists. Skipping download.")
        return

    logger.info(f"Downloading {dest_path.name} from {url}...")
    try:
        urllib.request.urlretrieve(url, dest_path)
        logger.info(f"Successfully downloaded {dest_path.name}.")
    except Exception as e:
        logger.error(f"Failed to download {dest_path.name}: {e}")
        logger.error("Please ensure the GitHub Release URLs are correct and publicly accessible.")

def main():
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    
    # You can update these URLs once you create the GitHub release
    models_to_download = [
        (GITHUB_RELEASE_URL_PIPELINE, MODELS_DIR / "pipeline.pkl"),
        (GITHUB_RELEASE_URL_ENCODER, MODELS_DIR / "label_encoder.pkl"),
    ]
    
    for url, path in models_to_download:
        if "YOUR_USERNAME" in url:
            logger.warning(f"Skipping {path.name}: Placeholder URL detected. Please update the URL in scripts/download_models.py")
            continue
        download_file(url, path)

if __name__ == "__main__":
    main()
