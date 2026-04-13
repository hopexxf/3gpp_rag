#!/usr/bin/env python3
"""
3GPP RAG - Unified Specification Management Tool
Version: 2.0.0

Features:
- Multi-Release support (Rel-19, Rel-20, etc.)
- Auto mode detection (normal/skip-large/chunked)
- Incremental update
- Batch operations
- Version comparison
- Data validation
- Statistics reporting

Usage:
    python manage_spec.py add 38.300 --release=Rel-19
    python manage_spec.py update 38.300 --release=Rel-19
    python manage_spec.py remove 38.300 --release=Rel-19
    python manage_spec.py list --release=Rel-19
    python manage_spec.py status
    python manage_spec.py diff 38.300 --from=Rel-19 --to=Rel-20
    python manage_spec.py batch-add --release=Rel-19
    python manage_spec.py report
"""

import sys
import os
import re
import json
import zipfile
import shutil
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from collections import Counter, defaultdict
import argparse

from docx import Document
import chromadb
from chromadb.config import Settings

# 导入配置加载器
try:
    from config_loader import load_config, get_path, get_db_path, get_embedding_model, ConfigError
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent))
    from config_loader import load_config, get_path, get_db_path, get_embedding_model, ConfigError

# ============== Configuration ==============

# 延迟加载配置（在首次使用时加载）
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

def PROTOCOL_BASE() -> Path:
    """获取协议根目录"""
    return get_path(get_rag_config(), "protocol_base")

def LOG_DIR() -> Path:
    """获取日志目录"""
    return get_path(get_rag_config(), "log_dir")

def DB_BASE_DIR() -> Path:
    """获取数据库根目录"""
    return WORK_DIR() / "chroma_db"

def DB_CONFIG_FILE() -> Path:
    """获取数据库配置文件路径"""
    return WORK_DIR() / "db_config.json"

# Auto mode detection thresholds
CHUNK_THRESHOLD_MB = 1.5      # ≤1.5MB: normal, >1.5MB: chunked
SKIP_LARGE_MAX_SIZE_MB = 1.5  # Same threshold for skip-large mode

# ============== Logging ==============

def get_log_file() -> Path:
    """Get log file path with date."""
    LOG_DIR().mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    return LOG_DIR() / f"manage_spec_{date_str}.log"

