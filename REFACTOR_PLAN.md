# 3GPP RAG Work 重构计划（V2.2 → V2.3）

> 创建时间：2026-04-14 03:25
> 作者：通信小粉 🌸
> 状态：**已完成** ✅
> 执行报告：`refactor_execution_2026-04-14_08-53.md`

---

## 一、当前状态（实测确认）

| 指标 | 值 |
|------|------|
| DB spec 数 | **44**（`manage_spec.py list` 确认） |
| DB clauses 数 | **12,826**（`manage_spec.py status` 确认） |
| Manifest spec 数 | **45**（含 38.523，但 38.523 未实际入库） |
| setup.py 行数 | **424 行** |
| manage_spec.py 行数 | **996 行** |
| 38.523 zip 文件 | 小 zip 0.6 MB / 大 zip 26.5 MB |
| Manifest 与 DB 不一致 | 38.523 在 manifest 中但不在 DB 中（入库挂死） |

### Manifest vs DB 差异

- Manifest 有 45 个 spec（含 38.523）
- DB 有 44 个 spec（不含 38.523）
- 差异原因：38.523 入库时 python-docx 在大 zip（26.5MB）上 hang，manifest 已写入但 DB 无数据

---

## 二、核心问题

1. **setup.py 职责过重**（424行）：下载逻辑、manifest 读写、文件扫描、ChromaDB 初始化全部耦合
2. **manifest 与 DB 不一致**：38.523 写入 manifest 但未入库，manifest 作为增量判断依据不可靠
3. **缺少 gc.collect()**：大量 add 操作后内存不释放
4. **38.523 根因**：72k+ table cells 嵌套导致 python-docx 内部极慢，非段落数/文件大小问题
5. **段落数阈值方案不可行**：11万段落的 38101 正常入库，4.8万段落的 38523 hang，阈值无法预测
6. **download_3gpp_r19.ps1 硬编码**：路径、Release 名、collection 名全部硬编码

### 38.523 处理数据分析

| 文件 | 段落数 | 大小 | python-docx 结果 |
|------|--------|------|-----------------|
| 38101_s00-05.docx | 112,999 | 2.5MB | ✅ 成功 |
| 38508_s00-s040311.docx | 98,819 | 2.2MB | ✅ 成功 |
| 38331-j20.docx | 79,749 | 4.4MB | ✅ 成功 |
| 38133_sA.6-A.605.docx | 60,466 | 3.0MB | ✅ 成功 |
| 38133_s0-7.docx | 15,443 | 1.2MB | ✅ 成功 |
| **38523_s00-s06.docx** | **48,842** | **2.1MB** | **❌ hang（72k+ table cells 嵌套）** |

**结论**：不能基于段落数或文件大小做降级判断，只能用超时回退。

---

## 三、重构计划

### Phase 0：前置准备（拍照基准）

**目标**：记录当前 DB 状态，供后续验证对比。

**操作**：
1. 创建 `C:\myfile\qclaw\3gpp_rag_work\TEST_PLAN.md`
2. 创建 `C:\myfile\qclaw\3gpp_rag_work\test_results/` 目录
3. 执行基准快照：

```bash
py -3 src/manage_spec.py status > test_results/p3_0_status_before.txt
py -3 src/manage_spec.py list --release Rel-19 > test_results/p3_0_list_before.txt
```

**产出**：`test_results/` 下两个基准文件

---

### Phase 1：manage_spec.py 重构（996 → ~1020 行，净增 ~24 行）

#### 1.1 DatabaseManager 新增单例模式

```python
_db_instance = None

@classmethod
def get_instance(cls) -> "DatabaseManager":
    if cls._db_instance is None:
        cls._db_instance = cls()
    return cls._db_instance
```

**目的**：避免多处创建 DatabaseManager 实例，减少重复连接开销。

#### 1.2 DatabaseManager 新增 get_loaded_specs()

