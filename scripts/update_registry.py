import os, re, json, zipfile, hashlib, sys
from datetime import datetime
from pathlib import Path

REPO_OWNER = os.environ.get("GITHUB_REPOSITORY", "owner/repo").split("/")[0]
REPO_NAME  = os.environ.get("GITHUB_REPOSITORY", "owner/repo").split("/")[1]
DEFAULT_BRANCH = os.environ.get("DEFAULT_BRANCH", "main")

DIST_DIR = Path("magic/upload")
REGISTRY_PATH = Path("magic/manifest.json")

BUILD_MAP = {
    "A": "stable",
    "B": "rc",
    "C": "beta",
    "D": "alpha",
    "F": "debug",
}

FILENAME_RE = re.compile(r"^(?P<name>[^_]+)_(?P<buildid>[A-Za-z0-9]+)\.magic$")

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def parse_build_type(build_id: str) -> str:
    if build_id:
        letter = build_id[-1].upper()
        return BUILD_MAP.get(letter, "unknown")
    return "unknown"

def read_model_infos_from_magic(magic_path: Path) -> dict:
  with zipfile.ZipFile(magic_path, "r") as z:
    candidate = None
    for name in z.namelist():
      if name.lower().endswith("metadata.json"):
        candidate = name
        break
    if not candidate:
      raise FileNotFoundError(f"Aucun metadata.json dans {magic_path.name}")

    with z.open(candidate) as f:
      data = json.loads(f.read().decode("utf-8"))

  return data

def load_registry() -> dict:
    if REGISTRY_PATH.exists():
        try:
            with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if not content:
                    print(f"[WARN] {REGISTRY_PATH} est vide, création d'un nouveau registry")
                    return {"models": []}
                return json.loads(content)
        except json.JSONDecodeError as e:
            print(f"[WARN] {REGISTRY_PATH} contient du JSON invalide: {e}")
            print("Création d'un nouveau registry")
            return {"models": []}
        except Exception as e:
            print(f"[ERREUR] Impossible de lire {REGISTRY_PATH}: {e}")
            return {"models": []}
    return {"models": []}

def save_registry(registry: dict):
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    registry["models"].sort(key=lambda m: (m.get("name",""), m.get("version","")), reverse=False)
    with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2, ensure_ascii=False)

def upsert_model(registry: dict, model_entry: dict):
    replaced = False
    for i, m in enumerate(registry["models"]):
        if m.get("name")==model_entry.get("name") and m.get("version")==model_entry.get("version"):
            registry["models"][i] = model_entry
            replaced = True
            break
    if not replaced:
        registry["models"].append(model_entry)

def main():
    if not DIST_DIR.exists():
        print("magic/upload/ n'existe pas, rien à faire.")
        return 0

    registry = load_registry()

    magic_files = [p for p in DIST_DIR.glob("*.magic") if p.is_file()]
    if not magic_files:
        print("Aucun .magic trouvé dans magic/upload/.")
        return 0

    for magic_path in magic_files:
        m = FILENAME_RE.match(magic_path.name)
        if not m:
            print(f"Ignore {magic_path.name} (nom inattendu)")
            continue

        name     = m.group("name")
        build_id = m.group("buildid")
        try:
            infos = read_model_infos_from_magic(magic_path)
        except Exception as e:
            print(f"[ERREUR] {magic_path.name}: {e}")
            continue
        version  = infos.get("version", "unknown")
        build_type = parse_build_type(build_id)

        if infos.get("version") and infos["version"] != version:
            print(f"[WARN] version mismatch: filename={version} / infos.json={infos['version']}")

        size_bytes = magic_path.stat().st_size
        sha = sha256_file(magic_path)

        # URL de téléchargement (GitHub par défaut, ou local pour le dev)
        if os.environ.get("DEV_SERVER_IP"):
            dev_ip = os.environ.get("DEV_SERVER_IP")
            dev_port = os.environ.get("DEV_SERVER_PORT", "8000")
            download_url = f"http://{dev_ip}:{dev_port}/magic/upload/{magic_path.name}"
        else:
            download_url = f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/{DEFAULT_BRANCH}/magic/upload/{magic_path.name}"

        compat = infos.get("compatible_versions") or infos.get("compat") or []
        if isinstance(compat, str):
            compat = [compat]

        entry = {
            "name": infos.get("name", name),
            "version": version,
            "author": infos.get("author", "unknown"),
            "date_created": infos.get("date_created") or datetime.utcnow().strftime("%Y-%m-%d"),
            "parameters": infos.get("parameters", {}),
            "compatible_versions": compat,
            "size_bytes": size_bytes,
            "sha256": sha,
            "download_url": download_url,
            "build_id": build_id,
            "build_type": build_type,
        }

        upsert_model(registry, entry)
        print(f"✅ Ajout/MàJ: {entry['name']} {entry['version']} ({build_type})")

    save_registry(registry)
    print(f"💾 Écrit {REGISTRY_PATH}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
