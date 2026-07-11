import json
import re
import pandas as pd
from tableauscraper.TableauWorkbook import TableauWorkbook

def parse_bootstrap_body(filepath="output/bootstrap_info.json"):
    with open(filepath, "r", encoding="utf-8") as f:
        # The file contains a JSON object. Wait, the user opened output/bootstrap_info.json
        # Wait, the file bootstrap_info.json might be the raw text OR just the matched json!
        content = f.read()
        
    print(f"File size: {len(content)}")
    
    # Try to parse it as JSON directly
    try:
        data = json.loads(content)
        print("Parsed as JSON directly.")
        
        # Check if it has secondaryInfo -> presModelMap -> dataDictionary
        if "secondaryInfo" in data:
            pm_map = data["secondaryInfo"].get("presModelMap", {})
            data_dict = pm_map.get("dataDictionary", {})
            pm_holder = data_dict.get("presModelHolder", {})
            gen_data = pm_holder.get("genDataDictionaryPresModel", {})
            data_segments = gen_data.get("dataSegments", {})
            print(f"Found dataSegments keys: {list(data_segments.keys())}")
            
            # Use TableauScraper's parsing!
            # TableauScraper expects an instance of TableauScraper
            class DummyTS:
                def __init__(self):
                    self.dataSegments = data_segments
                    self.data = data
                    # Need info for parameter control
                    self.info = {}
                    self.logger = None
            
            ts = DummyTS()
            # Need to get info from somewhere. 
            
    except Exception as e:
        print(f"Error parsing JSON: {e}")

if __name__ == "__main__":
    parse_bootstrap_body()
