"""Scan publication files without printing credentials. Optionally scan reachable Git history."""
import argparse
from pathlib import Path
import re
import subprocess

PATTERNS = {
    "provider_token": re.compile(rb"(?i)(?:sk-[a-z0-9_-]{16,}|gh[pousr]_[a-z0-9]{20,}|github_pat_[a-z0-9_]{20,}|AKIA[A-Z0-9]{16})"),
    "private_key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "password_assignment": re.compile(rb"(?im)^[ \t]*(?:NEO4J_PASSWORD[ \t]*=|password[ \t]*:)[ \t]*[\"']?([^ \t\r\n\"'#]+)[\"']?[ \t\r]*(?:#.*)?$"),
}
TEXT = {".py", ".js", ".cjs", ".mjs", ".md", ".txt", ".json", ".yaml", ".yml", ".html", ".example", ".env", ".toml", ".sh", ".ps1"}


def findings(raw):
    return [(kind, raw[:hit.start()].count(b"\n")+1)
            for kind, pattern in PATTERNS.items() for hit in pattern.finditer(raw)]


def scan_files(root):
    paths = subprocess.check_output(["git", "ls-files", "-z"], cwd=root).split(b"\0")
    result = []
    for entry in paths:
        if not entry:
            continue
        path = Path(entry.decode("utf-8"))
        if path.suffix not in TEXT or not (root/path).is_file():
            continue
        for kind, line in findings((root/path).read_bytes()):
            result.append({"path":path.as_posix(),"line":line,"kind":kind})
    return result


def scan_history(root):
    result = []
    for entry in subprocess.check_output(["git", "rev-list", "--objects", "--all"],cwd=root).splitlines():
        sha, _, name = entry.partition(b" ")
        if not name or Path(name.decode("utf-8")).suffix not in TEXT:
            continue
        raw = subprocess.check_output(["git","cat-file","blob",sha.decode()],cwd=root)
        for kind, line in findings(raw):
            result.append({"path":name.decode("utf-8"),"object":sha.decode()[:12],"line":line,"kind":kind})
    return result


if __name__ == "__main__":
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", action="store_true")
    args = parser.parse_args()
    root=Path(subprocess.check_output(["git","rev-parse","--show-toplevel"],text=True).strip())
    results=scan_files(root)+(scan_history(root) if args.history else [])
    print(json.dumps({"passed":not results,"findings":results,"scope":"tracked files + reachable history" if args.history else "tracked files"},ensure_ascii=False))
    raise SystemExit(bool(results))
