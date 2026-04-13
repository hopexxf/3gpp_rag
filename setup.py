#!/usr/bin/env python3
"""
3GPP RAG 一键初始化脚本
用法:
    python setup.py           # 全量初始化
    python setup.py db       # 仅重建数据库
    python setup.py dl       # 仅下载协议
"""
import sys
import os
import re
import json
import shutil
import traceback
import subprocess
from pathlib import Path
from datetime import datetime

# ======================= 配置 =======================
WORK_DIR    = Path(__file__).parent.resolve()
PROTOCOL    = Path("C:/myfile/project/3gpp_protocol")
LOG_DIR     = Path("C:/myfile/qclaw/log")
REL_DIR     = PROTOCOL / "Rel-19" / "38_series"
EMBED_MODEL = Path("C:/myfile/project/all-MiniLM-L6-v2")
RERANK_MODEL= Path("C:/myfile/project/ms-marco-MiniLM-L6-v2")

BASE_URL_3GPP = "https://www.3gpp.org/ftp/Specs/2026-03/Rel-19"
SERIES_LIST = [
    '22_series','23_series','24_series','25_series','26_series','27_series',
    '28_series','29_series','31_series','32_series','33_series','34_series',
    '35_series','36_series','37_series','38_series'
]

REQUIRES_PKGS = [
    "chromadb", "python-docx", "sentence-transformers",
    "rank-bm25", "numpy", "tqdm"
]

# ======================= 日志 =======================

def log_file():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    return LOG_DIR / f"setup_{datetime.now():%Y-%m-%d}.log"

LOG_FP = None

def log(msg, level="INFO"):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}][{level}] {msg}"
    print(line)
    if LOG_FP:
        LOG_FP.write(line + "\n")
        LOG_FP.flush()

def log_step(msg):
    log("", "STEP")
    log(f" {msg}", "STEP")

# ======================= 工具 =======================

def runpy(*args, **kwargs):
    """运行 py -3，返回 (returncode, stdout, stderr)"""
    kw = dict(capture_output=True, text=True, cwd=str(WORK_DIR))
    kw.update(kwargs)
    r = subprocess.run(["py", "-3"] + list(args), **kw)
    return r.returncode, r.stdout, r.stderr

def check_pkg(mod):
    """检查 Python 包是否已安装"""
    return runpy("-c", f"import {mod}")[0] == 0

def ensure_dir(p):
    p = Path(p)
    if not p.exists():
        p.mkdir(parents=True, exist_ok=True)
        log(f"Created: {p}")
    return p

# ======================= 阶段0: 环境检查 =======================

def step0_env():
    log_step("[0/4] 环境检查")
    rc, out, err = runpy("-c", "import sys; print(sys.version)")
    if rc != 0:
        log("ERROR: Python 3 未找到", "ERROR")
        sys.exit(1)
    log(f"Python 3: {out.strip()}")

    missing = [p for p in REQUIRES_PKGS if not check_pkg(p)]
    if missing:
        log(f"缺少依赖: {', '.join(missing)}", "WARN")
    else:
        log("依赖包: 全部已安装", "OK")

# ======================= 阶段1: 安装依赖 =======================

def step1_deps():
    log_step("[1/4] 安装依赖")
    req = WORK_DIR / "requirements.txt"
    if not req.exists():
        log(f"ERROR: {req} 不存在", "ERROR")
        sys.exit(1)

    log(f"安装: py -3 -m pip install -r {req}")
    rc, out, err = runpy("-m", "pip", "install", "-r", str(req), "--quiet")
    if rc != 0:
        log("pip install 失败（可能需要管理员权限）", "ERROR")
        log("提示: 以管理员身份运行 PowerShell 后重试", "ERROR")
        sys.exit(1)

    missing = [p for p in REQUIRES_PKGS if not check_pkg(p)]
    if missing:
        log(f"仍有缺失: {', '.join(missing)}，尝试单独安装...", "WARN")
        rc2, _, _ = runpy("-m", "pip", "install", *missing, "--quiet")
        if rc2 != 0:
            log("重装失败", "ERROR")
            sys.exit(1)
    log("依赖安装验证: OK", "OK")

# ======================= 阶段2: 模型检查 =======================

def step2_models():
    log_step("[2/4] 模型检查")
    if EMBED_MODEL.exists():
        log(f"Embedding 模型存在: {EMBED_MODEL}", "OK")
    else:
        log(f"Embedding 模型不存在（将在首次查询时自动下载）", "WARN")
    if RERANK_MODEL.exists():
        log(f"Reranker 模型存在: {RERANK_MODEL}", "OK")
    else:
        log(f"Reranker 模型不存在（将在首次查询时自动下载）", "WARN")

# ======================= 阶段3: 下载协议 =======================

