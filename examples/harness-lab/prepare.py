"""Create a tiny local asset; refuse to overwrite an existing file."""
import json
from pathlib import Path

with Path("ready.json").open("x", encoding="utf-8") as handle:
    json.dump({"values": [1, 2, 3]}, handle)
print("prepared: ready.json")
