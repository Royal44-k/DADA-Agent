"""Offline archive integrity check; never executes archived upstream code."""
import hashlib
import json
import sys
import zipfile
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


class ReportParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids, self.refs, self.titles = [], [], []
        self.in_title = False
        self.sections = 0
        self.remote_dependencies = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids.append(a["id"])
        if tag == "a" and a.get("href", "").startswith("#"):
            self.refs.append(a["href"][1:])
        if tag == "title":
            self.in_title = True
        if tag == "section":
            self.sections += 1
        if tag in {"script", "img", "iframe", "source"} and a.get("src", "").startswith(("http:", "https:", "//")):
            self.remote_dependencies.append(a["src"])
        if tag == "link" and a.get("rel") == "stylesheet" and a.get("href", "").startswith(("http:", "https:", "//")):
            self.remote_dependencies.append(a["href"])

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False

    def handle_data(self, value):
        if self.in_title:
            self.titles.append(value)


def main():
    manifest = json.loads((ROOT / "ASSET_MANIFEST.json").read_text(encoding="utf-8"))
    expected = {e["path"]: e for e in manifest["files"]}
    require(len(expected) == len(manifest["files"]), "Duplicate manifest entries")
    actual = {p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*") if p.is_file() and "__pycache__" not in p.parts}
    require(actual == set(expected) | {"ASSET_MANIFEST.json", "SHA256SUMS.txt"}, "Unexpected or missing archive files")
    for rel, e in expected.items():
        p = PurePosixPath(rel)
        require(not p.is_absolute() and ".." not in p.parts, f"Unsafe path: {rel}")
        data = (ROOT / rel).read_bytes()
        require(len(data) == e["bytes"] and digest(data) == e["sha256"], f"File mismatch: {rel}")
    checksum_lines = (ROOT / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines()
    sums = {line.split("  ", 1)[1]: line.split("  ", 1)[0] for line in checksum_lines}
    require(set(sums) == set(expected) | {"ASSET_MANIFEST.json"}, "Checksum set mismatch")
    for rel, value in sums.items():
        require(digest((ROOT / rel).read_bytes()) == value, f"Checksum mismatch: {rel}")

    snapshots = []
    for project in ("grok_build", "deepseek_harness", "pi_build"):
        index = json.loads((ROOT / "manifests" / f"{project}.json").read_text(encoding="utf-8"))
        members = {project + "/" + e["path"]: e for e in index["files"]}
        with zipfile.ZipFile(ROOT / "sources" / f"{project}.zip") as z:
            require(len(z.namelist()) == len(set(z.namelist())), f"Duplicate ZIP member: {project}")
            require(set(z.namelist()) == set(members), f"ZIP member mismatch: {project}")
            for name, entry in members.items():
                p = PurePosixPath(name)
                require(not p.is_absolute() and ".." not in p.parts and "\\" not in name, f"Unsafe ZIP path: {name}")
                data = z.read(name)
                require(len(data) == entry["bytes"] and digest(data) == entry["sha256"], f"ZIP content mismatch: {name}")
        snapshots.append({"project": project, "files": len(members)})

    reports = []
    for file, title, sections in (("grok-core-design-analysis.html", "Grok", None), ("deepseek-harness-core-design-analysis.html", "DeepSeek Harness", 13), ("pi-agent-core-design-analysis.html", "Pi Agent", 14)):
        parser = ReportParser()
        parser.feed((ROOT / "reports" / file).read_text(encoding="utf-8"))
        require(title in "".join(parser.titles), f"Wrong report title: {file}")
        require(len(parser.ids) == len(set(parser.ids)), f"Duplicate HTML ID: {file}")
        require(not (set(parser.refs) - set(parser.ids) - {""}), f"Broken HTML anchors: {file}")
        require(not parser.remote_dependencies, f"Remote document dependency: {file}")
        require(sections is None or parser.sections == sections, f"Wrong section count: {file}")
        reports.append({"file": file, "sections": parser.sections})
    pngs = list((ROOT / "previews").rglob("*.png"))
    require(len(pngs) == 12, "Expected 12 PNG previews")
    for p in pngs:
        require(p.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"), f"Invalid PNG: {p.name}")

    bundle_members = {rel for rel in expected if rel.startswith(("reports/", "previews/"))}
    with zipfile.ZipFile(ROOT / "downloads" / "reports-and-previews.zip") as z:
        require(set(z.namelist()) == bundle_members and len(z.namelist()) == len(bundle_members), "Report bundle member mismatch")
        for name in bundle_members:
            require(z.read(name) == (ROOT / name).read_bytes(), f"Report bundle content mismatch: {name}")
    print(json.dumps({"ok": True, "archive_files": len(expected) + 2, "snapshots": snapshots, "source_files": sum(e["files"] for e in snapshots), "reports": reports, "previews": len(pngs)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, zipfile.BadZipFile) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        sys.exit(1)
