#!/usr/bin/env python3
"""
3GPP RAN RAG V3 - Hybrid Search with BM25 + Vector + Hierarchy Context
Multi-Release Support (Rel-19, Rel-20, etc.)

Usage:
    python search.py "query" [--spec SPEC] [--release Rel-19] [--top N]
                         [--mode hybrid|vector|bm25] [--context yes|no] [--json]
"""

import sys
import json
import re
import math
import argparse
from pathlib import Path
from datetime import datetime
from collections import Counter
from typing import Dict, List, Optional, Tuple

# 导入配置加载器
try:
    from config_loader import load_config, get_path, get_db_path, ConfigError
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent))
    from config_loader import load_config, get_path, get_db_path, ConfigError

# 延迟加载配置
_rag_config = None

def get_rag_config():
    """获取 RAG 配置（单例模式）"""
    global _rag_config
    if _rag_config is None:
        _rag_config = load_config()
    return _rag_config

def WORK_DIR() -> Path:
    """获取工作目录"""
    return get_path(get_rag_config(), "work_dir")

def LOG_DIR() -> Path:
    """获取日志目录"""
    return get_path(get_rag_config(), "log_dir")

def LOG_FILE() -> Path:
    """获取日志文件路径"""
    return LOG_DIR() / "rag_v3_search.log"

def DB_CONFIG_FILE() -> Path:
    """获取数据库配置文件路径"""
    return WORK_DIR() / "db_config.json"

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    log_path = LOG_FILE()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ============== Database Configuration ==============

def load_db_config() -> dict:
    """Load database configuration."""
    cfg_file = DB_CONFIG_FILE()
    if cfg_file.exists():
        with open(cfg_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "default_release": "Rel-19",
        "databases": {
            "Rel-19": {"path": "chroma_db/rel19", "collection": "3gpp_complete"}
        }
    }

def get_local_db_path(release: str) -> Path:
    """Get database path for a release."""
    config = load_db_config()
    db_info = config.get("databases", {}).get(release, {})
    relative_path = db_info.get("path", f"chroma_db/{release.lower()}")
    return WORK_DIR() / relative_path


# ============================================================
# BM25 Index (built on-the-fly from database)
# ============================================================

class BM25Index:
    """In-memory BM25 index over ChromaDB documents."""

    def __init__(self):
        self.docs = []        # list of {id, text, spec, version, clause, title, level}
        self.doc_ids = []
        self.tokenized = []   # tokenized corpus
        self.bm25 = None
        self._built = False

    def build(self, documents):
        """Build BM25 index from ChromaDB query results.
        documents: from collection.get(include=['documents','metadatas'])
        """
        from rank_bm25 import BM25Okapi

        self.docs = []
        self.doc_ids = []
        self.tokenized = []

        for i, doc_id in enumerate(documents['ids']):
            text = documents['documents'][i] if documents['documents'] else ""
            meta = documents['metadatas'][i] if documents['metadatas'] else {}
            entry = {
                "id": doc_id,
                "text": text,
                "spec": meta.get("spec", ""),
                "release": meta.get("release", ""),
                "clause": meta.get("clause", ""),
                "title": meta.get("title", ""),
                "level": meta.get("level", 1),
            }
            self.docs.append(entry)
            self.doc_ids.append(doc_id)
            self.tokenized.append(self._tokenize(text + " " + meta.get("title", "")))

        self.bm25 = BM25Okapi(self.tokenized)
        self._built = True
        return len(self.docs)

    def search(self, query, top_k=20, spec_filter=None, version_filter=None):
        """Return list of (doc_entry, score) sorted by BM25 score descending."""
        if not self._built:
            return []

        tokens = self._tokenize(query)
        scores = self.bm25.get_scores(tokens)

        # Build index->entry mapping
        results = []
        for idx, score in enumerate(scores):
            if score <= 0:
                continue
            entry = self.docs[idx]
            # Apply filters
            if spec_filter and entry["spec"] != spec_filter:
                continue
            if version_filter and entry.get("release", "") != version_filter:
                continue
            results.append((entry, float(score)))

        # Sort by score descending
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]

    @staticmethod
    def _tokenize(text):
        """Simple tokenization: lowercase, split on non-alphanumeric, keep numbers."""
        text = text.lower()
        # Keep clause numbers like 5.1.3 as tokens
        tokens = re.findall(r'\d+(?:\.\d+)+|[a-z][a-z0-9_-]*', text)
        return tokens


# ============================================================
# Vector Search (ChromaDB)
# ============================================================