def log(msg: str, level: str = "INFO"):
    """Log message to file and console."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{level}] {msg}"
    print(line)
    with open(get_log_file(), "a", encoding="utf-8") as f:
        f.write(line + "\n")

# ============== Database Configuration ==============

def init_db_config():
    """Initialize database configuration."""
    cfg_file = DB_CONFIG_FILE()
    if not cfg_file.exists():
        config = {
            "version": "2.0.0",
            "databases": {},
            "default_release": "Rel-19",
            "current_databases": {
                "Rel-19": "chroma_db_rel19",
                "Rel-20": "chroma_db_rel20"
            }
        }
        save_db_config(config)
    return load_db_config()

def load_db_config() -> dict:
    """Load database configuration."""
    cfg_file = DB_CONFIG_FILE()
    if cfg_file.exists():
        with open(cfg_file, "r", encoding="utf-8") as f:
            config = json.load(f)
            # Ensure current_databases is populated from databases section
            if "current_databases" not in config and "databases" in config:
                config["current_databases"] = {
                    k: v["path"] for k, v in config["databases"].items()
                }
            return config
    return init_db_config()

def save_db_config(config: dict):
    """Save database configuration."""
    cfg_file = DB_CONFIG_FILE()
    cfg_file.parent.mkdir(parents=True, exist_ok=True)
    with open(cfg_file, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

# ============== Database Management ==============

class DatabaseManager:
    """Manage multiple ChromaDB databases."""
    
    def __init__(self):
        self.config = load_config()
        self.clients: Dict[str, chromadb.PersistentClient] = {}
        
    def get_client(self, release: str) -> chromadb.PersistentClient:
        """Get or create database client for a release."""
        if release not in self.clients:
            # Use data/chroma_db/{release_lower} path (consistent with README design)
            db_path = WORK_DIR() / "data" / "chroma_db" / release.lower().replace("-", "")
            db_path.mkdir(parents=True, exist_ok=True)
            self.clients[release] = chromadb.PersistentClient(
                path=str(db_path),
                settings=Settings(anonymized_telemetry=False)
            )
        return self.clients[release]
    
    def get_collection(self, release: str, create: bool = True) -> Optional[chromadb.Collection]:
        """Get collection for a release."""
        client = self.get_client(release)
        # Use consistent collection name across releases
        collection_name = "3gpp_complete"
        try:
            return client.get_collection(name=collection_name)
        except Exception as e:
            if create:
                return client.create_collection(name=collection_name)
            return None
    
    def list_releases(self) -> List[str]:
        """List available releases."""
        # First check config
        config_releases = list(self.config.get("current_databases", {}).keys())
        if config_releases:
            return config_releases
        
        # Fallback: scan data/chroma_db/ directory
        work_dir = WORK_DIR()
        db_dir = work_dir / "data" / "chroma_db"
        releases = []
        if db_dir.exists():
            for sub_dir in db_dir.iterdir():
                if sub_dir.is_dir():
                    releases.append(sub_dir.name)
        return releases

# ============== Document Parsing ==============

def parse_clause_number(text: str) -> Optional[str]:
    """Extract clause number from text."""
    match = re.match(r'^(\d+(?:\.\d+)*)\s+', text.strip())
    return match.group(1) if match else None

def parse_docx(docx_path: Path, spec_number: str, release: str) -> List[dict]:
    """Parse a docx file and return clauses."""
    file_stem = docx_path.stem
    doc = Document(str(docx_path))
    
    clauses = []
    current_clause = None
    current_content = []
    id_counter = {}
    
    def save_clause():
        if current_clause and current_content:
            cn, title = current_clause
            content = '\n'.join(current_content).strip()
            if len(content) >= 10:
                base_id = f"{spec_number}_{release}_{file_stem}_{cn}"
                if base_id in id_counter:
                    id_counter[base_id] += 1
                    doc_id = f"{base_id}_v{id_counter[base_id]}"
                else:
                    id_counter[base_id] = 1
                    doc_id = base_id
                
                clauses.append({
                    "id": doc_id,
                    "spec": spec_number,
                    "release": release,
                    "clause": cn,
                    "title": title,
                    "content": content[:5000],
                    "level": len(cn.split('.')),
                    "file": file_stem
                })
    
    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        
        style = para.style.name if para.style else ""
        is_heading = style.startswith("Heading") or style.startswith("标题")
        clause_num = parse_clause_number(text) if is_heading else None
        
        if is_heading and clause_num:
            save_clause()
            title = re.sub(r'^\d+(?:\.\d+)*\s*', '', text).strip()
            current_clause = (clause_num, title)
            current_content = [f"## {clause_num} {title}"]
        elif current_clause:
            current_content.append(text)
    
    save_clause()
    return clauses

def parse_docx_chunked(docx_path: Path, spec_number: str, release: str, max_chunk_mb: float = 1.5) -> List[dict]:
    """Parse large docx by splitting into chapter-based chunks.
    
    Strategy:
    1. Parse all clauses from the document
    2. Group clauses by top-level chapter (e.g., "4", "5", "6")
    3. Merge small chapters into chunks ≤ max_chunk_mb
    4. If a single chapter > max_chunk_mb, split at sub-clause level
    
    Args:
        docx_path: Path to docx file
        spec_number: Specification number (e.g., "38.133")
        release: Release version (e.g., "Rel-19")
        max_chunk_mb: Target max size per chunk in MB
    
    Returns:
        List of clause dictionaries (same format as parse_docx)
    """
    log(f"  [chunked] Starting chunked parsing: {docx_path.name}", "INFO")
    log(f"  [chunked] Target max chunk size: {max_chunk_mb}MB", "INFO")
    
    # Step 1: Parse all clauses first
    all_clauses = parse_docx(docx_path, spec_number, release)
    if not all_clauses:
        log(f"  [chunked] No clauses parsed, returning empty list", "WARN")
        return []
    
    log(f"  [chunked] Parsed {len(all_clauses)} total clauses", "INFO")
    
    # Step 2: Group by top-level chapter
    chapters: Dict[str, List[dict]] = defaultdict(list)
    for clause in all_clauses:
        clause_num = clause["clause"]
        top_level = clause_num.split('.')[0]
        chapters[top_level].append(clause)
    
    log(f"  [chunked] Grouped into {len(chapters)} top-level chapters: {sorted(chapters.keys())}", "INFO")
    
    # Step 3: Estimate size of a clause list
    def estimate_size_mb(clause_list: List[dict]) -> float:
        """Estimate total content size in MB."""
        total_chars = sum(len(c["content"]) for c in clause_list)
        return total_chars / (1024 * 1024)
    
    # Step 4: Build chunks
    chunks: List[List[dict]] = []
    current_chunk: List[dict] = []
    current_size: float = 0.0
    
    for chapter_num in sorted(chapters.keys(), key=lambda x: int(x)):
        chapter_clauses = chapters[chapter_num]
        chapter_size = estimate_size_mb(chapter_clauses)
        
        if chapter_size > max_chunk_mb:
            # Single chapter too large: split by sub-clauses
            log(f"  [chunked]   Chapter {chapter_num}: {chapter_size:.2f}MB > {max_chunk_mb}MB, splitting by sub-clauses", "INFO")
            
            # Flush current chunk first
            if current_chunk:
                chunks.append(current_chunk)
                current_chunk = []
                current_size = 0.0
            
            # Split this chapter
            sub_chunks: List[List[dict]] = []
            current_sub: List[dict] = []
            current_sub_size: float = 0.0
            
            for clause in chapter_clauses:
                clause_size = estimate_size_mb([clause])
                
                if clause_size > max_chunk_mb:
                    # Even single clause is too large: save current, emit single
                    if current_sub:
                        sub_chunks.append(current_sub)
                    sub_chunks.append([clause])
                    current_sub = []
                    current_sub_size = 0.0
                elif current_sub_size + clause_size > max_chunk_mb:
                    sub_chunks.append(current_sub)
                    current_sub = [clause]
                    current_sub_size = clause_size
                else:
                    current_sub.append(clause)
                    current_sub_size += clause_size
            
            if current_sub:
                sub_chunks.append(current_sub)
            
            chunks.extend(sub_chunks)
            log(f"  [chunked]     Split into {len(sub_chunks)} sub-chunks", "INFO")
        
        elif current_size + chapter_size <= max_chunk_mb:
            # Fits in current chunk
            current_chunk.extend(chapter_clauses)
            current_size += chapter_size
        
        else:
            # Doesn't fit: flush current and start new
            if current_chunk:
                chunks.append(current_chunk)
            current_chunk = chapter_clauses
            current_size = chapter_size
    
    # Don't forget the last chunk
    if current_chunk:
        chunks.append(current_chunk)
    
    # Step 5: Log chunk summary
    log(f"  [chunked] Generated {len(chunks)} chunks:", "INFO")
    for i, chunk in enumerate(chunks):
        chunk_size = estimate_size_mb(chunk)
        chapters_in_chunk = set(c["clause"].split('.')[0] for c in chunk)
        log(f"  [chunked]   Chunk {i+1}: {len(chunk)} clauses, ~{chunk_size:.2f}MB, chapters: {sorted(chapters_in_chunk)}", "INFO")
    
    # Step 6: Flatten all chunks back into clauses list
    # But renumber IDs to avoid collisions
    result = []
    for chunk in chunks:
        for clause in chunk:
            result.append(clause)
    
    return result

# ============== File Operations ==============

def find_zip_file(spec_number: str, release: str) -> Optional[Path]:
    """Find zip file for a specification."""
    series = spec_number.split('.')[0]
    release_dir = PROTOCOL_BASE() / release / f"{series}_series"
    if not release_dir.exists():
        return None
    
    spec_pattern = spec_number.replace(".", "").replace("-", "")
    for zf in sorted(release_dir.glob(f"{spec_pattern}*.zip")):
        return zf
    return None

def get_file_size_mb(file_path: Path) -> float:
    """Get file size in MB."""
    return file_path.stat().st_size / (1024 * 1024)

def determine_mode(docx_path: Path) -> str:
    """Determine parsing mode based on file size.
    
    Auto mode uses this to decide: normal vs chunked.
    """
    size_mb = get_file_size_mb(docx_path)
    if size_mb <= CHUNK_THRESHOLD_MB:
        return "normal"
    else:
        return "chunked"

# ============== Core Operations ==============

class SpecManager:
    """Manage specification operations."""
    
    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
        
    def add(self, spec_number: str, release: str, 
            mode: str = "auto", max_size_mb: float = SKIP_LARGE_MAX_SIZE_MB,
            chapters: Optional[List[str]] = None) -> bool:
        """Add a specification to the database."""
        log(f"Adding {spec_number} ({release})")
        
        zip_path = find_zip_file(spec_number, release)
        if not zip_path:
            log(f"ERROR: Zip file not found for {spec_number}", "ERROR")
            return False
        
        log(f"Found: {zip_path}")
        
        # Extract
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            with zipfile.ZipFile(zip_path, 'r') as z:
                z.extractall(tmpdir)
            
            docx_files = list(Path(tmpdir).glob("*.docx"))
            log(f"Found {len(docx_files)} docx files")
            
            all_clauses = []
            skipped_files = []
            
            for docx_file in docx_files:
                file_stem = docx_file.stem
                
                # Filter chapters if specified
                if chapters:
                    if not any(ch in file_stem for ch in chapters):
                        continue
                
                size_mb = get_file_size_mb(docx_file)
                
                # Determine effective mode for this file
                if mode == "skip":
                    log(f"  [skip] {docx_file.name} ({size_mb:.1f}MB) - skipped by mode")
                    skipped_files.append((docx_file.name, size_mb))
                    continue
                
                if mode == "auto":
                    effective_mode = determine_mode(docx_file)
                else:
                    effective_mode = mode
                
                log(f"  [start] {docx_file.name} ({size_mb:.1f}MB, mode={effective_mode})")
                clauses = []
                parse_success = False
                
                # Auto-fallback: normal → chunked → skip
                if effective_mode == "normal":
                    try:
                        log(f"  [normal] Attempting normal parse...")
                        clauses = parse_docx(docx_file, spec_number, release)
                        log(f"  [normal] OK Success: {len(clauses)} clauses")
                        parse_success = True
                    except Exception as e:
                        log(f"  [normal] X Failed: {e}", "WARN")
                        # Fall through to chunked
                        if mode == "auto":
                            log(f"  [auto] Falling back to chunked mode...", "WARN")
                            effective_mode = "chunked"
                        else:
                            effective_mode = "failed"
                
                # Try chunked if normal failed or was already chunked
                if not parse_success and effective_mode == "chunked":
                    try:
                        log(f"  [chunked] Attempting chunked parse...")
                        clauses = parse_docx_chunked(docx_file, spec_number, release)
                        log(f"  [chunked] OK Success: {len(clauses)} clauses")
                        parse_success = True
                    except Exception as e:
                        log(f"  [chunked] X Failed: {e}", "ERROR")
                        effective_mode = "failed"
                
                # If both failed and auto mode, skip the file
                if not parse_success:
                    if mode == "auto":
                        log(f"  [skip] Both normal and chunked failed, skipping file", "WARN")
                        skipped_files.append((docx_file.name, size_mb))
                    else:
                        log(f"  ERROR: {docx_file.name} parse failed in {mode} mode", "ERROR")
                    continue
                
                all_clauses.extend(clauses)
            
            if skipped_files:
                log(f"Skipped {len(skipped_files)} large files")
            
            if not all_clauses:
                log("ERROR: No clauses parsed", "ERROR")
                return False
            
            log(f"Total clauses: {len(all_clauses)}")
            
            # Add to database
            collection = self.db_manager.get_collection(release)
            if not collection:
                log("ERROR: Cannot create collection", "ERROR")
                return False
            
            # Remove existing
            existing = collection.get(where={"$and": [{"spec": spec_number}, {"release": release}]})
            if existing['ids']:
                log(f"Removing {len(existing['ids'])} existing documents")
                collection.delete(ids=existing['ids'])
            
            # Add new
            batch_ids = []
            batch_docs = []
            batch_metas = []
            
            for clause in all_clauses:
                embed_text = (
                    f"Specification: {clause['spec']}\n"
                    f"Release: {clause['release']}\n"
                    f"Clause: {clause['clause']}\n"
                    f"Title: {clause['title']}\n\n"
                    f"Content:\n{clause['content'][:2000]}"
                )
                
                batch_ids.append(clause['id'])
                batch_docs.append(embed_text)
                batch_metas.append({
                    "spec": clause['spec'],
                    "release": clause['release'],
                    "clause": clause['clause'],
                    "title": clause['title'],
                    "level": clause['level'],
                    "file": clause['file']
                })
                
                if len(batch_ids) >= 100:
                    collection.add(ids=batch_ids, documents=batch_docs, metadatas=batch_metas)
                    batch_ids, batch_docs, batch_metas = [], [], []
            
            if batch_ids:
                collection.add(ids=batch_ids, documents=batch_docs, metadatas=batch_metas)
            
            log(f"SUCCESS: Added {len(all_clauses)} clauses")
            return True
    
    def remove(self, spec_number: str, release: str) -> bool:
        """Remove a specification from the database."""
        log(f"Removing {spec_number} ({release})")
        
        collection = self.db_manager.get_collection(release, create=False)
        if not collection:
            log(f"ERROR: Collection not found for {release}", "ERROR")
            return False
        
        existing = collection.get(where={"$and": [{"spec": spec_number}, {"release": release}]})
        if not existing['ids']:
            log(f"WARNING: {spec_number} not found in {release}")
            return True
        
        collection.delete(ids=existing['ids'])
        log(f"Removed {len(existing['ids'])} documents")
        return True
    
    def update(self, spec_number: str, release: str, **kwargs) -> bool:
        """Update a specification (remove and re-add)."""
        log(f"Updating {spec_number} ({release})")
        self.remove(spec_number, release)
        return self.add(spec_number, release, **kwargs)
    
    def list(self, release: str) -> Dict[str, int]:
        """List all specifications in a release."""
        collection = self.db_manager.get_collection(release, create=False)
        if not collection:
            return {}
        
        results = collection.get()
        specs = Counter(m['spec'] for m in results['metadatas'])
        return dict(specs.most_common())
    
    def status(self) -> dict:
        """Get database status."""
        status = {"releases": {}, "total": 0}
        
        for release in self.db_manager.list_releases():
            collection = self.db_manager.get_collection(release, create=False)
            if collection:
                count = collection.count()
                results = collection.get(limit=min(count, 10000))
                specs = Counter(m['spec'] for m in results['metadatas'])
                status["releases"][release] = {
                    "total": count,
                    "specs": len(specs),
                    "top_specs": dict(specs.most_common(5))
                }
                status["total"] += count
        
        return status
    
    # ========== Version Comparison (B1, B2, B3) ==========
    
    def diff(self, spec_number: str, from_release: str, to_release: str) -> dict:
        """Compare specification between two releases."""
        log(f"Comparing {spec_number}: {from_release} -> {to_release}")
        
        from_collection = self.db_manager.get_collection(from_release, create=False)
        to_collection = self.db_manager.get_collection(to_release, create=False)
        
        if not from_collection or not to_collection:
            return {"error": "Collection not found"}
        
        from_data = from_collection.get(where={"spec": spec_number})
        to_data = to_collection.get(where={"spec": spec_number})
        
        from_clauses = {m['clause']: m for m in from_data['metadatas']}
        to_clauses = {m['clause']: m for m in to_data['metadatas']}
        
        from_set = set(from_clauses.keys())
        to_set = set(to_clauses.keys())
        
        return {
            "spec": spec_number,
            "from_release": from_release,
            "to_release": to_release,
            "from_count": len(from_set),
            "to_count": len(to_set),
            "added": sorted(to_set - from_set),
            "removed": sorted(from_set - to_set),
            "common": sorted(from_set & to_set),
            "added_count": len(to_set - from_set),
            "removed_count": len(from_set - to_set),
            "common_count": len(from_set & to_set)
        }
    
    def new_clauses(self, spec_number: str, from_release: str, to_release: str) -> List[str]:
        """List new clauses in the new release."""
        diff_result = self.diff(spec_number, from_release, to_release)
        return diff_result.get("added", [])
    
    # ========== Batch Operations (C1, C2, C3) ==========
    
    def batch_add(self, release: str, spec_list: Optional[List[str]] = None) -> dict:
        """Batch add specifications."""
        log(f"Batch add for {release}")
        
        if spec_list:
            specs_to_add = spec_list
        else:
            # Find all available specs
            release_dir = PROTOCOL_BASE() / release / "38_series"
            if not release_dir.exists():
                return {"error": f"Release directory not found: {release_dir}"}
            
            specs_to_add = []
            for zf in release_dir.glob("*.zip"):
                spec_num = re.match(r'^(\d{2})(\d{3})', zf.stem)
                if spec_num:
                    specs_to_add.append(f"{spec_num.group(1)}.{spec_num.group(2)}")
        
        results = {"success": [], "failed": [], "total": len(specs_to_add)}
        
        for spec in specs_to_add:
            try:
                if self.add(spec, release):
                    results["success"].append(spec)
                else:
                    results["failed"].append(spec)
            except Exception as e:
                log(f"ERROR adding {spec}: {e}", "ERROR")
                results["failed"].append(spec)
        
        log(f"Batch add complete: {len(results['success'])} success, {len(results['failed'])} failed")
        return results
    
    def batch_update(self, release: str) -> dict:
        """Batch update all existing specifications."""
        log(f"Batch update for {release}")
        
        specs = self.list(release)
        return self.batch_add(release, list(specs.keys()))
    
    def sync(self, release: str) -> dict:
        """Incremental sync - only add/update changed specs."""
        log(f"Sync for {release}")
        
        # For now, same as batch_add
        # Could be enhanced to check timestamps or hashes
        return self.batch_add(release)
    
    # ========== Statistics (E1, E2, E3) ==========
    
    def report(self) -> dict:
        """Generate comprehensive report."""
        log("Generating report")
        
        report_data = {
            "timestamp": datetime.now().isoformat(),
            "databases": {},
            "summary": {}
        }
        
        for release in self.db_manager.list_releases():
            collection = self.db_manager.get_collection(release, create=False)
            if collection:
                count = collection.count()
                # Get all documents (no limit)
                results = collection.get()
                
                specs = Counter(m['spec'] for m in results['metadatas'])
                levels = Counter(m['level'] for m in results['metadatas'])
                files = Counter(m.get('file', 'unknown') for m in results['metadatas'])
                
                report_data["databases"][release] = {
                    "total_documents": count,
                    "total_specs": len(specs),
                    "specs_detail": dict(specs.most_common()),
                    "level_distribution": dict(sorted(levels.items())),
                    "files_count": len(files),
                    "largest_specs": dict(specs.most_common(10))
                }
        
        report_data["summary"] = {
            "total_releases": len(report_data["databases"]),
            "total_documents": sum(d["total_documents"] for d in report_data["databases"].values()),
            "total_specs": sum(d["total_specs"] for d in report_data["databases"].values())
        }
        
        return report_data
    
    def validate(self, release: str) -> dict:
        """Validate data integrity."""
        log(f"Validating {release}")
        
        collection = self.db_manager.get_collection(release, create=False)
        if not collection:
            return {"error": "Collection not found"}
        
        results = collection.get()
        ids = results['ids']
        metadatas = results['metadatas']
        
        issues = []
        
        # Check for duplicate IDs
        id_counts = Counter(ids)
        duplicates = {k: v for k, v in id_counts.items() if v > 1}
        if duplicates:
            issues.append(f"Duplicate IDs: {len(duplicates)}")
        
        # Check for missing metadata
        for i, meta in enumerate(metadatas):
            if not meta.get('spec'):
                issues.append(f"Missing spec at index {i}")
            if not meta.get('clause'):
                issues.append(f"Missing clause at index {i}")
        
        # Check for empty content
        documents = results['documents']
        for i, doc in enumerate(documents):
            if not doc or len(doc.strip()) < 10:
                issues.append(f"Empty content at index {i}")
        
        return {
            "release": release,
            "total_documents": len(ids),
            "issues_count": len(issues),
            "issues": issues[:20],  # Limit to first 20
            "is_valid": len(issues) == 0
        }

# ============== CLI Interface ==============

def create_parser() -> argparse.ArgumentParser:
    """Create argument parser."""
    parser = argparse.ArgumentParser(
        description="3GPP RAG Specification Management Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Commands")
    
    # add command
    add_parser = subparsers.add_parser("add", help="Add a specification")
    add_parser.add_argument("spec", help="Specification number (e.g., 38.300)")
    add_parser.add_argument("--release", default="Rel-19", help="Release version")
    add_parser.add_argument("--mode", choices=["auto", "normal", "chunked", "skip"], 
                           default="auto", help="Parsing mode: auto (normal→chunked→skip) | normal | chunked | skip")
    add_parser.add_argument("--max-size", type=float, default=CHUNK_THRESHOLD_MB, help="Max file size (MB), default 1.5MB")
    add_parser.add_argument("--chapters", help="Specific chapters to add (comma-separated)")
    
    # update command
    update_parser = subparsers.add_parser("update", help="Update a specification")
    update_parser.add_argument("spec", help="Specification number")
    update_parser.add_argument("--release", default="Rel-19", help="Release version")
    
    # remove command
    remove_parser = subparsers.add_parser("remove", help="Remove a specification")
    remove_parser.add_argument("spec", help="Specification number")
    remove_parser.add_argument("--release", default="Rel-19", help="Release version")
    
    # list command
    list_parser = subparsers.add_parser("list", help="List specifications")
    list_parser.add_argument("--release", default="Rel-19", help="Release version")
    
    # status command
    subparsers.add_parser("status", help="Show database status")
    
    # diff command (B1, B2)
    diff_parser = subparsers.add_parser("diff", help="Compare between releases")
    diff_parser.add_argument("spec", help="Specification number")
    diff_parser.add_argument("--from", dest="from_release", default="Rel-19", help="From release")
    diff_parser.add_argument("--to", dest="to_release", default="Rel-20", help="To release")
    
    # new-clauses command (B3)
    new_parser = subparsers.add_parser("new-clauses", help="List new clauses")
    new_parser.add_argument("spec", help="Specification number")
    new_parser.add_argument("--from", dest="from_release", default="Rel-19", help="From release")
    new_parser.add_argument("--to", dest="to_release", default="Rel-20", help="To release")
    
    # batch-add command (C1)
    batch_add_parser = subparsers.add_parser("batch-add", help="Batch add specifications")
    batch_add_parser.add_argument("--release", default="Rel-19", help="Release version")
    batch_add_parser.add_argument("--specs", help="Comma-separated spec list")
    
    # batch-update command (C2)
    batch_update_parser = subparsers.add_parser("batch-update", help="Batch update specifications")
    batch_update_parser.add_argument("--release", default="Rel-19", help="Release version")
    
    # sync command (C3)
    sync_parser = subparsers.add_parser("sync", help="Incremental sync")
    sync_parser.add_argument("--release", default="Rel-19", help="Release version")
    
    # report command (E1)
    subparsers.add_parser("report", help="Generate statistics report")
    
    # validate command (E2)
    validate_parser = subparsers.add_parser("validate", help="Validate data integrity")
    validate_parser.add_argument("--release", default="Rel-19", help="Release version")
    
    # config command (E3)
    config_parser = subparsers.add_parser("config", help="Manage configuration")
    config_parser.add_argument("--list", action="store_true", help="List config")
    config_parser.add_argument("--set", nargs=2, metavar=("KEY", "VALUE"), help="Set config value")
    
    return parser

def main():
    """Main entry point."""
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    
    parser = create_parser()
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    # Initialize
    db_manager = DatabaseManager()
    spec_manager = SpecManager(db_manager)
    
    # Execute command
    if args.command == "add":
        chapters = args.chapters.split(",") if args.chapters else None
        spec_manager.add(args.spec, args.release, args.mode, args.max_size, chapters)
    
    elif args.command == "update":
        spec_manager.update(args.spec, args.release)
    
    elif args.command == "remove":
        spec_manager.remove(args.spec, args.release)
    
    elif args.command == "list":
        specs = spec_manager.list(args.release)
        print(f"\n=== Specifications in {args.release} ===")
        for spec, count in sorted(specs.items()):
            print(f"  {spec}: {count} clauses")
        print(f"\nTotal: {len(specs)} specs, {sum(specs.values())} clauses")
    
    elif args.command == "status":
        status = spec_manager.status()
        print("\n=== Database Status ===")
        for release, data in status["releases"].items():
            print(f"\n{release}:")
            print(f"  Total documents: {data['total']}")
            print(f"  Specifications: {data['specs']}")
            print(f"  Top 5: {data['top_specs']}")
        print(f"\nGrand total: {status['total']} documents")
    
    elif args.command == "diff":
        result = spec_manager.diff(args.spec, args.from_release, args.to_release)
        print(f"\n=== Diff: {args.spec} ({args.from_release} -> {args.to_release}) ===")
        if "error" in result:
            print(f"Error: {result['error']}")
        else:
            print(f"From: {result['from_count']} clauses")
            print(f"To: {result['to_count']} clauses")
            print(f"Added: {result['added_count']}")
            print(f"Removed: {result['removed_count']}")
            if result['added']:
                print(f"\nNew clauses: {', '.join(result['added'][:20])}")
            if result['removed']:
                print(f"Removed clauses: {', '.join(result['removed'][:20])}")
    
    elif args.command == "new-clauses":
        clauses = spec_manager.new_clauses(args.spec, args.from_release, args.to_release)
        if isinstance(clauses, dict) and "error" in clauses:
            print(f"\nError: {clauses['error']}")
        else:
            print(f"\n=== New clauses in {args.spec} ({args.from_release} -> {args.to_release}) ===")
            for clause in clauses:
                print(f"  {clause}")
            print(f"\nTotal: {len(clauses)} new clauses")
    
    elif args.command == "batch-add":
        specs = args.specs.split(",") if args.specs else None
        result = spec_manager.batch_add(args.release, specs)
        print(f"\n=== Batch Add Complete ===")
        print(f"Success: {len(result['success'])}")
        print(f"Failed: {len(result['failed'])}")
        if result['failed']:
            print(f"Failed specs: {', '.join(result['failed'])}")
    
    elif args.command == "batch-update":
        result = spec_manager.batch_update(args.release)
        print(f"\n=== Batch Update Complete ===")
        print(f"Success: {len(result['success'])}")
        print(f"Failed: {len(result['failed'])}")
    
    elif args.command == "sync":
        result = spec_manager.sync(args.release)
        print(f"\n=== Sync Complete ===")
        print(f"Processed: {result['total']}")
    
    elif args.command == "report":
        report = spec_manager.report()
        print("\n=== 3GPP RAG Database Report ===")
        print(f"Generated: {report['timestamp']}")
        print(f"\nSummary:")
        print(f"  Total releases: {report['summary']['total_releases']}")
        print(f"  Total documents: {report['summary']['total_documents']}")
        print(f"  Total specs: {report['summary']['total_specs']}")
        
        for release, data in report['databases'].items():
            print(f"\n{release}:")
            print(f"  Documents: {data['total_documents']}")
            print(f"  Specifications: {data['total_specs']}")
            print(f"  Top 10 specs:")
            for spec, count in list(data['specs_detail'].items())[:10]:
                print(f"    {spec}: {count}")
    
    elif args.command == "validate":
        result = spec_manager.validate(args.release)
        print(f"\n=== Validation: {args.release} ===")
        print(f"Total documents: {result['total_documents']}")
        print(f"Valid: {result['is_valid']}")
        if result['issues']:
            print(f"Issues found: {result['issues_count']}")
            for issue in result['issues']:
                print(f"  - {issue}")
    
    elif args.command == "config":
        config = load_config()
        if args.list:
            print("\n=== Configuration ===")
            def json_serializable(obj):
                """Recursively convert Path objects and other non-serializable types."""
                if isinstance(obj, Path):
                    return str(obj)
                elif isinstance(obj, dict):
                    return {k: json_serializable(v) for k, v in obj.items()}
                elif isinstance(obj, list):
                    return [json_serializable(i) for i in obj]
                elif hasattr(obj, '__iter__') and not isinstance(obj, (str, bytes)):
                    return str(obj)
                return obj
            print(json.dumps(json_serializable(config), indent=2))
        elif args.set:
            key, value = args.set
            config[key] = value
            save_config(config)
            print(f"Set {key} = {value}")

if __name__ == "__main__":
    main()
