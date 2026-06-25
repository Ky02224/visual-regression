import os
import json
import yaml
from urllib.parse import urlparse

def get_website_root(url):
    if not url or not isinstance(url, str):
        return "http://unknown_website"
    try:
        parsed = urlparse(url)
        if parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
    except Exception:
        pass
    if "://" in url:
        parts = url.split("/")
        return "/".join(parts[:3])
    return url

def main():
    # Use the default path .visual-regression/baselines
    baselines_dir = os.path.join(".visual-regression", "baselines")
    if not os.path.exists(baselines_dir):
        # Fallback to local baselines folder
        baselines_dir = "baselines"

    if not os.path.exists(baselines_dir):
        print(f"Error: Baselines directory '{baselines_dir}' not found.")
        print("Please ensure the dashboard server has been started and baseline captures have run.")
        return

    print(f"Reading baselines from directory: {baselines_dir}")
    
    # Scan baselines directory for metadata.json files
    rows = []
    for folder_name in sorted(os.listdir(baselines_dir)):
        folder_path = os.path.join(baselines_dir, folder_name)
        if not os.path.isdir(folder_path):
            continue
        
        metadata_path = os.path.join(folder_path, "metadata.json")
        image_path = os.path.join(folder_path, "baseline.png")
        if not os.path.exists(metadata_path) or not os.path.exists(image_path):
            continue
            
        try:
            with open(metadata_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            # The 'capture' key has the detailed config
            capture = data.get("capture", {})
            name = data.get("name", folder_name)
            url = capture.get("url")
            browser = capture.get("browser", "chromium")
            device = capture.get("device")
            locale = capture.get("locale")
            timezone_id = capture.get("timezone_id")
            viewport = capture.get("viewport", [1440, 900])
            ignore_regions = data.get("ignore_regions", [])
            
            rows.append({
                "name": name,
                "url": url,
                "browser": browser,
                "device": device,
                "locale": locale,
                "timezone_id": timezone_id,
                "viewport": viewport,
                "ignore_regions": ignore_regions
            })
        except Exception as e:
            print(f"Warning: Failed to read baseline folder '{folder_name}': {e}")

    if not rows:
        print("No baselines found in the directory. Please capture some baselines first!")
        return

    # Group baselines by their website root URL
    website_groups = {}
    for row in rows:
        url = row["url"]
        root = get_website_root(url)
        if root not in website_groups:
            website_groups[root] = []
        website_groups[root].append(row)

    roots = list(website_groups.keys())

    print("\n=== LENS YAML SUITE GENERATOR ===")
    print("Detected the following websites in your database baselines:")
    for idx, root in enumerate(roots, 1):
        count = len(website_groups[root])
        print(f"  [{idx}] {root} ({count} pages)")
    print(f"  [{len(roots) + 1}] Export ALL websites together")
    
    # Prompt the user for choice
    choice_str = input(f"\nSelect which website to export (1-{len(roots) + 1}): ").strip()
    try:
        choice = int(choice_str)
        if choice < 1 or choice > len(roots) + 1:
            raise ValueError()
    except ValueError:
        print("Invalid selection. Exiting.")
        return

    # Filter rows based on choice
    selected_rows = []
    if choice <= len(roots):
        selected_root = roots[choice - 1]
        selected_rows = website_groups[selected_root]
        # Create a clean filename from the domain
        domain = urlparse(selected_root).netloc.replace(":", "_").replace(".", "_")
        output_file = f"suite.{domain}.yaml"
        print(f"\nExporting baselines for site: {selected_root}")
    else:
        selected_rows = rows
        output_file = "suite.exported_all.yaml"
        print("\nExporting all baselines...")

    tests = []
    for r in selected_rows:
        test_case = {
            "name": r["name"],
            "url": r["url"] or "http://unknown_website",
            "browser": r["browser"] or "chromium",
            "viewport": r["viewport"] or [1440, 900],
            "wait_ms": 400,
            "threshold_pct": 0.25,
            "pixel_threshold": 20,
            "min_region_area": 120,
            "locale": r["locale"] or "en-US",
            "timezone_id": r["timezone_id"] or "Asia/Kuala_Lumpur",
            "ignore_regions": r["ignore_regions"] or []
        }
        if r["device"]:
            test_case["device"] = r["device"]
            
        tests.append(test_case)

    suite_data = {
        "defaults": {
            "comparison_mode": "ai"
        },
        "tests": tests
    }

    with open(output_file, "w", encoding="utf-8") as f:
        yaml.dump(suite_data, f, default_flow_style=False, sort_keys=False)
    
    print(f"Success! Exported {len(tests)} cases to '{output_file}'.\n")

if __name__ == "__main__":
    main()