def vector_search(query, collection, top_k=20, where_filter=None):
    """Return list of (doc_entry, distance) from ChromaDB."""
    results = collection.query(
        query_texts=[query],
        n_results=top_k,
        where=where_filter
    )

    entries = []
    for i in range(len(results['ids'][0])):
        meta = results['metadatas'][0][i]
        entry = {
            "id": results['ids'][0][i],
            "text": results['documents'][0][i],
            "spec": meta.get("spec", ""),
            "version": meta.get("version", ""),
            "clause": meta.get("clause", ""),
            "title": meta.get("title", ""),
            "level": meta.get("level", 1),
        }
        distance = results['distances'][0][i]
        entries.append((entry, float(distance)))

    return entries


# ============================================================
# RRF Fusion
# ============================================================

def rrf_fuse(vector_results, bm25_results, k=60):
    """Reciprocal Rank Fusion of two ranked lists.
    vector_results: [(entry, distance)] - lower distance = better
    bm25_results: [(entry, score)] - higher score = better
    Returns: [(entry, fused_score)] sorted by fused_score descending
    """
    scores = {}

    # Vector: rank by distance ascending (lower = better)
    sorted_vec = sorted(vector_results, key=lambda x: x[1])
    for rank, (entry, dist) in enumerate(sorted_vec, 1):
        doc_id = entry["id"]
        scores[doc_id] = scores.get(doc_id, 0) + 1.0 / (k + rank)

    # BM25: rank by score descending (higher = better)
    sorted_bm25 = sorted(bm25_results, key=lambda x: x[1], reverse=True)
    for rank, (entry, score) in enumerate(sorted_bm25, 1):
        doc_id = entry["id"]
        scores[doc_id] = scores.get(doc_id, 0) + 1.0 / (k + rank)

    # Build entry lookup
    entry_map = {}
    for entry, _ in vector_results:
        entry_map[entry["id"]] = entry
    for entry, _ in bm25_results:
        entry_map[entry["id"]] = entry

    # Sort by fused score descending
    fused = [(entry_map[doc_id], score) for doc_id, score in scores.items()]
    fused.sort(key=lambda x: x[1], reverse=True)

    # Add source rank info
    vec_id_rank = {entry["id"]: rank for rank, (entry, _) in enumerate(sorted_vec, 1)}
    bm25_id_rank = {entry["id"]: rank for rank, (entry, _) in enumerate(sorted_bm25, 1)}

    result = []
    for entry, score in fused:
        vr = vec_id_rank.get(entry["id"], None)
        br = bm25_id_rank.get(entry["id"], None)
        result.append((entry, score, vr, br))

    return result


# ============================================================
# Hierarchy Context
# ============================================================

def get_parent_clause_number(clause):
    """Get parent clause number. E.g. 5.1.3 -> 5.1, 5.1 -> 5, 5 -> None"""
    parts = clause.split('.')
    if len(parts) <= 1:
        return None
    return '.'.join(parts[:-1])


def build_hierarchy_path(clause, title_lookup, spec):
    """Build full hierarchy path for a clause within the same spec.
    E.g. 5.1.3 -> "5 | 5.1 Random Access procedure | 5.1.3 ..."
    """
    path_parts = []
    current = clause
    visited = set()
    while current and current not in visited:
        visited.add(current)
        info = title_lookup.get((spec, current))
        if info:
            label = f"{current} {info['title']}" if info['title'] else current
        else:
            label = current
        path_parts.insert(0, label)
        current = get_parent_clause_number(current)
        # Max 5 levels up
        if len(path_parts) >= 5:
            break
    return " > ".join(path_parts) if path_parts else clause


def get_child_clauses(clause, title_lookup, spec):
    """Get direct child clauses of a given clause within the same spec."""
    prefix = clause + "."
    children = []
    for (s, c), info in title_lookup.items():
        if s != spec:
            continue
        if c.startswith(prefix) and c.count('.') == clause.count('.') + 1:
            children.append(f"{c} {info['title']}" if info['title'] else c)
    return children[:5]  # Max 5 children


# ============================================================
# Main Search
# ============================================================

