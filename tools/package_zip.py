"""Build the release ZIP and check it.

    python tools/package_zip.py [output.zip]

Excludes: virtual environments, caches, git metadata, every database (local/test data), generated ratewatch data,
and third-party files that must not be redistributed (TD's calculator files). Keeps dotfiles such as
.github/workflows, .gitignore and .env.example.
"""
import fnmatch
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".venv", "venv", "__pycache__", ".pytest_cache", ".git", "node_modules", ".mypy_cache"}
SKIP_PATHS = ("data/ratewatch/td_oracle/", "data/ratewatch/osfi/")
SKIP_FILES = ("*.db", "*.sqlite", "*.sqlite3", "*.pyc", "*.log", ".env", "data/ratewatch/backfill_progress.json",
              "data/ratewatch/alerts.csv", "data/ratewatch/url_overrides.json")
MUST_HAVE = (".github/workflows/ci.yml", ".gitignore", ".env.example", "README.md", "LICENSE", "requirements.txt",
             "backend/renewal/ratewatch/ird.py", "tools/td_oracle.mjs")


def included(rel: str) -> bool:
    parts = rel.split("/")
    if any(p in SKIP_DIRS for p in parts[:-1]):
        return False
    if any(rel.startswith(p) for p in SKIP_PATHS):
        return False
    return not any(fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(parts[-1], pat) for pat in SKIP_FILES)


def build(out: Path) -> list[str]:
    names = []
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for path in sorted(ROOT.rglob("*")):
            if not path.is_file() or path.resolve() == out.resolve():
                continue
            rel = path.relative_to(ROOT).as_posix()          # keeps leading dots (.github, .gitignore)
            if included(rel):
                z.write(path, rel)
                names.append(rel)
    return names


def check(out: Path) -> None:
    with zipfile.ZipFile(out) as z:
        names = set(z.namelist())
        assert z.testzip() is None, "corrupt member"
    missing = [m for m in MUST_HAVE if m not in names]
    leaked = [n for n in names if n.endswith((".db", ".sqlite", ".sqlite3")) or n.startswith("data/ratewatch/td_oracle/")]
    assert not missing, f"missing from zip: {missing}"
    assert not leaked, f"must not be in zip: {leaked}"


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT.parent / "renewal-radar-enterprise-v18-code.zip"
    names = build(out)
    check(out)
    print(f"{out}  {len(names)} files  {out.stat().st_size / 1e6:.1f} MB  (checked)")
