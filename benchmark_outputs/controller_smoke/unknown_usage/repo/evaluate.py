"""Evaluate the fixed linear predictor; process success is not metric success."""
import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
dataset = ROOT / "data" / "samples.csv"
config_path = ROOT / "config.json"
config = json.loads(config_path.read_text(encoding="utf-8"))
with dataset.open(encoding="utf-8", newline="") as stream:
    rows = list(csv.DictReader(stream))
inputs = [float(row["x"]) for row in rows]
targets = [float(row["y"]) for row in rows]
predictions = [config["slope"] * value + config["bias"] for value in inputs]
mse = sum((actual - expected) ** 2 for actual, expected in zip(predictions, targets)) / len(targets)
output = ROOT / "results"
if output.is_symlink():
    raise RuntimeError("Refusing linked output directory")
output.mkdir(exist_ok=True)
artifacts = {
    "metrics.json": {"mse": mse, "sample_count": len(rows),
                     "data_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
                     "config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest()},
    "predictions.json": {"inputs": inputs, "targets": targets, "predictions": predictions},
}
for name, value in artifacts.items():
    path = output / name
    if path.is_symlink():
        raise RuntimeError("Refusing linked artifact")
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
print(f"mse={mse}")