def step3_download():
    log_step("[3/4] 协议下载")

    if REL_DIR.exists():
        cnt = len(list(REL_DIR.glob("*")))
        log(f"已有文件: {cnt} 个")
        if cnt >= 50:
            log(f"文件已齐全（≥50），跳过下载。如需重新下载请删除 {REL_DIR}", "OK")
            return
    else:
        ensure_dir(REL_DIR)

    import urllib.request
    import urllib.error

    file_exts = ('.pdf','.doc','.docx','.xls','.xlsx','.zip','.tar.gz','.tgz','.rtf','.cdf')
    visited = set()
    total_dl = total_skip = total_err = 0
    failed = []

    def is_real_dir(url):
        return not any(url.lower().endswith(ext) for ext in file_exts)

    def get_file_links(html, base):
        links = []
        for m in re.finditer(r'href="(https://www\.3gpp\.org/ftp/Specs/[^"?\s]+\.(?:pdf|doc|docx|xls|xlsx|zip|tar\.gz|tgz|rtf|cdf))"', html):
            url = m.group(1)
            if url.startswith(base + "/") and not url.endswith("/") and len(url) > len(base) + 1:
                links.append(url)
        return links

    def get_subdirs(html, base):
        dirs = []
        for m in re.finditer(r'href="(https://www\.3gpp\.org/ftp/Specs/[^"?]+)"', html):
            url = m.group(1).rstrip("/")
            if url != base and is_real_dir(url):
                dirs.append(url)
        return dirs

    def process_folder(url, local_dir):
        if url in visited:
            return
        visited.add(url)
        ensure_dir(local_dir)

        log(f"[SCAN] {url}")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                html = resp.read().decode("utf-8", errors="replace")
        except Exception as e:
            log(f"  [ERR] 请求失败: {e}", "ERROR")
            return

        # 下载文件
        for furl in get_file_links(html, BASE_URL_3GPP):
            fname = Path(furl).name
            rel_f = furl[len(BASE_URL_3GPP)+1:].replace("/", os.sep)
            local = PROTOCOL / rel_f
            ensure_dir(local.parent)

            if local.exists():
                log(f"  [SKIP] {fname}")
                total_skip += 1
            else:
                try:
                    log(f"  [DOWN] {fname}")
                    req2 = urllib.request.Request(furl, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req2, timeout=60) as resp2:
                        with open(local, "wb") as f2:
                            shutil.copyfileobj(resp2, f2)
                    total_dl += 1
                except Exception as e:
                    log(f"  [ERR] {fname}: {e}", "ERROR")
                    total_err += 1
                    failed.append(furl)

        # 递归子目录
        for sub in get_subdirs(html, BASE_URL_3GPP):
            rel_sub = sub[len(BASE_URL_3GPP)+1:].replace("/", os.sep)
            process_folder(sub + "/", PROTOCOL / rel_sub)

    # 根目录
    log("[ROOT]", "STEP")
    try:
        req = urllib.request.Request(BASE_URL_3GPP, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        for furl in get_file_links(html, BASE_URL_3GPP):
            fname = Path(furl).name
            local = PROTOCOL / fname
            if local.exists():
                log(f"  [SKIP] {fname}"); total_skip += 1
            else:
                try:
                    log(f"  [DOWN] {fname}")
                    req2 = urllib.request.Request(furl, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req2, timeout=60) as resp2:
                        with open(local, "wb") as f2:
                            shutil.copyfileobj(resp2, f2)
                    total_dl += 1
                except Exception as e:
                    log(f"  [ERR] {fname}", "ERROR"); total_err += 1; failed.append(furl)
    except Exception as e:
        log(f"[ROOT ERR] {e}", "ERROR")

    # 各 series
    for s in SERIES_LIST:
        log(""); log(f"=== {s} ===", "STEP")
        url = f"{BASE_URL_3GPP}/{s}"
        process_folder(url + "/", PROTOCOL / s)

    log("")
    log(f"下载完成: Downloaded={total_dl}  Skipped={total_skip}  Errors={total_err}", "INFO")
    for f in failed:
        log(f"  FAIL: {f}", "WARN")

    if REL_DIR.exists():
        final_cnt = len([p for p in REL_DIR.glob("*") if p.is_file()])
        log(f"38_series 最终文件数: {final_cnt}", "INFO")

# ======================= 阶段4: 构建数据库 =======================

def step4_build():
    log_step("[4/4] 数据库构建")

    if not REL_DIR.exists():
        log(f"ERROR: 协议目录不存在: {REL_DIR}", "ERROR")
        log("请先运行: python setup.py dl", "ERROR")
        sys.exit(1)

    all_zips = list(REL_DIR.glob("*.zip"))
    if not all_zips:
        log("ERROR: 38_series 中无 zip 文件", "ERROR")
        sys.exit(1)
    log(f"发现 {len(all_zips)} 个 zip 文件")

    # 去重（同名取最大文件）
    spec_map = {}
    for zf in sorted(all_zips, key=lambda p: p.stat().st_size):
        m = re.match(r"^(\d{2})(\d{3})", zf.stem)
        if m:
            sn = f"{m.group(1)}.{m.group(2)}"
            if sn not in spec_map:
                spec_map[sn] = zf
    spec_list = sorted(spec_map.keys())
    log(f"去重后: {len(spec_list)} 个协议")

    # 过滤超大文件（>30MB zip），避免内存爆炸
    too_big = []
    safe_list = []
    for sn in spec_list:
        zf = spec_map[sn]
        size_mb = zf.stat().st_size / 1_048_576
        if size_mb > 20:
            too_big.append((sn, size_mb))
            log(f"跳过超大文件 ({size_mb:.0f}MB): {sn} - {zf.name}", "WARN")
        else:
            safe_list.append(sn)
    spec_list = safe_list
    log(f"最终入库: {len(spec_list)} 个协议（跳过 {len(too_big)} 个超大文件）")

    # 增量模式：用 manifest.json 记录已入库的协议，避免重复扫描 ChromaDB
    db_dir = WORK_DIR / "data" / "chroma_db" / "rel19"
    manifest_path = db_dir / "manifest.json"
    manifest = {}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            manifest = {}
    done_set = set(manifest.get("specs", []))
    if done_set:
        already_done = [s for s in spec_list if s in done_set]
        spec_list = [s for s in spec_list if s not in done_set]
        log(f"增量模式: 已入库 {len(already_done)} 个，跳过")
    else:
        log("manifest.json 不存在或为空，将全量重建")
        if db_dir.exists():
            shutil.rmtree(db_dir)
        db_dir.mkdir(parents=True, exist_ok=True)

    # 添加到 sys.path
    src_path = WORK_DIR / "src"
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))

    from config_loader import load_config
    from manage_spec import DatabaseManager, SpecManager

    load_config()
    db_mgr = DatabaseManager()
    spec_mgr = SpecManager(db_mgr)

    total = len(spec_list)
    done = 0
    failed = []

    for i, spec in enumerate(spec_list):
        pct = (i + 1) * 100 // total
        print(f"[{pct}%] {i+1}/{total} {spec}", flush=True)
        try:
            ok = spec_mgr.add(spec, "Rel-19", mode="auto")
            if ok:
                done += 1
                done_set.add(spec)
                manifest["specs"] = sorted(done_set)
                manifest["updated"] = datetime.now().isoformat()
                manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
                print(f"  OK: {spec}", flush=True)
            else:
                failed.append(spec)
                print(f"  FAIL: {spec}", flush=True)
        except Exception as e:
            failed.append(spec)
            print(f"  ERROR: {spec}: {e}", flush=True)
            traceback.print_exc()
            sys.stdout.flush()

    log(f"DONE: {done}/{total} success, {len(failed)} failed", "OK")
    if failed:
        log(f"Failed: {', '.join(failed)}", "WARN")

    # 最终状态
    log(""); log("=== 数据库最终状态 ===", "STEP")
    st = SpecManager(DatabaseManager()).status()
    for rel, data in st["releases"].items():
        log(f"{rel}: {data['total']} docs, {data['specs']} specs", "OK")
    log(f"Total: {st['total']} docs", "OK")

