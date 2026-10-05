"""Verify and optionally build the source archive in an isolated release context."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile
import tempfile

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser()
parser.add_argument("--build",action="store_true",help="Build Linux API/web images from the extracted release")
args=parser.parse_args()
version=json.loads((ROOT/"package.json").read_text())["version"]
prefix="mv-signal-"+version
archive=ROOT/"artifacts/releases"/(prefix+".tar.gz")
expected=archive.with_suffix(".gz.sha256").read_text().split()[0]
hasher=hashlib.sha256()
with archive.open("rb") as source:
    for chunk in iter(lambda:source.read(1024*1024),b""):hasher.update(chunk)
assert hasher.hexdigest()==expected,"Archive checksum mismatch"
parent=ROOT/"artifacts/release-build"
parent.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory(prefix="verify-",dir=parent) as temporary:
    target=Path(temporary).resolve()
    assert target.is_relative_to(parent.resolve()),"Extraction must stay in the release workspace"
    with tarfile.open(archive,"r:gz") as bundle:
        manifest=json.load(bundle.extractfile(prefix+"/release-manifest.json"))
        assert manifest["version"]==version
        for member in bundle.getmembers():
            path=PurePosixPath(member.name)
            assert member.isfile() and path.parts[0]==prefix and ".." not in path.parts and not path.is_absolute(),"Invalid archive path/type"
            relative=path.relative_to(prefix).as_posix()
            if relative!="release-manifest.json":
                assert relative in manifest["files"],"Unexpected archive file"
                assert hashlib.sha256(bundle.extractfile(member).read()).hexdigest()==manifest["files"][relative],relative
        assert len(bundle.getmembers())==len(manifest["files"])+1
        bundle.extractall(target,filter="data")
    if args.build:
        docker=shutil.which("docker") or r"C:\Program Files\Docker\Docker\resources\bin\docker.exe"
        for service in ("api","web"):
            dockerfile="services/api/Dockerfile" if service=="api" else "apps/web/Dockerfile"
            subprocess.run([docker,"build","-f",dockerfile,"-t","mv-signal-release-"+service+":"+version,"."],cwd=target/prefix,check=True)
    # TemporaryDirectory removes only this checked, newly-created directory.
print(json.dumps({"release":prefix,"files":len(manifest["files"]),"sha256":expected,"verified":"checksum, manifest, safe Linux-compatible extraction"+(" and both Linux Docker builds" if args.build else "")},indent=2))
