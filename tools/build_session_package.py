"""Package this conversation's existing assets; use only Python's standard library."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIELDS = ('label', 'rounds', 'ctx', 'hard_pair', 'history', 'text', 'asr_noise', 'src')
COUNTS = dict(zip('abcdefghijklm', [113, 111, 98, 101, 89, 110, 101, 102, 101, 84, 101, 87, 102]))
PACKAGE = 'Technique-DADA-assets-2026-09-13.zip'
DATASET = '测试集-1300.zip'
SENSITIVE = {
    'private_key': r'-----BEGIN (?:OPENSSH |RSA |EC |DSA )?PRIVATE KEY-----',
    'github_token': r'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{35,})\b',
    'api_token': r'\bsk-[A-Za-z0-9_-]{20,}\b',
    'aws_key': r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b',
    'bearer': r'(?i)bearer\s+[A-Za-z0-9_.-]{30,}',
    'credential_url': r'[a-z]+://[^\s/@:]+:[^\s/@]+@',
    'credential_assignment': r'''(?i)["']?(?:api[_-]?key|access[_-]?token|client[_-]?secret)["']?\s*[:=]\s*["']([A-Za-z0-9_./+=-]{24,})["']''',
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def rows(data):
    return [json.loads(line) for line in data.decode('utf-8-sig').splitlines() if line.strip()]


def check(condition, message):
    if not condition:
        raise ValueError(message)


def pack(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, content in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 9, 13, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, content, compresslevel=9)
    result = buffer.getvalue()
    with zipfile.ZipFile(io.BytesIO(result)) as archive:
        check(archive.testzip() is None, 'ZIP CRC mismatch')
        check(set(archive.namelist()) == set(files), 'ZIP member set mismatch')
        for name, content in files.items():
            check(archive.read(name) == content, f'ZIP content mismatch: {name}')
    return result


def source_path(workspace, relative):
    if relative.startswith('datasets/corrected-v3-1300/'):
        return workspace / '测试集-1300' / Path(relative).name
    if relative.startswith('experiments/early-fg-isolation/'):
        return Path('C:/Users/lenovo/.codex/visualizations/2026/08/06/019fd598-1f9a-7d60-a8c6-9f5d0378fe4d') / Path(relative).name
    if relative.startswith('experiments/'):
        candidate = workspace / relative.removeprefix('experiments/')
        return candidate if candidate.exists() else workspace / Path(relative).name
    if relative.startswith('reference/'):
        return Path('C:/Users/lenovo/Downloads') / Path(relative).name
    if relative.startswith('docs/historical-plans/'):
        name = Path(relative).name
        group = 'specs' if name.endswith('-design.md') else 'plans'
        return workspace / 'docs/superpowers' / group / name
    raise ValueError(f'Unknown source mapping: {relative}')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-workspace', type=Path, help='Optional local originals for byte comparison')
    args = parser.parse_args()
    manifest = json.loads((ROOT / 'ASSET_MANIFEST.json').read_text(encoding='utf-8'))
    check(manifest['source_assets'] == len(manifest['files']) == 132, 'Source count mismatch')
    for entry in manifest['files']:
        data = (ROOT / entry['path']).read_bytes()
        check(len(data) == entry['bytes'] and sha(data) == entry['sha256'], f'Source hash mismatch: {entry["path"]}')
        if args.source_workspace:
            original = source_path(args.source_workspace, entry['path']).read_bytes()
            check(original == data, f'Original file differs: {entry["path"]}')

    stateful = ROOT / 'experiments/2026-08-20-dada-1300-stateful-retest'
    source = rows((stateful / 'sample-1300-corrected-v3-2026-08-20.jsonl').read_bytes())
    check(len(source) == len({row['sample_id'] for row in source}) == 1300, 'v3 ID count mismatch')
    dataset_dir = ROOT / 'datasets/corrected-v3-1300'
    check(sorted(p.name for p in dataset_dir.iterdir()) == [f'{label}.jsonl' for label in COUNTS], 'Dataset file layout mismatch')
    dataset_files, actual_counts = {}, {}
    for label in COUNTS:
        data = (dataset_dir / f'{label}.jsonl').read_bytes()
        records = rows(data)
        expected = [{key: row[key] for key in FIELDS} for row in source if row['label'] == label]
        check(records == expected, f'v3 content/order mismatch: {label}')
        check(all(tuple(row) == FIELDS for row in records), f'Field order mismatch: {label}')
        actual_counts[label] = len(records)
        dataset_files[f'测试集-1300/{label}.jsonl'] = data
    check(actual_counts == COUNTS, 'Label distribution mismatch')
    dataset_zip = pack(dataset_files)

    legacy_paths = [line.split('  ', 1)[1] for line in (ROOT / 'SHA256SUMS.txt').read_text(encoding='utf-8').splitlines() if line]
    additions = ['docs/SESSION_ASSETS.md', 'docs/TESTSET_1300.md', 'tools/build_session_package.py']
    payload = {name: (ROOT / name).read_bytes() for name in sorted(set(legacy_paths + additions))}
    session_text = (ROOT / 'docs/SESSION_ASSETS.md').read_text(encoding='utf-8')
    snapshot_text = '\n'.join(line for line in session_text.splitlines() if PACKAGE not in line) + '\n'
    payload['docs/SESSION_ASSETS.md'] = snapshot_text.encode('utf-8')

    def root_link(match):
        target = match.group(2)
        if '://' in target or target.startswith('#'):
            return match.group(0)
        target = target[3:] if target.startswith('../') else 'docs/' + target
        return f'[{match.group(1)}]({target})'

    payload['README.md'] = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', root_link, snapshot_text).encode('utf-8')
    payload['downloads/' + DATASET] = dataset_zip
    payload['downloads/SHA256SUMS.txt'] = f'{sha(dataset_zip)}  {DATASET}\n'.encode('utf-8')

    findings = []
    for name, content in payload.items():
        if name.endswith('.zip'):
            continue
        text = content.decode('utf-8-sig')
        for kind, pattern in SENSITIVE.items():
            for match in re.finditer(pattern, text):
                findings.append({'path': name, 'kind': kind, 'line': text.count('\n', 0, match.start()) + 1})
    check(not findings, f'Credential scan findings (values withheld): {findings}')

    payload['SHA256SUMS.txt'] = ''.join(f'{sha(content)}  {name}\n' for name, content in sorted(payload.items())).encode('utf-8')
    package_zip = pack(payload)
    with tempfile.TemporaryDirectory(prefix='technique-dada-verify-') as temp:
        with zipfile.ZipFile(io.BytesIO(package_zip)) as archive:
            archive.extractall(temp)
        import subprocess
        import sys
        result = subprocess.run([sys.executable, str(Path(temp) / 'tools/verify_archive.py')], capture_output=True)
        check(result.returncode == 0, 'Extracted archive verification failed: ' + result.stderr.decode('utf-8', errors='replace'))

    report = {
        'date': '2026-09-13', 'repository': 'Royal44-k/Technique', 'status': 'PASS',
        'source_assets': len(manifest['files']), 'local_originals_byte_compared': bool(args.source_workspace),
        'jsonl_files': 13, 'dataset_rows': sum(actual_counts.values()), 'label_counts': actual_counts,
        'v3_fields_and_order_match': True, 'credential_pattern_findings': len(findings),
        'zip_crc_and_members_verified': True, 'extracted_offline_verifier': 'PASS',
        'model_retest_performed': False,
        'archives': {PACKAGE: {'bytes': len(package_zip), 'sha256': sha(package_zip), 'members': len(payload)},
                     DATASET: {'bytes': len(dataset_zip), 'sha256': sha(dataset_zip), 'members': 13}},
    }
    (ROOT / 'downloads' / PACKAGE).write_bytes(package_zip)
    (ROOT / 'downloads' / DATASET).write_bytes(dataset_zip)
    download_sums = ROOT / 'downloads/SHA256SUMS.txt'
    old_lines = [line for line in download_sums.read_text(encoding='utf-8').splitlines() if line and line.split('  ', 1)[1] not in {PACKAGE, DATASET}]
    download_sums.write_text('\n'.join(old_lines + [f'{sha(package_zip)}  {PACKAGE}', f'{sha(dataset_zip)}  {DATASET}']) + '\n', encoding='utf-8', newline='\r\n')
    # The root table describes the current readable archive; the original ZIP stays a historical snapshot.
    (ROOT / 'SHA256SUMS.txt').write_text(''.join(f'{sha((ROOT / name).read_bytes())}  {name}\n' for name in legacy_paths), encoding='utf-8', newline='\r\n')
    (ROOT / 'docs/SESSION_VERIFICATION.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
