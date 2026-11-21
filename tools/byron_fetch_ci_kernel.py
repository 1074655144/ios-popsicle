#!/usr/bin/env python3
"""Download the xnu-kernel artifact from a GitHub Actions run.

  python3 tools/byron_fetch_ci_kernel.py RUN_ID OUT_DIR [KERNEL_DEST]

RUN_ID is the xnu workflow run, e.g. 44920089727. OUT_DIR receives the
extracted artifact; KERNEL_DEST defaults to OUT_DIR/kernel.development.pandora.
The script only reads GitHub and writes local files. It never touches the
phone, partitions, AVB, or the CI run itself.

Authentication uses GITHUB_TOKEN when set, otherwise `git credential fill`
for github.com (the same credential the fork push uses).
"""
import hashlib
import io
import os
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
import zipfile

REPO = os.environ.get('REPO', '1074655144/ios-popsicle')
API = 'https://api.github.com'


def token():
    if os.environ.get('GITHUB_TOKEN'):
        return os.environ['GITHUB_TOKEN']
    p = subprocess.run(
        ['git', 'credential', 'fill'],
        input=b'protocol=https\nhost=github.com\n\n',
        capture_output=True,
        timeout=30,
    )
    if p.returncode:
        raise SystemExit('git credential fill failed: ' + p.stderr.decode(errors='replace').strip())
    for line in p.stdout.decode(errors='replace').splitlines():
        if line.startswith('password='):
            return line.split('=', 1)[1]
    raise SystemExit('no GitHub credential found')


class StripAuthOnRedirect(urllib.request.HTTPRedirectHandler):
    """Do not forward the token to a signed artifact host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        r = super().redirect_request(req, fp, code, msg, headers, newurl)
        if r and urllib.parse.urlparse(newurl).netloc != urllib.parse.urlparse(req.full_url).netloc:
            r.headers.pop('Authorization', None)
        return r


def opener(tok):
    return urllib.request.build_opener(StripAuthOnRedirect())


def fetch(op, url, tok, accept=None):
    headers = {
        'Authorization': f'Bearer {tok}',
        'Accept': accept or 'application/vnd.github+json',
        'User-Agent': 'byron-kernel-fetch',
    }
    with op.open(urllib.request.Request(url, headers=headers), timeout=120) as r:
        return r.read()


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    run = sys.argv[1]
    out = os.path.abspath(sys.argv[2])
    dest = os.path.abspath(sys.argv[3]) if len(sys.argv) > 3 else os.path.join(out, 'kernel.development.pandora')
    tok = token()
    op = opener(tok)

    import json
    data = json.loads(fetch(op, f'{API}/repos/{REPO}/actions/runs/{run}/artifacts', tok))
    arts = data.get('artifacts', [])
    if not arts:
        raise SystemExit(f'no artifacts in run {run} (status may not be completed yet)')
    match = [a for a in arts if a.get('name') == 'xnu-kernel']
    if not match:
        raise SystemExit('artifacts: ' + ', '.join(a.get('name', '?') for a in arts))
    art = match[0]
    print(f"artifact: {art['name']} ({art.get('size', 0)} bytes), expired={art.get('expired')}")

    blob = fetch(op, art['archive_download_url'], tok, accept='application/zip')
    os.makedirs(out, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        for info in z.infolist():
            name = info.filename
            if name.startswith('/') or '..' in name.split('/'):
                raise SystemExit(f'unsafe artifact path: {name}')
        z.extractall(out)

    found = []
    for root, _, files in os.walk(out):
        for f in files:
            if f == 'kernel.development.pandora':
                found.append(os.path.join(root, f))
    if not found:
        raise SystemExit('kernel.development.pandora not found in artifact')
    src = found[0]
    if os.path.abspath(src) != dest:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copyfile(src, dest)

    head = open(dest, 'rb').read(4)
    if head not in (b'\xcf\xfa\xed\xfe', b'\xfe\xed\xfa\xcf'):
        raise SystemExit(f'not a Mach-O kernel: {head!r}')
    h = hashlib.sha256()
    with open(dest, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    print(f'kernel: {dest}')
    print(f'sha256: {h.hexdigest()}')


if __name__ == '__main__':
    main()
