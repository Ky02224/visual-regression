import logging
from typing import List, Dict, Any
from .review_manager import ReviewManager

logger = logging.getLogger(__name__)

def get_auto_ignore_suggestions(store, paths, baseline_name: str, current_run_id: str, limit: int = 5) -> List[Dict[str, Any]]:
    # Query database for last failed runs of this baseline.
    is_pg = hasattr(store, "pool")
    query = (
        """
        SELECT run_id FROM runs_index
        WHERE baseline_name = %s AND run_id != %s AND status = 'FAIL'
        ORDER BY created_at DESC LIMIT %s;
        """
        if is_pg
        else """
        SELECT run_id FROM runs_index
        WHERE baseline_name = ? AND run_id != ? AND status = 'FAIL'
        ORDER BY created_at DESC LIMIT ?;
        """
    )
    try:
        rows = store._execute_query(query, (baseline_name, current_run_id, limit), fetch=True)
    except Exception as e:
        logger.warning("Failed to query runs for auto-ignore suggestions: %s", e)
        return []

    run_ids = [row["run_id"] for row in rows]
    if not run_ids:
        return []

    manager = ReviewManager(paths)
    all_regions: List[List[Dict[str, Any]]] = []

    for rid in run_ids:
        try:
            run_dir = manager.resolve_run_dir(rid)
            payload = manager.load_run_payload(run_dir)
            regions = payload.get("result", {}).get("regions", [])
            if regions:
                all_regions.append(regions)
        except Exception as e:
            logger.warning("Failed to load run payload for %s: %s", rid, e)
            continue
            
    if not all_regions:
        return []
        
    def get_iou(boxA, boxB):
        xA = max(boxA[0], boxB[0])
        yA = max(boxA[1], boxB[1])
        xB = min(boxA[0] + boxA[2], boxB[0] + boxB[2])
        yB = min(boxA[1] + boxA[3], boxB[1] + boxB[3])
        
        interArea = max(0, xB - xA) * max(0, yB - yA)
        boxAArea = boxA[2] * boxA[3]
        boxBArea = boxB[2] * boxB[3]
        
        unionArea = boxAArea + boxBArea - interArea
        if unionArea == 0:
            return 0.0
        return interArea / unionArea

    flat_regions = []
    for idx, run_list in enumerate(all_regions):
        for r in run_list:
            x = r.get("x")
            y = r.get("y")
            w = r.get("width") or r.get("w")
            h = r.get("height") or r.get("h")
            if x is not None and y is not None and w and h:
                flat_regions.append((idx, [x, y, w, h]))

    if not flat_regions:
        return []

    if len(flat_regions) > 1000:
        flat_regions = flat_regions[:1000]

    parent = list(range(len(flat_regions)))

    def find(i):
        path = []
        while parent[i] != i:
            path.append(i)
            i = parent[i]
        for node in path:
            parent[node] = i
        return i

    def union(i, j):
        root_i = find(i)
        root_j = find(j)
        if root_i != root_j:
            parent[root_i] = root_j

    for i in range(len(flat_regions)):
        run_idx_i, box_i = flat_regions[i]
        for j in range(i + 1, len(flat_regions)):
            run_idx_j, box_j = flat_regions[j]
            if run_idx_i != run_idx_j:
                if get_iou(box_i, box_j) > 0.4:
                    union(i, j)

    clusters_map = {}
    for i in range(len(flat_regions)):
        root = find(i)
        if root not in clusters_map:
            clusters_map[root] = []
        clusters_map[root].append(flat_regions[i])
    clusters = list(clusters_map.values())

    suggestions = []
    for cluster in clusters:
        distinct_runs = set(item[0] for item in cluster)
        if len(distinct_runs) >= 2:
            boxes = [item[1] for item in cluster]
            min_x = min(b[0] for b in boxes)
            min_y = min(b[1] for b in boxes)
            max_r = max(b[0] + b[2] for b in boxes)
            max_b = max(b[1] + b[3] for b in boxes)
            suggestions.append({
                "x": min_x,
                "y": min_y,
                "width": max_r - min_x,
                "height": max_b - min_y,
                "frequency": len(distinct_runs),
                "total_runs_analyzed": len(all_regions)
            })

    return suggestions
