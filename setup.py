#!/usr/bin/env python3
"""
3GPP RAG 一键初始化脚本 (简化版 V2.3)
用法:
    python setup.py              # 全量初始化
    python setup.py db           # 仅重建数据库
    python setup.py --check-only # 仅输出待入库列表
"""
import sys
import os
import re
import json
import shutil
import subprocess
from pathlib import Path
from datetime import datetime

# ======================= 配置 =======================
WORK_DIR     = Path(__file__).parent.resolve()
CONFIG_PATH  = WORK_DIR / "config" / "config.json"
LOG_DIR      = Path("C:/myfile/qclaw/log")
REL_DIR      = None  # 从 config.json 读取
REQUIRES_PKGS = ["chromadb", "python-docx", "sentence-transformers", "rank-bm25", "numpy", "tqdm"]

# ======================= 日志 =======================
LOG_FP = None

def log_file():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    return LOG_DIR / f"setup_{datetime.now():%Y-%m-%d}.log"

def log(msg, level="INFO"):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}][{level}] {msg}"
    print(line)
    if LOG_FP:
        LOG_FP.write(line + "\n")
        LOG_FP.flush()

# ======================= 工具 =======================
def runpy(*args, **kwargs):
    kw = dict(capture_output=True, text=True, cwd=str(WORK_DIR))
    kw.update(kwargs)
    r = subprocess.run(["py", "-3"] + list(args), **kw)
    return r.returncode, r.stdout, r.stderr

def check_pkg(mod):
    return runpy("-c", f"import {mod}")[0] == 0

def load_config():
    global REL_DIR
    if CONFIG_PATH.exists():
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        REL_DIR = Path(cfg.get("paths", {}).get("protocol_base", "C:/myfile/project/3gpp_protocol")) / "Rel-19" / "38_series"
    else:
        REL_DIR = Path("C:/myfile/project/3gpp_protocol/Rel-19/38_series")
    return cfg if CONFIG_PATH.exists() else {}

# ======================= 阶段0: 环境检查 =======================
def step0_env():
    log("[0/3] 环境检查")
    rc, out, _ = runpy("-c", "import sys; print(sys.version)")
    if rc != 0:
        log("ERROR: Python 3 未找到", "ERROR")
        sys.exit(1)
    log(f"Python: {out.strip()}")
    missing = [p for p in REQUIRES_PKGS if not check_pkg(p)]
    if missing:
        log(f"缺少依赖: {', '.join(missing)}，请先运行 pip install -r requirements.txt", "WARN")

# ======================= 阶段1: 数据库构建 =======================
def get_loaded_specs() -> set:
    """调用 manage_spec.py list-db 获取已入库 spec（直接查 DB，100% 准确）"""
    rc, out, _ = runpy(str(WORK_DIR / "src" / "manage_spec.py"), "list-db", "--release", "Rel-19")
    if rc == 0 and out.strip():
        return set(json.loads(out).keys())
    return set()

def step1_build(check_only=False):
    log("[1/3] 数据库构建")
    load_config()

    if not REL_DIR.exists():
        log(f"ERROR: 协议目录不存在: {REL_DIR}", "ERROR")
        log("请先运行 download_3gpp_r19.ps1 下载协议", "ERROR")
        sys.exit(1)

    # 扫描 zip 文件并去重（取最大文件）
    all_zips = list(REL_DIR.glob("*.zip"))
    if not all_zips:
        log("ERROR: 无 zip 文件", "ERROR")
        sys.exit(1)

    spec_map = {}
    for zf in sorted(all_zips, key=lambda p: p.stat().st_size):
        m = re.match(r"^(\d{2})(\d{3})", zf.stem)
        if m:
            sn = f"{m.group(1)}.{m.group(2)}"
            spec_map[sn] = zf

    total_specs = sorted(spec_map.keys())
    log(f"发现 {len(total_specs)} 个协议")

    # 增量判断：用 list-db 替代 manifest
    done_set = get_loaded_specs()
    pending = [s for s in total_specs if s not in done_set]

    if check_only:
        log(f"已入库: {len(done_set)} 个，待入库: {len(pending)} 个")
        if pending:
            log(f"待入库列表: {', '.join(pending)}")
        return

    if not pending:
        log("所有协议已入库，无需重建", "OK")
        return

    log(f"增量模式: 将入库 {len(pending)} 个协议")

    # 添加 src 到 sys.path
    src_path = WORK_DIR / "src"
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))

    from config_loader import load_config as load_app_config
    from manage_spec import DatabaseManager, SpecManager

    load_app_config()
    db_mgr = DatabaseManager.get_instance()
    spec_mgr = SpecManager(db_mgr)

    failed = []
    for i, spec in enumerate(pending):
        print(f"[{i+1}/{len(pending)}] {spec}", flush=True)
        try:
            ok = spec_mgr.add(spec, "Rel-19", mode="auto")
            if ok:
                print(f"  OK: {spec}", flush=True)
            else:
                failed.append(spec)
                print(f"  FAIL: {spec}", flush=True)
        except Exception as e:
            failed.append(spec)
            print(f"  ERROR: {spec}: {e}", flush=True)

    log(f"完成: {len(pending) - len(failed)}/{len(pending)} 成功", "OK")
    if failed:
        log(f"失败: {', '.join(failed)}", "WARN")

# ======================= 阶段2: 验证 =======================
def step2_verify():
    log("[2/3] 验证")
    src_path = WORK_DIR / "src"
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))

    try:
        from search import search
        r = search("random access", top_n=3, release="Rel-19", mode="hybrid")
        log(f"Search OK: {len(r) if isinstance(r, list) else 0} results", "OK")
        log("3GPP RAG 已就绪！", "OK")
    except Exception as e:
        log(f"Search 验证失败: {e}", "ERROR")

# ======================= 主流程 =======================
def main():
    global LOG_FP

    mode = sys.argv[1] if len(sys.argv) > 1 else "full"
    check_only = "--check-only" in sys.argv

    LOG_FP = open(log_file(), "a", encoding="utf-8")
    start = datetime.now()
    log(f"=== 3GPP RAG 初始化 {datetime.now():%Y-%m-%d %H:%M} ===")

    if check_only:
        step1_build(check_only=True)
    elif mode == "full":
        step0_env()
        step1_build()
        step2_verify()
    elif mode == "db":
        step1_build()
        step2_verify()
    else:
        log(f"未知模式: {mode}，可用: full, db, --check-only", "ERROR")
        sys.exit(1)

    elapsed = (datetime.now() - start).total_seconds() / 60
    log(f"完成！耗时: {elapsed:.1f} 分钟", "OK")
    LOG_FP.close()

if __name__ == "__main__":
    main()
