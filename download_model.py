"""
download_model.py - Downloader for SmolLM2 1.7B Instruct GGUF (q8_0)
Downloads the model to Researcher/models/ for dedicated research synthesis.
"""

import os
import sys

REPO_ID = "bartowski/SmolLM2-1.7B-Instruct-GGUF"
FILENAME = "SmolLM2-1.7B-Instruct-Q8_0.gguf"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(BASE_DIR, "models")
TARGET_PATH = os.path.join(MODELS_DIR, FILENAME)


def download_model(force: bool = False) -> str:
    """Downloads SmolLM2-1.7B-Instruct-Q8_0.gguf into Researcher/models/."""
    os.makedirs(MODELS_DIR, exist_ok=True)

    if os.path.exists(TARGET_PATH) and not force:
        file_size_mb = os.path.getsize(TARGET_PATH) / (1024 * 1024)
        print(f"[*] Model already exists at: {TARGET_PATH} ({file_size_mb:.2f} MB)")
        return TARGET_PATH

    print(f"[*] Downloading {FILENAME} from {REPO_ID} to {MODELS_DIR}...")
    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        print("[-] huggingface_hub not installed. Please install it with:")
        print("    pip install huggingface_hub")
        sys.exit(1)

    downloaded_path = hf_hub_download(
        repo_id=REPO_ID,
        filename=FILENAME,
        local_dir=MODELS_DIR,
        local_dir_use_symlinks=False
    )

    print(f"[+] Download complete: {downloaded_path}")
    return downloaded_path


if __name__ == "__main__":
    force_download = "--force" in sys.argv
    download_model(force=force_download)
