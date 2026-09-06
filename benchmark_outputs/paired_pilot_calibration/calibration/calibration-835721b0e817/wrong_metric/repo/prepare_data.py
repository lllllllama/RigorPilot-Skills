"""Create the documented local data; no network or third-party packages."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
directory = ROOT / "data"
if directory.is_symlink():
    raise RuntimeError("Refusing linked data directory")
directory.mkdir(exist_ok=True)
path = directory / "samples.csv"
expected = b"x,y\n0,1\n1,3\n2,5\n"
if path.is_symlink():
    raise RuntimeError("Refusing linked dataset")
if path.exists():
    if path.read_bytes() != expected:
        raise RuntimeError("Existing dataset does not match; refusing overwrite")
else:
    with path.open("xb") as stream:
        stream.write(expected)
print("Prepared data/samples.csv from fixed local values")