def search(query, spec_filter=None, version_filter=None, release=None, top_n=5,
           mode="hybrid", show_context=False):
    """Main search function with hybrid retrieval support.

    Args:
        query: Search query string
        spec_filter: Filter by spec number (e.g., "38.321")
        version_filter: Filter by version (e.g., "Rel-19")
        release: Release version for database selection (e.g., "Rel-19")
        top_n: Number of results to return
        mode: "hybrid" (BM25+vector), "vector" (vector only), "bm25" (BM25 only)
        show_context: Whether to include hierarchy context

    Returns:
        dict with search results
    """
    import chromadb
    from chromadb.utils import embedding_functions

    ef = embedding_functions.DefaultEmbeddingFunction()
    
    # Determine database path based on release
    config = load_config()
    if release is None:
        release = config.get("default_release", "Rel-19")
    
    # Use data/chroma_db/{release_lower} path (consistent with README design)
    work_dir = get_path(config, "work_dir")
    DB_DIR = work_dir / "data" / "chroma_db" / release.lower().replace("-", "")
    
    # Use consistent collection name
    collection_name = "3gpp_complete"

    try:
        client = chromadb.PersistentClient(path=str(DB_DIR))
        collection = client.get_collection(name=collection_name, embedding_function=ef)
    except Exception as e:
        return {"status": "error", "message": f"Database not found for {release}: {e}"}

    # Build where filter
    where_filter = None
    conditions = []
    if spec_filter:
        conditions.append({"spec": spec_filter})
    if version_filter:
        conditions.append({"release": version_filter})  # Use 'release' not 'version'
    if len(conditions) > 1:
        where_filter = {"$and": conditions}
    elif len(conditions) == 1:
        where_filter = conditions[0]

    # Fetch all docs for BM25 index (apply same filters)
    # For BM25 we need all docs, but we filter at search time
    all_docs = collection.get(include=["documents", "metadatas"])

    # Build BM25 index
    bm25_index = BM25Index()
    bm25_count = bm25_index.build(all_docs)

    # Run searches
    if mode == "vector":
        vec_results = vector_search(query, collection, top_k=top_n * 3, where_filter=where_filter)
        final_results = [(entry, 1.0 / (60 + i + 1), i + 1, None) for i, (entry, _) in enumerate(vec_results[:top_n])]
    elif mode == "bm25":
        bm25_results = bm25_index.search(query, top_k=top_n * 3, spec_filter=spec_filter, version_filter=version_filter)
        final_results = [(entry, 1.0 / (60 + i + 1), None, i + 1) for i, (entry, _) in enumerate(bm25_results[:top_n])]
    else:  # hybrid
        vec_results = vector_search(query, collection, top_k=top_n * 3, where_filter=where_filter)
        bm25_results = bm25_index.search(query, top_k=top_n * 3, spec_filter=spec_filter, version_filter=version_filter)
        final_results = rrf_fuse(vec_results, bm25_results)[:top_n]

    # Build hierarchy context if requested
    hierarchy = None
    if show_context and final_results:
        # Build title lookup from all docs, keyed by (spec, clause)
        title_lookup = {}
        for meta in all_docs['metadatas']:
            cid = meta.get('clause', '')
            spec = meta.get('spec', '')
            if cid and spec:
                title_lookup[(spec, cid)] = {
                    'title': meta.get('title', ''),
                    'spec': spec,
                }

        hierarchy = {}
        for entry, score, vec_rank, bm25_rank in final_results:
            cid = entry['clause']
            spec = entry['spec']
            path = build_hierarchy_path(cid, title_lookup, spec)
            children = get_child_clauses(cid, title_lookup, spec)
            hierarchy[cid] = {"path": path, "children": children}

    # Format results
    formatted = []
    for entry, score, vec_rank, bm25_rank in final_results:
        result = {
            "spec": entry['spec'],
            "version": entry.get('release', ''),
            "clause": entry['clause'],
            "title": entry['title'],
            "level": entry['level'],
            "score": round(score, 6),
            "content": entry['text'],
        }
        # Add rank info
        ranks = []
        if vec_rank is not None:
            ranks.append(f"vec#{vec_rank}")
        if bm25_rank is not None:
            ranks.append(f"bm25#{bm25_rank}")
        result["ranks"] = " + ".join(ranks) if ranks else ""

        # Add hierarchy context
        if hierarchy and entry['clause'] in hierarchy:
            h = hierarchy[entry['clause']]
            result["hierarchy_path"] = h['path']
            if h['children']:
                result["children"] = h['children']

        formatted.append(result)

    # Log
    log(f"query={query[:50]} mode={mode} spec={spec_filter} version={version_filter} "
        f"results={len(formatted)} bm25_docs={bm25_count}")

    return {
        "status": "ok",
        "query": query,
        "mode": mode,
        "spec_filter": spec_filter,
        "version_filter": version_filter,
        "context": show_context,
        "total": len(formatted),
        "results": formatted,
    }


# ============================================================
# Output Formatting
# ============================================================

def format_output(result):
    if result.get("status") != "ok":
        return f"[ERROR] {result.get('message', 'Unknown error')}"

    query = result["query"]
    results = result["results"]
    total = result["total"]
    mode = result.get("mode", "hybrid")

    output = []
    output.append("")
    output.append(f"[Query] {query}")
    output.append(f"[Mode] {mode}")
    if result.get("spec_filter"):
        output.append(f"[Spec Filter] {result['spec_filter']}")
    if result.get("version_filter"):
        output.append(f"[Version Filter] {result['version_filter']}")
    output.append(f"[Results] {total} items\n")
    output.append("=" * 80)

    for i, r in enumerate(results, 1):
        output.append("")
        ranks_str = f"  [{r['ranks']}]" if r.get('ranks') else ""
        output.append(f"[{i}] {r['spec']} {r['clause']} (v{r['version']}){ranks_str}")

        # Hierarchy path
        if r.get("hierarchy_path"):
            output.append(f"    Path: {r['hierarchy_path']}")

        output.append(f"    Title: {r['title']}")
        output.append("")
        output.append("    Content:")

        content = r['content']
        lines = content.split('\n')
        content_lines = [l.strip() for l in lines if l.strip()]

        for line in content_lines[:8]:
            output.append(f"       {line}")

        if len(content_lines) > 8:
            output.append(f"       ... ({len(content_lines)} lines)")

        # Children
        if r.get("children"):
            output.append(f"    Sub-clauses: {', '.join(r['children'][:3])}")

        output.append("-" * 80)

    return "\n".join(output)