# ======================= Search 验证 =======================

def test_search():
    log(""); log("=== Search 验证 ===", "STEP")
    src_path = WORK_DIR / "src"
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))

    try:
        from search import search
        r = search("random access", top_n=3, release="Rel-19", mode="hybrid")
        count = len(r) if isinstance(r, list) else 0
        log(f"Search OK: {count} results", "OK")
        for item in (r if isinstance(r, list) else []):
            spec = item.get("spec", "?") if isinstance(item, dict) else str(item)
            title = (item.get("title", "") or "")[:50] if isinstance(item, dict) else ""
            log(f"  [{spec}] {title}", "OK")
        log("3GPP RAG 已就绪，可以开始查询！", "OK")
    except Exception as e:
        log(f"Search 验证失败: {e}", "ERROR")
        traceback.print_exc()

# ======================= 主流程 =======================

def main():
    global LOG_FP

    mode = sys.argv[1] if len(sys.argv) > 1 else "full"

    LOG_FP = open(log_file(), "a", encoding="utf-8")

    start = datetime.now()
    log("")
    log("=" * 40, "INFO")
    log(f" 3GPP RAG 一键初始化 {datetime.now():%Y-%m-%d %H:%M}", "INFO")
    log(f" 模式: {mode}", "INFO")
    log("=" * 40, "INFO")

    if mode == "full":
        step0_env()
        step1_deps()
        step2_models()
        step3_download()
        step4_build()
        test_search()
    elif mode == "db":
        step4_build()
        test_search()
    elif mode == "dl":
        step3_download()
    else:
        log(f"未知模式: {mode}，可用: full, db, dl", "ERROR")
        sys.exit(1)

    elapsed = (datetime.now() - start).total_seconds() / 60
    log("")
    log("=" * 40, "INFO")
    log(f" 完成！耗时: {elapsed:.1f} 分钟", "INFO")
    log(f" 日志: {log_file()}", "INFO")
    log("=" * 40, "INFO")

    LOG_FP.close()

if __name__ == "__main__":
    main()
