"""Download a Hugging Face model snapshot and package it as a SageMaker model.tar.gz."""

# --- START MODIFICATION ---
# Ruff CI fixes: drop shebang (EXE001), unused sys (F401), bare raise (TRY201)
# --- END MODIFICATION ---

import argparse
import os
import tarfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description="Download a Hugging Face model and create a SageMaker model.tar.gz"
    )
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--local-dir", required=True)
    parser.add_argument("--tarball", required=True)
    parser.add_argument("--skip-if-exists", action="store_true")
    args = parser.parse_args()

    local_dir = Path(args.local_dir)
    extracted_dir = local_dir / "extracted"
    tarball_path = Path(args.tarball)

    if args.skip_if_exists and tarball_path.exists():
        print(f"Tarball already exists at {tarball_path}; skipping.")
        return

    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        print("huggingface_hub is not installed. Run: pip install huggingface_hub")
        raise

    local_dir.mkdir(parents=True, exist_ok=True)
    extracted_dir.mkdir(parents=True, exist_ok=True)

    print(f"Downloading {args.model_id} to {extracted_dir} ...")
    snapshot_download(
        repo_id=args.model_id,
        local_dir=str(extracted_dir),
        local_dir_use_symlinks=False,
    )

    print(f"Packaging {extracted_dir} into {tarball_path} ...")
    tarball_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tarball_path, "w:gz") as tf:
        for root, _dirs, files in os.walk(extracted_dir):
            for file in files:
                full_path = Path(root) / file
                arcname = full_path.relative_to(extracted_dir).as_posix()
                tf.add(str(full_path), arcname=arcname)

    print(f"Created {tarball_path} ({tarball_path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
