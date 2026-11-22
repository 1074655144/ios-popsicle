#!/usr/bin/env python3
"""Resilient GitHub Actions artifact downloader with parallel HTTP Range resume.

Usage:
  python3 tools/byron_fetch_artifact_resume.py ARTIFACT_ID OUT_DIR [--workers N]

The artifact is fetched by id from the configured REPO, verified against the
SHA256 digest published by the API, then unpacked into OUT_DIR with path
traversal checks. Partial chunk files (*.part.NN) are kept next to the final
zip so an interrupted download can be resumed by rerunning the same command.

Reads GitHub only; never touches the phone, partitions, AVB, or CI runs.
"""
import argparse
import concurrent.futures
import hashlib
import io
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import zipfile

REPO = os.environ.get('REPO', '1074655144/ios-popsicle')
API = 'https://api.github.com'
CHUNK = 4 << 20  # 4 MiB per Range request
PRINT_LOCK = threading.Lock()


def token():
    if os.environ.get('GITHUB_TOKEN'):
        return os.environ['GITHUB_TOKEN']
    p = subprocess.run(
        ['git', 'credential', 'fill'],
        input=b'protocol=https\nhost=github.com\n\n',
        capture_output=True, timeout=30,
    )
    if p.returncode:
        raise SystemExit('git credential fill failed: ' + p.stderr.decode(errors='replace').strip())
    for line in p.stdout.decode(errors='replace').splitlines():
        if line.startswith('password='):
            return line.split('=', 1)[1]
    raise SystemExit('no GitHub credential found')


class StripAuthOnRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        r = super().redirect_request(req, fp, code, msg, headers, newurl)
        if r and urllib.parse.urlparse(newurl).netloc != urllib.parse.urlparse(req.full_url).netloc:
            r.headers.pop('Authorization', None)
        return r


OPENER = urllib.request.build_opener(StripAuthOnRedirect())


def api_get(url, tok):
    req = urllib.request.Request(url, headers={
        'Authorization': f'Bearer {tok}',
        'Accept': 'application/vnd.github+json',
        'User-Agent': 'byron-artifact-resume',
    })
    with OPENER.open(req, timeout=90) as r:
        return __import__('json').loads(r.read())


def resolve_blob(download_url, tok):
    """Follow the API redirect once and return the signed blob URL."""
    req = urllib.request.Request(download_url, headers={
        'Authorization': f'Bearer {tok}',
        'Accept': 'application/vnd.github+json',
        'User-Agent': 'byron-artifact-resume',
    })
    with OPENER.open(req, timeout=90) as r:
        return r.geturl()


def get_blob(tok, url_holder, lock):
    with lock:
        return url_holder[0]


def refresh_blob(tok, url_holder, lock, download_url):
    with lock:
        url_holder[0] = resolve_blob(download_url, tok)
        return url_holder[0]


def fetch_chunk(args):
    idx, start, end, part, tok, url_holder, lock, download_url = args
    want = end - start + 1
    for attempt in range(8):
        have = os.path.getsize(part) if os.path.exists(part) else 0
        if have >= want:
            return idx, have, 'cached'
        url = get_blob(tok, url_holder, lock)
        try:
            req = urllib.request.Request(url, headers={
                'Range': f'bytes={start + have}-{end}',
                'User-Agent': 'byron-artifact-resume',
            })
            with urllib.request.urlopen(req, timeout=180) as r:
                status = r.status
                if status == 200:  # server ignored Range: take from the beginning
                    have = 0
                data = r.read()
            if not data:
                raise IOError('empty response')
            mode = 'wb' if have == 0 else 'ab'
            with open(part, mode) as f:
                f.write(data)
            have = os.path.getsize(part)
            if have >= want:
                return idx, have, 'ok'
            raise IOError(f'short chunk {have}/{want}')
        except Exception as e:
            msg = str(e)[:120]
            if '403' in msg or '410' in msg or 'Expired' in msg or 'expired' in msg:
                refresh_blob(tok, url_holder, lock, download_url)
            with PRINT_LOCK:
                print(f'  chunk {idx} attempt {attempt + 1}: {msg}', flush=True)
            time.sleep(min(2 ** attempt, 10))
    raise SystemExit(f'chunk {idx} failed after 8 attempts')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('artifact_id', type=int)
    ap.add_argument('out_dir')
    ap.add_argument('--workers', type=int, default=12)
    a = ap.parse_args()

    tok = token()
    art = api_get(f'{API}/repos/{REPO}/actions/artifacts/{a.artifact_id}', tok)
    size = art['size_in_bytes']
    digest = (art.get('digest') or '').split(':', 1)[-1]
    print(f"artifact {art['name']} id={a.artifact_id} size={size} sha256={digest} expired={art.get('expired')}", flush=True)
    if art.get('expired'):
        raise SystemExit('artifact expired')

    out = os.path.abspath(a.out_dir)
    os.makedirs(out, exist_ok=True)
    zpath = os.path.join(out, f"artifact-{a.artifact_id}.zip")
    total_parts = (size + CHUNK - 1) // CHUNK
    url_holder = [resolve_blob(art['archive_download_url'], tok)]
    lock = threading.Lock()

    jobs = []
    for i in range(total_parts):
        start = i * CHUNK
        end = min(start + CHUNK, size) - 1
        jobs.append((i, start, end, zpath + f'.part.{i:04d}', tok, url_holder, lock, art['archive_download_url']))

    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as ex:
        for fut in concurrent.futures.as_completed([ex.submit(fetch_chunk, j) for j in jobs]):
            idx, n, how = fut.result()
            done += 1
            with PRINT_LOCK:
                print(f'  chunk {idx}/{total_parts - 1}: {n} bytes ({how}), {done}/{total_parts}', flush=True)

    h = hashlib.sha256()
    with open(zpath, 'wb') as outf:
        for i in range(total_parts):
            part = zpath + f'.part.{i:04d}'
            with open(part, 'rb') as f:
                for block in iter(lambda: f.read(1 << 20), b''):
                    h.update(block)
                    outf.write(block)
    got = h.hexdigest()
    print(f'zip sha256: {got}', flush=True)
    if digest and got != digest:
        raise SystemExit(f'sha256 mismatch: expected {digest}')
    for i in range(total_parts):
        os.remove(zpath + f'.part.{i:04d}')

    with zipfile.ZipFile(zpath) as z:
        names = z.namelist()
        for name in names:
            if name.startswith('/') or '..' in name.split('/'):
                raise SystemExit(f'unsafe artifact path: {name}')
        z.extractall(out)
    print(f'extracted {len(names)} files into {out}', flush=True)
    for name in names[:20]:
        print('  ', name, flush=True)


if __name__ == '__main__':
    main()
