"""Repack conda-forge's free-threaded polars-runtime-32 builds as wheels.

PyPI has no free-threaded (cp314t) polars-runtime-32 wheels, and polars plans
none before Python 3.15.  conda-forge builds them.  This downloads conda-forge's
cp314t build for each platform JMod supports and repacks its site-packages as
a wheel, leaving every installed file byte-identical:

    python repack.py 1.44.2            # wheels into dist/

A conda package is a zip holding pkg-*.tar.zst; its site-packages already holds
the dist-info pip wrote when conda-forge installed maturin's wheel.  The wheel
drops what installing added (INSTALLER, REQUESTED, direct_url.json, __pycache__),
sets the platform tag, and rewrites RECORD.  Wheels are reproducible: entries
are sorted and stamped with the conda package's build time.

Standard library only; needs Python 3.14+ for compression.zstd.
"""

import argparse
import base64
import hashlib
import io
import json
import re
import sys
import tarfile
import time
import urllib.request
import zipfile
from compression import zstd
from pathlib import Path

PACKAGE = "polars-runtime-32"
DIST = "polars_runtime_32"
ABI = "python_abi 3.14.* *_cp314t"
FILES_API = f"https://api.anaconda.org/package/conda-forge/{PACKAGE}/files"

# conda-forge subdir -> wheel platform tags.  The platforms JMod ships to: those
# peppy_sage builds wheels for that conda-forge also builds.  The floors are
# checked against each build's __glibc / __osx requirement in check_floor.
PLATFORMS = {
    "linux-64": ["manylinux_2_17_x86_64", "manylinux2014_x86_64"],
    "linux-aarch64": ["manylinux_2_17_aarch64", "manylinux2014_aarch64"],
    "osx-64": ["macosx_11_0_x86_64"],
    "osx-arm64": ["macosx_11_0_arm64"],
    "win-64": ["win_amd64"],
}
GLIBC_FLOOR = (2, 17)
MACOS_FLOOR = (11, 0)

# Written by the installer, not part of the wheel
DROP = {"INSTALLER", "REQUESTED", "direct_url.json", "RECORD"}


def fetch(url):
    with urllib.request.urlopen(url, timeout=300) as r:
        return r.read()


def builds(version):
    """{subdir: file entry} of the cp314t builds of *version*, the highest
    build number per subdir."""
    chosen = {}
    for f in json.loads(fetch(FILES_API)):
        attrs = f["attrs"]
        if f["version"] != version or ABI not in attrs.get("depends", []):
            continue
        if "main" not in f.get("labels", []):
            continue
        sub = attrs["subdir"]
        if sub in PLATFORMS and (sub not in chosen or attrs["build_number"] > chosen[sub]["attrs"]["build_number"]):
            chosen[sub] = f
    missing = sorted(set(PLATFORMS) - set(chosen))
    if missing:
        sys.exit(f"conda-forge has no {ABI} build of {PACKAGE} {version} for {', '.join(missing)}")
    return chosen


def version_tuple(text):
    return tuple(int(x) for x in text.split("."))


def check_floor(entry):
    """Fail if the build needs a newer glibc or macOS than its wheel tag claims."""
    for dep in entry["attrs"]["depends"]:
        m = re.fullmatch(r"__(glibc|osx) >=([\d.]+)(,.*)?", dep)
        if not m:
            continue
        floor = GLIBC_FLOOR if m.group(1) == "glibc" else MACOS_FLOOR
        if version_tuple(m.group(2)) > floor:
            sys.exit(f"{entry['basename']} needs {m.group(1)} {m.group(2)}, newer than its "
                     f"wheel tag's {'.'.join(map(str, floor))}: update PLATFORMS")


def download(entry):
    data = fetch("https:" + entry["download_url"])
    if hashlib.md5(data).hexdigest() != entry["md5"]:
        sys.exit(f"md5 mismatch downloading {entry['basename']}")
    if entry.get("sha256") and hashlib.sha256(data).hexdigest() != entry["sha256"]:
        sys.exit(f"sha256 mismatch downloading {entry['basename']}")
    return data


def site_packages(conda):
    """{path relative to site-packages: bytes} of a .conda package."""
    with zipfile.ZipFile(io.BytesIO(conda)) as z:
        (pkg,) = [n for n in z.namelist() if n.startswith("pkg-") and n.endswith(".tar.zst")]
        tar = tarfile.open(fileobj=io.BytesIO(zstd.decompress(z.read(pkg))))
    files = {}
    for m in tar.getmembers():
        parts = m.name.split("/")
        if "site-packages" not in parts:
            sys.exit(f"unexpected file outside site-packages: {m.name}")
        if not m.isfile():
            continue
        rel = "/".join(parts[parts.index("site-packages") + 1:])
        files[rel] = tar.extractfile(m).read()
    return files


def record_hash(data):
    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
    return f"sha256={digest}"


def build_wheel(files, version, tags, timestamp, out_dir):
    dist_info = f"{DIST}-{version}.dist-info"
    keep = {}
    for rel, data in files.items():
        if "__pycache__" in rel.split("/"):
            continue
        top, _, name = rel.partition("/")
        if top == dist_info and name in DROP:
            continue
        if top != dist_info and not top.startswith("_polars_runtime_32"):
            sys.exit(f"unexpected top-level entry in site-packages: {rel}")
        keep[rel] = data

    wheel_meta = keep[f"{dist_info}/WHEEL"].decode()
    lines = [ln for ln in wheel_meta.splitlines() if ln and not ln.startswith("Tag:")]
    lines += [f"Tag: cp314-cp314t-{plat}" for plat in tags]
    keep[f"{dist_info}/WHEEL"] = ("\n".join(lines) + "\n").encode()

    record = f"{dist_info}/RECORD"
    rows = [f"{rel},{record_hash(data)},{len(data)}" for rel, data in sorted(keep.items())]
    rows.append(f"{record},,")
    keep[record] = ("\n".join(rows) + "\n").encode()

    name = f"{DIST}-{version}-cp314-cp314t-{'.'.join(tags)}.whl"
    path = out_dir / name
    date_time = time.gmtime(timestamp)[:6]
    # dist-info last, as the wheel spec recommends
    order = sorted(keep, key=lambda rel: (rel.startswith(dist_info + "/"), rel == record, rel))
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in order:
            info = zipfile.ZipInfo(rel, date_time)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o755 if rel.endswith((".so", ".pyd")) else 0o644) << 16
            z.writestr(info, keep[rel])
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("version", help="polars version, e.g. 1.44.2")
    parser.add_argument("--out", type=Path, default=Path("dist"), help="output folder (default dist)")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    for sub, entry in sorted(builds(args.version).items()):
        check_floor(entry)
        files = site_packages(download(entry))
        # conda timestamps are in milliseconds; zip can not go before 1980
        timestamp = max(entry["attrs"]["timestamp"] / 1000, 315532800)
        path = build_wheel(files, args.version, PLATFORMS[sub], timestamp, args.out)
        print(f"{entry['basename']} -> {path}")


if __name__ == "__main__":
    main()
