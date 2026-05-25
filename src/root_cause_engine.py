import json
import re
from difflib import SequenceMatcher
from pathlib import Path

_KNOWLEDGE_BASE_PATH = Path(__file__).parent / "root_cause_knowledge.json"


def _normalize(s):
    """Remove punctuation and whitespace for better matching."""
    return re.sub(r"[／/()（）\s]", "", s)


def _load_knowledge_base():
    with open(_KNOWLEDGE_BASE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _defect_matches(query, candidate, threshold=0.4):
    """Check if a query string matches a knowledge base defect name."""
    q = _normalize(query)
    c = _normalize(candidate)
    if q == c:
        return True
    if q in c or c in q:
        return True
    match = SequenceMatcher(None, q, c).find_longest_match(0, len(q), 0, len(c))
    if match.size < 2:
        return False
    return SequenceMatcher(None, q, c).ratio() >= threshold


def _match_ratio(query, candidate):
    """Return similarity ratio for a query-candidate pair."""
    q = _normalize(query)
    c = _normalize(candidate)
    if q == c:
        return 1.0
    if q in c or c in q:
        return 0.9
    return SequenceMatcher(None, q, c).ratio()


def get_all_process_types():
    """Return all process types available in the knowledge base."""
    kb = _load_knowledge_base()
    return list(kb.keys())


def get_defect_types_for_process(process_type):
    """Return defect types for a given process type."""
    kb = _load_knowledge_base()
    process_data = kb.get(process_type, {})
    return list(process_data.keys())


def get_root_causes(process_type, defect_type):
    """Return root cause list for a given process and defect type.
    Each item: {根因: str, 概率: int}
    Returns empty list if no match found.
    """
    kb = _load_knowledge_base()
    process_data = kb.get(process_type, {})
    return process_data.get(defect_type, [])


def find_defect_root_causes(defect_type, process_hint=None):
    """Find root causes for a defect type across all or a hinted process.

    Collects all fuzzy matches across processes, then returns the best one.
    Returns (process_type, root_causes_list) or (None, []).
    """
    kb = _load_knowledge_base()
    candidates = []

    processes_ordered = []
    if process_hint and process_hint in kb:
        processes_ordered.append(process_hint)
    if process_hint:
        for proc_name in kb:
            if proc_name not in processes_ordered and (
                process_hint in proc_name or proc_name in process_hint
            ):
                processes_ordered.append(proc_name)
    for proc_name in kb:
        if proc_name not in processes_ordered:
            processes_ordered.append(proc_name)

    for proc_name in processes_ordered:
        for kb_defect, causes in kb[proc_name].items():
            if _defect_matches(defect_type, kb_defect):
                ratio = _match_ratio(defect_type, kb_defect)
                candidates.append((ratio, proc_name, causes))

    if not candidates:
        return None, []

    candidates.sort(key=lambda x: x[0], reverse=True)
    _, best_proc, best_causes = candidates[0]
    return best_proc, best_causes


def search_defect_in_knowledge(defect_type):
    """Search all processes for a defect type (fuzzy match).
    Returns list of (process_type, defect_type, root_causes).
    """
    kb = _load_knowledge_base()
    results = []

    for proc_name, proc_data in kb.items():
        for kb_defect, root_causes in proc_data.items():
            if _defect_matches(defect_type, kb_defect):
                results.append((proc_name, kb_defect, root_causes))

    return results


def probability_to_level(prob):
    """Convert a probability value (0-100) to a qualitative severity level.

    Level 5 = most common (highest probability), Level 1 = rarest.
    Returns (level_label, severity_grade, color) tuple.
    """
    if prob >= 25:
        return "最高发", 5, "#8B0000"
    elif prob >= 20:
        return "高发", 4, "#DC143C"
    elif prob >= 15:
        return "常见", 3, "#FF8C00"
    elif prob >= 10:
        return "偶发", 2, "#DAA520"
    else:
        return "少见", 1, "#808080"


def add_custom_root_cause(process_type, defect_type, root_cause, probability):
    """Add or update a custom root cause entry. Saves to knowledge base file.

    If the process or defect type doesn't exist, it will be created.
    If the root cause already exists, its probability will be updated.
    """
    kb = _load_knowledge_base()

    if process_type not in kb:
        kb[process_type] = {}

    if defect_type not in kb[process_type]:
        kb[process_type][defect_type] = []

    causes = kb[process_type][defect_type]

    for item in causes:
        if item["根因"] == root_cause:
            item["概率"] = probability
            break
    else:
        causes.append({"根因": root_cause, "概率": probability})

    causes.sort(key=lambda x: x["概率"], reverse=True)

    with open(_KNOWLEDGE_BASE_PATH, "w", encoding="utf-8") as f:
        json.dump(kb, f, ensure_ascii=False, indent=2)

    return causes
