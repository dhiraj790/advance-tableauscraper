"""Dig into the worldUpdate key and other info structures to find the actual data."""
import json
import re
import sys
sys.stdout.reconfigure(encoding='utf-8')

from pathlib import Path

OUTPUT = Path("output")

# Load the saved bootstrap data
with open(OUTPUT / "bootstrap_info.json", "r", encoding="utf-8") as f:
    info = json.load(f)

with open(OUTPUT / "bootstrap_data.json", "r", encoding="utf-8") as f:
    data = json.load(f)


def describe(obj, prefix="", depth=0, max_depth=4):
    """Recursively describe JSON structure."""
    if depth > max_depth:
        print(f"{prefix}... (max depth)")
        return
    if isinstance(obj, dict):
        for key in list(obj.keys())[:10]:
            val = obj[key]
            if isinstance(val, dict):
                print(f"{prefix}{key}: dict ({len(val)} keys)")
                describe(val, prefix + "  ", depth + 1, max_depth)
            elif isinstance(val, list):
                print(f"{prefix}{key}: list ({len(val)} items)")
                if val and depth < max_depth:
                    describe(val[0], prefix + "  [0] ", depth + 1, max_depth)
            elif isinstance(val, str) and len(val) > 100:
                print(f"{prefix}{key}: str ({len(val)} chars) = {val[:80]}...")
            else:
                print(f"{prefix}{key}: {type(val).__name__} = {val}")
        if len(obj) > 10:
            print(f"{prefix}... and {len(obj) - 10} more keys")
    elif isinstance(obj, list):
        print(f"{prefix}list ({len(obj)} items)")
        if obj:
            describe(obj[0], prefix + "[0] ", depth + 1, max_depth)


print("=== info structure ===")
describe(info)

# Specifically look at worldUpdate
print("\n\n=== worldUpdate structure ===")
world_update = info.get("worldUpdate", {})
describe(world_update, max_depth=5)

# Look for dataDictionary in worldUpdate
print("\n\n=== Looking for dataDictionary ===")
def find_key(obj, target, path=""):
    """Find all occurrences of a key in nested dict."""
    results = []
    if isinstance(obj, dict):
        for key, val in obj.items():
            if key == target:
                results.append((path + "." + key, type(val).__name__, 
                              len(val) if isinstance(val, (dict, list)) else str(val)[:50]))
            if isinstance(val, (dict, list)):
                results.extend(find_key(val, target, path + "." + key))
    elif isinstance(obj, list):
        for i, item in enumerate(obj[:5]):  # limit to first 5
            results.extend(find_key(item, target, path + f"[{i}]"))
    return results

for target_key in ["dataDictionary", "dataSegments", "dataValues", "dataColumns", 
                    "presModelHolder", "vizDataModel", "vizData", "paneColumns",
                    "dataDictionaryPresModel", "columns", "columnsData"]:
    results = find_key(info, target_key)
    if results:
        print(f"\n  '{target_key}' found at:")
        for path, type_name, size in results:
            print(f"    {path}: {type_name} ({size})")

# Also look in the data dict
results2 = find_key(data, "dataDictionary")
if results2:
    print(f"\n  'dataDictionary' in data:")
    for path, type_name, size in results2:
        print(f"    {path}: {type_name} ({size})")

# Look for the actual data values
print("\n\n=== Looking for dataValues ===")
for target in ["dataValues", "tupleIds"]:
    results = find_key(info, target)
    if results:
        print(f"\n  '{target}' found at {len(results)} locations:")
        for path, type_name, size in results[:5]:
            print(f"    {path}: {type_name} ({size})")

# Try to find where the worksheet data is
print("\n\n=== Worksheet data in worldUpdate ===")
wu = info.get("worldUpdate", {})
if "applicationPresModel" in wu:
    apm = wu["applicationPresModel"]
    print(f"applicationPresModel keys: {list(apm.keys())[:15]}")
    
    if "workbookPresModel" in apm:
        wpm = apm["workbookPresModel"]
        print(f"\nworkbookPresModel keys: {list(wpm.keys())[:15]}")
        
        if "sheetsInfo" in wpm:
            si = wpm["sheetsInfo"]
            print(f"\nsheetsInfo ({len(si)} sheets):")
            for sheet_name, sheet_info in si.items():
                print(f"  {sheet_name}: {list(sheet_info.keys())[:10]}")

    if "dataDictionary" in apm:
        dd = apm["dataDictionary"]
        print(f"\ndataDictionary keys: {list(dd.keys())[:10]}")
        if "dataSegments" in dd:
            segs = dd["dataSegments"]
            print(f"dataSegments: {len(segs)} segments")
            for seg_name in list(segs.keys())[:3]:
                seg = segs[seg_name]
                print(f"\n  Segment '{seg_name}':")
                if isinstance(seg, dict):
                    for col_name in list(seg.keys())[:5]:
                        col = seg[col_name]
                        if isinstance(col, dict):
                            dt = col.get("dataType", "?")
                            vals = col.get("dataValues", [])
                            print(f"    {col_name}: type={dt}, values={len(vals)}")
                            if vals:
                                print(f"      sample: {vals[:3]}")
