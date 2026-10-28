"""Prepare local source and IBM SPSS Extension Hub review archives.

This tool does not publish, contact IBM, rebuild the installed extension or
change an existing release. It uses only Python's standard library.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
from io import BytesIO
import json
from pathlib import Path, PurePosixPath
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SUBMISSION = ROOT / "submission"
ARTIFACTS = SUBMISSION / "artifacts"
ZIP_DATE = (2026, 10, 28, 0, 0, 0)
ROOT_FILES = (
    "PATHLAB.py", "PATHLAB.xml", "setup.pyw", "PathLab-Setup.cmd",
    "requirements.txt", "README.md", "VALIDATION.md", "AUTHORS.txt",
    "CITATION.txt", "source-provenance.json", "LICENSE",
    "THIRD-PARTY-NOTICES.txt", "MAINTAINER.txt",
)
OPTIONAL_ROOT_FILES = (".gitignore", "RELEASE-NOTES.txt")
RUNTIME_FILES = (
    "__init__.py", "adapter.py", "branding.py", "core.py", "errors.py",
    "models.py", "plots.py", "report.py", "viewer.py",
)
SUBMISSION_FILES = (
    "metadata.json", "DEVELOPMENT.txt", "START-HERE.txt",
)
SOURCE_FOLDERS = {
    "pathlab_spss": {".py", ".json"},
    "dialog": {".xml", ".properties", ".htm", ".html", ".png"},
    "examples": {".csv", ".png", ".txt", ".md"},
    "tests": {".py", ".json", ".csv"},
    "tools": {".py", ".cmd", ".txt"},
    "validation": {".json", ".png"},
}


def sha256(content):
    return hashlib.sha256(content).hexdigest()


def literal_constant(filename, name):
    """Read version and identity without importing the numerical runtime."""
    tree = ast.parse(filename.read_text(encoding="utf-8"), filename=str(filename))
    for statement in tree.body:
        if isinstance(statement, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == name
                   for target in statement.targets):
                return ast.literal_eval(statement.value)
    raise ValueError("Required constant %s is missing from %s." % (name, filename.name))


def load_metadata():
    required = [ROOT / name for name in ROOT_FILES]
    required += [ROOT / "pathlab_spss" / name for name in RUNTIME_FILES]
    required += [SUBMISSION / "metadata.json"]
    missing = [str(path.relative_to(ROOT)) for path in required if not path.is_file()]
    if missing:
        raise ValueError("Required source files are missing: " + ", ".join(missing))
    version = literal_constant(ROOT / "pathlab_spss/__init__.py", "__version__")
    branding = ROOT / "pathlab_spss/branding.py"
    developer = {
        "name": literal_constant(branding, "AUTHOR"),
        "title": literal_constant(branding, "TITLE"),
        "affiliation": literal_constant(branding, "AFFILIATION"),
    }
    developer["credit"] = "Developed by " + developer["name"]
    metadata = json.loads((SUBMISSION / "metadata.json").read_text(encoding="utf-8"))
    if metadata.get("version") != version:
        raise ValueError("Submission version must match the runtime version %s." % version)
    supplied = metadata.get("developer")
    if not isinstance(supplied, dict) or any(supplied.get(key) != value
                                             for key, value in developer.items()):
        raise ValueError("Submission developer credit must match branding.py exactly.")
    if not isinstance(metadata.get("pending_actions", []), list):
        raise ValueError("Submission pending_actions must be a JSON list.")
    return version, developer, metadata


def folder_entries(folder, suffixes):
    directory = ROOT / folder
    if not directory.is_dir():
        return {}
    entries = {}
    for file in sorted(directory.rglob("*")):
        if not file.is_file() or file.is_symlink() or file.suffix.lower() not in suffixes:
            continue
        relative = file.relative_to(ROOT)
        if any(part in {"__pycache__", ".git", "dist", "artifacts"}
               for part in relative.parts):
            continue
        entries[relative.as_posix()] = file.read_bytes()
    return entries


def source_entries():
    """A standalone extension source tree, excluding the surrounding website."""
    entries = {name: (ROOT / name).read_bytes() for name in ROOT_FILES}
    for name in OPTIONAL_ROOT_FILES:
        file = ROOT / name
        if file.is_file():
            entries[name] = file.read_bytes()
    for folder, suffixes in SOURCE_FOLDERS.items():
        entries.update(folder_entries(folder, suffixes))
    for name in SUBMISSION_FILES:
        file = SUBMISSION / name
        if file.is_file():
            entries["submission/" + name] = file.read_bytes()
    return entries


def archive(entries):
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=9) as target:
        for name in sorted(entries):
            relative = PurePosixPath(name)
            if relative.is_absolute() or ".." in relative.parts or ":" in name or "\\" in name:
                raise ValueError("Unsafe archive path: " + name)
            info = zipfile.ZipInfo(name, date_time=ZIP_DATE)
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            target.writestr(info, entries[name], compress_type=zipfile.ZIP_DEFLATED,
                            compresslevel=9)
    return buffer.getvalue()


def required_documents():
    documents = {}
    for suffix in (".docx", ".pdf"):
        name = "PathLab-Submission-Dossier" + suffix
        candidates = (SUBMISSION / "documents" / name, SUBMISSION / name)
        file = next((path for path in candidates if path.is_file()), None)
        if file is None:
            raise ValueError("Required review document is missing: submission/documents/" + name)
        documents["documents/" + name] = file.read_bytes()
    return documents


def prepare(source_only=False):
    version, developer, metadata = load_metadata()
    release_names = ("PathLab-%s.spe" % version, "PathLab-SPSS-%s.zip" % version)
    if source_only:
        documents, releases = {}, {}
    else:
        documents = required_documents()
        releases = {}
        for name in release_names:
            file = ROOT / "dist" / name
            if not file.is_file():
                raise ValueError("Existing release is missing: dist/" + name)
            releases["release/" + name] = file.read_bytes()
        if not list((SUBMISSION / "drafts").glob("*.txt")):
            raise ValueError("No submission/drafts/*.txt files were found.")
        missing = [name for name in SUBMISSION_FILES if not (SUBMISSION / name).is_file()]
        if missing:
            raise ValueError("Required review files are missing: " + ", ".join(missing))

    source_name = "PathLab-SPSS-%s-source.zip" % version
    source_data = archive(source_entries())
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    (ARTIFACTS / source_name).write_bytes(source_data)
    result = {
        "status": metadata.get("submission_status", "prepared_for_local_review"),
        "version": version,
        "developer": developer,
        "source_archive": source_name,
        "source_sha256": sha256(source_data),
        "source_only": source_only,
        "published_or_submitted": bool(metadata.get("published") or metadata.get("sent_to_ibm")),
    }
    if source_only:
        return result

    entries = dict(releases)
    entries.update(documents)
    entries["source/" + source_name] = source_data
    for file in sorted((SUBMISSION / "drafts").glob("*.txt")):
        if file.is_file() and not file.is_symlink():
            entries["drafts/" + file.name] = file.read_bytes()
    for name in SUBMISSION_FILES:
        entries[name] = (SUBMISSION / name).read_bytes()
    for name in ("LICENSE", "THIRD-PARTY-NOTICES.txt", "MAINTAINER.txt", *OPTIONAL_ROOT_FILES):
        file = ROOT / name
        if file.is_file():
            entries[name] = file.read_bytes()
    qa_file = SUBMISSION / "QA-CHECKS.json"
    if qa_file.is_file():
        entries[qa_file.name] = qa_file.read_bytes()
    entries.update(folder_entries("validation", {".json", ".png"}))
    entries.update(folder_entries("examples", {".csv", ".png", ".txt", ".md"}))
    manifest = {
        "status": metadata.get("submission_status", "prepared_for_local_review"),
        "published_or_submitted": bool(metadata.get("published") or metadata.get("sent_to_ibm")),
        "version": version,
        "developer": metadata["developer"],
        "contact": metadata.get("contact"),
        "license": metadata.get("license"),
        "pending_actions": metadata.get("pending_actions", []),
        "metadata_sha256": sha256((SUBMISSION / "metadata.json").read_bytes()),
        "source_archive": {"path": "source/" + source_name,
                           "sha256": sha256(source_data)},
        "original_releases": [{"path": name, "sha256": sha256(content)}
                              for name, content in sorted(releases.items())],
        "note": "This local review archive does not indicate IBM acceptance or listing. "
                "License, publication and compatibility status are recorded in metadata.json.",
    }
    manifest_data = (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    entries["review-manifest.json"] = manifest_data
    entries["SHA256SUMS.txt"] = ("".join("%s  %s\n" % (sha256(content), name)
                                       for name, content in sorted(entries.items()))).encode("utf-8")
    review_name = "PathLab-SPSS-%s-submission-review.zip" % version
    review_data = archive(entries)
    (ARTIFACTS / review_name).write_bytes(review_data)
    (ARTIFACTS / "review-manifest.json").write_bytes(manifest_data)
    result.update(review_archive=review_name, review_sha256=sha256(review_data),
                  review_entries=len(entries), pending_actions=manifest["pending_actions"])
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-only", action="store_true",
                        help="Build standalone source without requiring review documents or releases.")
    arguments = parser.parse_args()
    try:
        print(json.dumps(prepare(arguments.source_only), indent=2, ensure_ascii=False))
    except (OSError, ValueError, SyntaxError, zipfile.BadZipFile) as error:
        parser.exit(1, "Submission preparation stopped: %s\n" % error)