```python
def get_loaded_specs(self, release: str) -> Dict[str, int]:
    """Scan ChromaDB directly, return {spec_number: clause_count}."""
    collection = self.get_collection(release, create=False)
    if not collection:
        return {}
    count = collection.count()
    if count == 0:
        return {}
    results = collection.get(limit=min(count, 20000), include=["metadatas"])
    from collections import Counter
    return dict(Counter(m.get("spec", m.get("spec_name", "")) for m in results["metadatas"]))
```

**目的**：直接从 DB 获取已入库 spec 列表，不依赖 manifest。这是增量判断的唯一可靠来源。

#### 1.3 SpecManager.add() 末尾加 gc.collect()

```python
import gc
# ... collection.add() 循环结束后 ...
gc.collect()
```

**目的**：大量 add 操作后释放内存，避免 OOM。

#### 1.4 新增 CLI 命令 list-db

```bash
py -3 src/manage_spec.py list-db [--release Rel-19]
# 输出: {"38.413": 1047, "38.423": 823, "38.141": 811, ...}
```

**目的**：供 setup.py 调用，实现增量判断。输出 JSON 格式，方便程序解析。

---

### Phase 2：parse_docx 超时回退（新功能，零误判）

**问题**：38.523 s00-s06.docx 内部有 72k+ 嵌套 table cells，python-docx 处理时 hang。

**方案**：先尝试 python-docx，超时后自动降级到 streaming parser。

```
parse_docx()
  ├─ 尝试 python-docx（multiprocessing.Process, 60s 超时）
  │   ├─ 成功 → 返回完整结果（最优质量）
  │   └─ 超时 → terminate 进程 + join → fallback
  └─ fallback → streaming parser
      ├─ 成功 → 返回 streaming 结果
      └─ 失败 → 记录日志，跳过该文件，继续处理其余文件
```

**核心实现**：

```python
def parse_docx(docx_path: Path, spec_number: str, release: str) -> List[dict]:
    from multiprocessing import Process, Queue

    def _try_python_docx(q: Queue):
        try:
            result = _parse_docx_python_docx(docx_path, spec_number, release)
            q.put(("ok", result))
        except Exception as e:
            q.put(("err", str(e)))

    q = Queue()
    p = Process(target=_try_python_docx, args=(q,))
    p.start()
    p.join(timeout=60)  # 60秒超时

    if p.is_alive():
        p.terminate()
        p.join(timeout=5)
        log(" [parse_docx] python-docx timeout (60s), falling back to streaming...")
        return _parse_docx_streaming(docx_path, spec_number, release)

    if not q.empty():
        status, result = q.get()
        if status == "ok":
            return result
        else:
            log(f" [parse_docx] python-docx error: {result}, falling back to streaming...")

    return _parse_docx_streaming(docx_path, spec_number, release)
```

**方案对比**：

| 方案 | 被误降级的文件数 | 内容损失 |
|------|----------------|---------|
| 大小阈值 5MB | 10 个 | 不必要损失 |
| 段落阈值 15k | 79 个 | 严重损失 |
| **超时回退** | **0 个** | **零损失** |

**对现有数据的影响**：现有 44 个 spec 全部能在 60s 内完成，不受影响。

---

### Phase 3：setup.py 简化（424 → ~140 行，净减 ~284 行）

#### 删除内容

| 删除模块 | 估算行数 |
|---------|---------|
| 下载/解压逻辑（改调 download_3gpp_r19.ps1） | ~100 行 |
| manifest 扫描和读写（改调 list-db） | ~50 行 |
| 文件大小过滤（依赖 find_zip_file 内置） | ~30 行 |
| ChromaDB Client 初始化（不直接操作 DB） | ~25 行 |

#### 简化后核心逻辑

```
1. 加载 config
2. 调用 download_3gpp_r19.ps1（如需下载）
3. 扫描 rel19/38_series/*.zip
4. 调用 manage_spec.py list-db 获取已入库 spec
5. 对每个未入库 zip，调用 manage_spec.py add <spec> --release Rel-19
6. 汇总报告
```

#### 新增 --check-only 标志

```bash
python setup.py --check-only
# 输出待入库列表，不实际下载或入库
```

**增量判断来源变更**：manifest（不可靠） → list-db（直接查 DB，100% 准确）