# ============================================================
# CLI Entry
# ============================================================

def main():
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="3GPP RAN RAG Search V3 (Hybrid, Multi-Release)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python search.py "MAC CE for BSR"
    python search.py "RRC connection" --release Rel-19
    python search.py "carrier aggregation" --release Rel-19,Rel-20
    python search.py "measurement" --spec 38.133
        """
    )
    parser.add_argument("query", help="Search query")
    parser.add_argument("--spec", help="Filter by spec number (e.g., 38.321)")
    parser.add_argument("--release", default=None, 
                        help="Filter by release (e.g., Rel-19 or Rel-19,Rel-20)")
    parser.add_argument("--top", type=int, default=5, help="Number of results (default: 5)")
    parser.add_argument("--mode", choices=["hybrid", "vector", "bm25"], default="hybrid",
                        help="Search mode (default: hybrid)")
    parser.add_argument("--context", choices=["yes", "no"], default="yes",
                        help="Show hierarchy context (default: yes)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    
    # Enhanced features
    parser.add_argument("--cluster", action="store_true", 
                        help="Cluster results by topic (D1)")
    parser.add_argument("--recommend", action="store_true",
                        help="Show related clause recommendations (D2)")
    parser.add_argument("--history", action="store_true",
                        help="Show search history")

    args = parser.parse_args()
    
    # Handle history
    if args.history:
        print("\n=== Search History ===")
        if LOG_FILE.exists():
            lines = open(LOG_FILE, "r", encoding="utf-8").readlines()[-20:]
            for line in lines:
                print(f"  {line.strip()}")
        else:
            print("  No history available")
        return

    # Determine releases to search
    config = load_config()
    if args.release:
        releases = [r.strip() for r in args.release.split(",")]
    else:
        releases = [config.get("default_release", "Rel-19")]

    # Search across releases
    all_results = {"results": [], "query": args.query, "status": "ok", "mode": args.mode}
    
    for release in releases:
        result = search(
            args.query,
            spec_filter=args.spec,
            version_filter=release,
            release=release,
            top_n=args.top,
            mode=args.mode,
            show_context=(args.context == "yes"),
        )
        
        if result.get("status") == "ok":
            for r in result["results"]:
                r["release"] = release
            all_results["results"].extend(result["results"])
        else:
            print(f"[DEBUG] Search failed for {release}: {result.get('message')}", file=sys.stderr)
    
    # Sort by score
    all_results["results"].sort(key=lambda x: x.get("score", 0), reverse=True)
    all_results["results"] = all_results["results"][:args.top]
    all_results["total"] = len(all_results["results"])
    all_results["mode"] = args.mode
    
    # Cluster results if requested (D1)
    if args.cluster and all_results["results"]:
        all_results["clustered"] = cluster_results(all_results["results"])
    
    # Add recommendations if requested (D2)
    if args.recommend and all_results["results"]:
        all_results["recommendations"] = get_recommendations(all_results["results"])

    if args.json:
        print(json.dumps(all_results, indent=2, ensure_ascii=False))
    else:
        print(format_output(all_results))


def cluster_results(results: List[dict]) -> Dict[str, List[dict]]:
    """Cluster results by spec (simple clustering)."""
    clusters = defaultdict(list)
    for r in results:
        clusters[r.get("spec", "unknown")].append(r)
    return dict(clusters)


def get_recommendations(results: List[dict]) -> List[dict]:
    """Get related clause recommendations based on hierarchy."""
    recommendations = []
    seen_clauses = set()
    
    for r in results[:3]:  # Top 3 results
        spec = r.get("spec")
        clause = r.get("clause", "")
        
        # Suggest parent clause
        if "." in clause:
            parent = ".".join(clause.split(".")[:-1])
            parent_key = f"{spec}_{parent}"
            if parent_key not in seen_clauses:
                recommendations.append({
                    "spec": spec,
                    "clause": parent,
                    "reason": "Parent clause"
                })
                seen_clauses.add(parent_key)
    
    return recommendations[:5]


if __name__ == "__main__":
    main()
