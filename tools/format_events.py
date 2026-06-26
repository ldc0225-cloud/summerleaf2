"""events.json: ZOOM canonical + steps one-line format."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from field_runtime import parse_zoom_step, _canonical_zoom_json  # noqa: E402

IND = "    "


def compact(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(", ", ": "))


def fmt_dict(d, depth=0):
    if not d:
        return "{}"
    parts = []
    keys = list(d.keys())
    for i, k in enumerate(keys):
        v = d[k]
        key = json.dumps(k, ensure_ascii=False)
        comma = "," if i < len(keys) - 1 else ""
        if k == "steps" and isinstance(v, list):
            if not v:
                parts.append(IND * (depth + 1) + '"steps": []' + comma)
            else:
                sl = [
                    IND * (depth + 2) + compact(s) + ("," if j < len(v) - 1 else "")
                    for j, s in enumerate(v)
                ]
                parts.append(
                    IND * (depth + 1) + '"steps": [\n' + "\n".join(sl) + "\n" + IND * (depth + 1) + "]" + comma
                )
        elif isinstance(v, dict):
            parts.append(IND * (depth + 1) + key + ": " + fmt_dict(v, depth + 1) + comma)
        elif isinstance(v, list):
            if not v:
                parts.append(IND * (depth + 1) + key + ": []" + comma)
            elif all(isinstance(x, (str, int, float, bool)) or x is None for x in v):
                parts.append(IND * (depth + 1) + key + ": " + compact(v) + comma)
            elif all(isinstance(x, list) for x in v):
                parts.append(IND * (depth + 1) + key + ": " + compact(v) + comma)
            else:
                parts.append(IND * (depth + 1) + key + ": " + compact(v) + comma)
        else:
            parts.append(IND * (depth + 1) + key + ": " + json.dumps(v, ensure_ascii=False) + comma)
    return "{\n" + "\n".join(parts) + "\n" + IND * depth + "}"


def main():
    path = ROOT / "events.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    for cat in data.values():
        if not isinstance(cat, dict):
            continue
        for entry in cat.values():
            if not isinstance(entry, dict):
                continue
            steps = entry.get("steps")
            if not isinstance(steps, list):
                continue
            for i, s in enumerate(steps):
                if not isinstance(s, dict) or (s.get("type") or "").upper() != "ZOOM":
                    continue
                steps[i] = _canonical_zoom_json(parse_zoom_step(s))
    path.write_text(fmt_dict(data, 0) + "\n", encoding="utf-8")
    print("formatted", path)


if __name__ == "__main__":
    main()
