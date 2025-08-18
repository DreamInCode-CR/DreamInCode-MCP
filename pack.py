# pack.py
import os, re, zipfile
INCLUDE = [
    r"^application\.py$",
    r"^requirements\.txt$",
    r"^mcp_api/.*",
    r"^mcp/.*",
    r"^bin/.*",         # (opcional: para ffmpeg/ffprobe locales)
]
EXCLUDE_DIRS = {"venv", ".venv", "antenv", "__pycache__", ".git", ".vscode"}
EXCLUDE_FILES = {".DS_Store", "Thumbs.db", "package.zip"}

def norm(p):  # siempre con /
    return p.replace("\\", "/")

def should_take(arcname):
    a = norm(arcname)
    if any(part in EXCLUDE_DIRS for part in a.split("/")): return False
    if os.path.basename(a) in EXCLUDE_FILES: return False
    return any(re.match(pat, a) for pat in INCLUDE)

def main():
    seen = set()
    with zipfile.ZipFile("package.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk("."):
            # filtra dirs excluidas
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            for f in files:
                abs_path = os.path.join(root, f)
                arcname = norm(os.path.relpath(abs_path, "."))
                if should_take(arcname) and arcname not in seen:
                    z.write(abs_path, arcname)
                    seen.add(arcname)
    print("OK -> package.zip")

if __name__ == "__main__":
    main()