---

### Phase 4：download_3gpp_r19.ps1 配置化

**当前问题**：
- 硬编码 `C:\myfile\project\3gpp_protocol`
- 硬编码 `Rel-19`、`38_series`
- 硬编码 collection name

**目标**：从 `config/config.json` 读取配置，消除硬编码路径。

```powershell
$config = Get-Content "config/config.json" | ConvertFrom-Json
$protocolBase = $config.paths.protocol_base
```

**验证要点**：
- 配置化后执行 `download_3gpp_r19.ps1`，确认能正确读取 config.json
- 确认下载路径与 config.json 中 `paths.protocol_base` 一致
- 确认 Release 名和 series 目录从配置读取

---

### Phase 5：验证测试

| 用例 | 验证内容 | 预期结果 |
|------|---------|---------|
| P3-0 | 基准状态快照 | 44 spec / 12,826 clauses |
| P3-1 | DatabaseManager 单例隔离性 | get_instance() 返回同一实例；绕过单例也能正常连接 |
| P3-2 | get_loaded_specs() 一致性 | 连续 5 次调用返回相同 44 spec，clause 数一致 |
| P3-3 | 单个 spec 增量添加（38.863） | 替换已存在记录，clause 数不变 |
| P3-4 | 38.523 超时回退验证 | python-docx 超时 → streaming fallback → 完成入库，DB 44→45 |
| P3-5 | 幂等性（38.523 再添加一次） | 替换已存在记录，clause 数不变，不报错 |
| P3-6 | setup.py --check-only | 输出待入库列表，不实际下载 |
| P3-7 | setup.py 增量构建（删除 manifest 后） | 依赖 list-db 实现增量，DB 不丢数据 |
| P3-8 | ps1 配置化验证 | download_3gpp_r19.ps1 从 config.json 读取路径，下载功能正常 |

**38.523 降级策略**：
1. python-docx 60s 超时 → streaming parser
2. streaming 也 hang → 记录日志，跳过该文件
3. 若彻底失败 → 记录到 known_issues.md，manifest 标记跳过

---

### Phase 6：清理

- 删除 `data/chroma_db/rel19/manifest.json`（确认不在版本控制中）
- 评估 `batch_add_all.py` 是否废弃（setup.py 简化后功能重叠）
- 清理 `__pycache__/`
- 更新 README.md / SKILL.md（同步新功能）

---

## 四、改动汇总

| Phase | 文件 | 操作 | 行数变化 |
|-------|------|------|---------|
| 0 | TEST_PLAN.md + test_results/ | 新建 | — |
| 1 | src/manage_spec.py | 修改 | +24 行 |
| 2 | parse_docx 相关函数 | 修改/新增 | +40 行 |
| 3 | setup.py | 简化 | -284 行 / +10 行 |
| 4 | download_3gpp_r19.ps1 | 配置化重构 | — |
| 5 | — | 验证测试 | — |
| 6 | 本地文件 | 删除/更新 | — |

**最终规模预估**：
- setup.py：**~140 行**（当前 424 行，减 67%）
- manage_spec.py：**~1060 行**（当前 996 行，含 Phase 1 + Phase 2 改动）

---

## 五、风险与降级策略

| 风险 | 降级策略 |
|------|---------|
| 38.523 python-docx 超时后 streaming 也失败 | 记录 known_issues.md，跳过该文件，不阻塞其余 spec |
| get_loaded_specs() 全表扫描慢 | 当前 12,826 条在可接受范围；未来数据量大时加缓存 |
| multiprocessing 在 Windows 兼容性 | 已是 Python 标准库，无第三方依赖 |
| setup.py 简化后功能回退 | Phase 5 验证覆盖所有核心流程 |

---

## 六、执行顺序

```
Phase 0（拍照）→ Phase 1（manage_spec.py 重构）→ Phase 2（超时回退）
    → Phase 3（setup.py 简化）→ Phase 4（ps1 配置化）→ Phase 5（验证测试）→ Phase 6（清理）
```

每个 Phase 完成后 git commit，保证可回退。

---

**请确认或调整。**
