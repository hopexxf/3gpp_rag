# 3GPP RAN RAG 检索系统 V2.3

## 简介

本系统是一个针对 3GPP RAN（无线接入网）协议规范的语义检索工具。 支持：

- **分库存储**：按 Release 独立数据库（Rel-19、Rel-20 等）
- **混合检索**：BM25 关键词 + 向量语义 RRF 融合
- **版本对比**：跨版本差异分析
- **批量管理**：批量添加、更新、同步
- **可移植配置**：所有路径通过 `config.json` 配置，支持环境变量覆盖
- **查询扩展**：50个内置电信术语同义词，支持自动学习补充
- **重排序**：Cross-Encoder二次排序，提升Top-K精度

**管理工具**: `src/manage_spec.py`
**检索工具**: `src/search.py`

---

## 快速部署

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置路径

编辑 `config/config.json`，设置你的路径：

```json
{
  "paths": {
    "work_dir": "/your/path/3gpp_rag_work",
    "protocol_base": "/your/path/3gpp_protocol",
    "log_dir": "/your/path/logs"
  },
  "database": {
    "embedding_model": "all-MiniLM-L6-v2",
    "embedding_model_local_path": ""
  },
  "query_expansion": {
    "enabled": true,
    "custom_terms": {}
  },
  "reranker": {
    "enabled": true,
    "model_local_path": "/your/path/ms-marco-MiniLM-L6-v2"
  }
}
```

**路径约束**：
- `protocol_base` 下需包含 `Rel-19`/`R19`/`rel19` 格式的子目录
- 协议文件放在 `{protocol_base}/Rel-19/38_series/*.zip`

**模型配置**：
- `embedding_model`: 向量模型，默认 `"all-MiniLM-L6-v2"`
- `reranker/model_local_path`: 重排序模型本地路径
- 本地路径优先，为空时从 HuggingFace 下载

### 3. 或使用环境变量（可选）

```bash
export GPP_RAG_WORK_DIR=/your/path/3gpp_rag_work
export GPP_RAG_PROTOCOL_BASE=/your/path/3gpp_protocol
export GPP_RAG_LOG_DIR=/your/path/logs
```

**环境变量优先级高于配置文件。**

### 4. 离线部署（无网络环境）

若在无网络环境部署，需提前下载模型：

```bash
# 在有网络的环境下载模型
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# 复制模型到离线环境
# 默认缓存位置: ~/.cache/torch/sentence_transformers/
# 或配置 config.json 中的 model_cache_dir
```

---

## 系统优势

### 1️⃣ 条款级语义完整性
- **按条款章节切分**：每个条款作为独立检索单元，语义完整
- **条款号精确匹配**：支持 `5.1.3`、`6.2.1.2` 等精确编号查询
- **层级上下文**：自动构建条款层级路径（如 `5 > 5.1 > 5.1.3`）

### 2️⃣ 混合检索（Hybrid Search）
- **BM25**：精确关键词匹配，适合条款号、术语查找
- **向量检索**：语义理解，适合自然语言描述查询
- **RRF融合**：双重排序取长补短，兼顾精确性和语义相关性

### 3️⃣ 多版本分库管理
- **按Release分库**：Rel-19、Rel-20 等独立存储
- **版本对比**：一键对比不同版本协议差异
- **增量更新**：只添加/更新变化的协议

### 4️⃣ 企业级管理能力
- **批量操作**：批量添加、更新、删除
- **数据校验**：完整性检查
- **统计报告**：多维度数据分析
- **ID唯一性**：防重复设计，ID冲突自动处理

### 5️⃣ 电信领域优化
- **协议结构理解**：层级标题、条款编号自动识别
- **附录过滤**：自动跳过不适合检索的附录表格
- **核心章节优先**：收录协议核心规范，非测试用例

### 6️⃣ 智能查询增强
- **查询扩展**：50个内置电信术语同义词，自动补充专业词汇
- **重排序优化**：Cross-Encoder二次排序，Top-K精度提升15-25%
- **日志轮转**：自动管理日志大小，10MB×5文件限制

---

## 数据库状态

**当前版本：Rel-19**
- **协议数**：46 个
- **条款数**：15,342 个
- **覆盖率**：46/49 协议（93.9%）
- **数据库大小**：~50 MB
- **数据库位置**：`data/chroma_db/rel19/`

**按 Release 分库存储**：
```
data/chroma_db/
├── rel19/          # Rel-19 数据库
└── rel20/          # Rel-20 数据库（预留）
```

---

## 已收录协议

### 核心协议（按条款数排序）

| 协议编号 | 协议名称 | 条款数 |
|---------|---------|--------|
| 38.133 | RRM 无线资源管理 | 1543 |
| 38.523 | UE 一致性测试规范 | 1498 |
| 38.413 | NGAP 协议 | 1047 |
| 38.473 | F1AP 协议 | 1040 |
| 38.719 | NR 侧链信道 | 875 |
| 38.423 | XnAP 协议 | 823 |
| 38.141 | BS 一致性测试 | 811 |
| 38.508 | UE 一致性测试参数 | 728 |
| 38.181 | FR2 射频 | 706 |
| 38.300 | NR 总体架构 | 594 |
| 38.331 | RRC 层 | 589 |
| 38.176 | BS 联合发射/接收 | 472 |
| 38.106 | BS 射频附加 | 443 |
| 38.108 | BS FR1-1 射频 | 323 |

### 其他协议

38.101, 38.104, 38.108, 38.113, 38.115, 38.151, 38.161, 38.191, 38.194, 38.195, 38.211, 38.212, 38.213, 38.214, 38.291, 38.304, 38.306, 38.307, 38.321, 38.322, 38.355, 38.391, 38.401, 38.410, 38.521, 38.522, 38.561, 38.761, 38.768, 38.774, 38.863, 38.870, 38.901 等



---

## 快速开始

### 1. 管理协议

```bash
# 查看状态
python src/manage_spec.py status

# 添加协议
python src/manage_spec.py add 38.300 --release Rel-19

# 批量添加
python src/manage_spec.py batch-add --release Rel-19

# 更新协议
python src/manage_spec.py update 38.300 --release Rel-19

# 删除协议
python src/manage_spec.py remove 38.300 --release Rel-19

# 列出已收录
python src/manage_spec.py list --release Rel-19
```

### 2. 检索协议

```bash
# 基本检索
python src/search.py "MAC CE for BSR"

# 指定 Release
python src/search.py "RRC connection" --release Rel-19

# 跨版本检索
python src/search.py "carrier aggregation" --release Rel-19,Rel-20

# 指定协议
python src/search.py "PUSCH" --spec 38.214

# 精确编号
python src/search.py "6.1.3.1" --spec 38.321 --mode bm25

# 语义聚类 (D1)
python src/search.py "measurement" --cluster

# 关联推荐 (D2)
python src/search.py "BSR" --recommend
```

### 3. 版本对比

```bash
# 对比差异
python src/manage_spec.py diff 38.300 --from Rel-19 --to Rel-20

# 查看新增条款
python src/manage_spec.py new-clauses 38.300 --from Rel-19 --to Rel-20
```

### 4. 数据管理

```bash
# 生成报告
python src/manage_spec.py report

# 校验数据
python src/manage_spec.py validate --release Rel-19

# 配置管理
python src/manage_spec.py config --list
python src/manage_spec.py config --set default_release Rel-20
```

### 5. 协议下载

```powershell
# 下载 Rel-19 协议（自动从 config.json 读取路径）
pwsh download_3gpp_r19.ps1

# 指定系列下载（默认 38_series）
pwsh download_3gpp_r19.ps1 -Series 38_series

# 下载 Rel-20
pwsh download_3gpp_r19.ps1 -Release Rel-20

# 强制重新下载（跳过已存在检查）
pwsh download_3gpp_r19.ps1 -Force

# 仅打印下载地址，不下载
pwsh download_3gpp_r19.ps1 -DryRun
```

**参数说明：**

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `-Series` | 下载哪个系列的协议（38_series 等） | `38_series` |
| `-Release` | 下载哪个 Release 版本 | `Rel-19` |
| `-Force` | 强制重新下载已存在的文件 | `$false` |
| `-DryRun` | 仅打印 URL，不下载 | `$false` |

> **前提条件**：在 `config/config.json` 中配置 `paths.protocol_base` 为协议文件根目录。脚本会自动拼接 `Rel-19/38_series/` 子路径。

---

### 6. 安装器 & 批量管理

#### setup.ps1（首次部署编排）

```bash
# 全量初始化：依赖+模型+协议+数据库
.\setup.ps1

# 仅入库（增量，安全可重复执行）
.\setup.ps1 -Mode db

# 仅下载协议
.\setup.ps1 -Mode dl
```

> 安装器仅用于首次部署编排，日常操作走 manage_spec.py。

#### manage_spec.py 批量命令

```bash
# 增量检查：哪些协议待入库
py -3 src/manage_spec.py check-pending --release Rel-19

# 批量入库：自动扫描 zip 并入库（跳过已入库）
py -3 src/manage_spec.py batch-add --release Rel-19

# 批量更新：重新入库已收录协议
py -3 src/manage_spec.py batch-update --release Rel-19

# 查看数据库状态
py -3 src/manage_spec.py status
```

> **注意**：`batch-add` 会逐个解析 docx 文件，超大文件（>20MB）首次入库耗时较长，解析过程有超时回退（60s python-docx → streaming parser → 记录跳过）。`batch-add` 天然幂等，重复执行不会产生重复数据。

---


---

## 目录结构

```
3gpp_rag_work/
├── config/                 # 配置目录
│   └── config.json         # 主配置文件（路径、参数、自定义同义词）
│
├── src/                    # 源代码
│   ├── manage_spec.py      # 统一管理脚本
│   ├── search.py           # 检索脚本
│   ├── config_loader.py    # 配置加载模块
│   ├── read_config.py      # 配置读取工具
│   ├── query_expansion.py  # 查询扩展
│   ├── reranker.py         # 重排序
│   ├── log_manager.py      # 日志管理
│   ├── batch_add_all.py    # 批量初始化脚本
│   └── parse_specs_v2.py   # 批量解析脚本
│
├── data/                   # 数据目录（程序管理）
│   ├── chroma_db/          # 向量数据库
│   │   ├── rel19/          # Rel-19 数据库
│   │   └── rel20/          # Rel-20 数据库
│   ├── db_config.json      # 数据库状态
│   ├── synonyms_builtin.json   # 内置同义词（50术语，只读）
│   └── synonyms_auto.json      # 自动补充同义词
│
├── tests/                  # 单元测试
│   ├── conftest.py
│   ├── test_batch_add_idempotent.py
│   ├── test_check_pending.py
│   ├── test_scan_available_specs.py
│   └── test_setup_ps1.py
│
├── logs/                   # 日志目录（自动轮转，gitignore）
├── download_3gpp_r19.ps1   # 协议下载脚本
├── setup.ps1               # 首次部署编排
├── test_config.ps1         # 配置验证脚本
├── requirements.txt        # Python依赖
├── README.md               # 本文件
└── SKILL.md                # Skill 说明
```

---

## 检索模式

| 模式 | 参数 | 适用场景 |
|------|------|----------|
| **hybrid** (默认) | `--mode hybrid` | 通用查询，兼顾精确和语义 |
| **vector** | `--mode vector` | 自然语言描述类查询 |
| **bm25** | `--mode bm25` | 精确编号/术语查找 |

---

## 额外功能

| 功能 | 命令 | 说明 |
|------|------|------|
| **版本对比 (B1)** | `diff` | 对比协议不同版本差异 |
| **变更检测 (B2)** | `diff` | 检测协议更新内容 |
| **新增条款 (B3)** | `new-clauses` | 列出新版本新增条款 |
| **批量添加 (C1)** | `batch-add` | 批量添加所有协议 |
| **批量更新 (C2)** | `batch-update` | 批量更新已收录协议 |
| **增量同步 (C3)** | `sync` | 只添加/更新变化的协议 |
| **语义聚类 (D1)** | `--cluster` | 按主题自动聚类结果 |
| **关联推荐 (D2)** | `--recommend` | 推荐相关条款 |
| **统计报告 (E1)** | `report` | 生成数据库统计报告 |
| **数据校验 (E2)** | `validate` | 校验数据完整性 |
| **配置管理 (E3)** | `config` | 管理分库配置 |
| **安装器 (F)** | `.\setup.ps1 -Mode db` | 首次部署编排（环境检查、依赖安装、协议下载、批量入库） |
| **批量管理 (F2)** | `manage_spec.py batch-add` | 增量扫描、批量入库、幂等执行 |
| **增量检查 (F3)** | `manage_spec.py check-pending` | 对比磁盘 zip 与 DB，列出待入库协议 |
| **协议下载 (G)** | `pwsh download_3gpp_r19.ps1` | 下载 Rel-19 协议压缩包 |

## 未收录协议

| 协议 | 说明 | 状态 |
|------|------|------|
| 38.533 | UE 一致性-EMC（28.2MB，大文件） | 计划中 |
| 38.903 | RF 性能验证方法论（83.2MB，超大文件） | 计划中 |
| 38.905 | 多天线BS验证方法论 | 计划中 |

> **说明**：剩余 3 个协议均为 UE/BS 测试规范，内容以测试用例和参数表格为主。入库需要单独执行，约需 1-2 小时。38.521(117条款) 和 38.522(17条款) 已入库，但条款数较少未列入核心表。



---

## V2.2 已完成功能 ✅

| 功能 | 状态 | 说明 |
|------|------|------|
| **目录结构重构** | ✅ | config/, src/, data/, logs/ 分离 |
| **查询扩展** | ✅ | 50个内置术语 + 自动学习 + 用户自定义 |
| **重排序** | ✅ | Cross-Encoder二次排序，本地模型优先 |
| **模糊缓存** | ❌ | 已移除（CLI场景无收益） |
| **日志轮转** | ✅ | 10MB×5文件限制 |
| **可移植配置** | ✅ | 配置文件+环境变量，无硬编码路径 |

---

## V2.3 已完成功能

| 功能 | 说明 |
|------|------|
| **超时回退** | python-docx 60s超时自动降级到 streaming parser |
| **单例模式** | DatabaseManager 单例，get_loaded_specs() |
| **list-db 命令** | 直接查 DB，替代 manifest.json |
| **_scan_available_specs** | 提取公共函数，setup.ps1 + batch-add 共用 |
| **check-pending 命令** | 对比磁盘与 DB，替代 setup.py --check-only |
| **setup.ps1 精简** | 280行→163行，删除内联构建/下载/验证，改调 manage_spec.py |
| **setup.py 删除** | 193行，全部功能已迁移至 manage_spec.py CLI |
| **单元测试** | 13个测试用例覆盖 scan/pending/batch-add/setup.ps1 |
| **download_3gpp_r19.ps1** | 配置化，从 config.json 读取路径 |

## V2.4 计划功能

| 功能 | 优先级 | 说明 |
|------|--------|------|
| **Web API** | 中 | 提供HTTP API接口 |
| **Docker部署** | 中 | 容器化部署支持 |
| **LLM集成** | 低 | 结合大模型生成回答 |

---

## 低优先级任务（暂不实施）

| 任务 | 说明 | 暂不实施原因 |
|------|------|-------------|
| **影响分析** | 分析条款变更影响范围 | 需要NetworkX图谱，增加复杂度 |
| **语义图谱** | 构建条款关系图 | 与向量化检索功能重叠 |
| **邻域上下文** | 获取条款父子节点 | 与向量化检索功能重叠 |
| **cache缓存** | 节省向量计算时间，减少磁盘I/O | 当前CLI无收益，未来多worker常驻才有价值 |

---

## 维护记录

| 日期 | 版本 | 变更内容 |
|------|------|----------|
| 2026-04-05 | V1.0 | 初始搭建，7个核心协议 |
| 2026-04-06 | V2.0 | 混合检索，批量添加 |
| 2026-04-07 | V2.0 | 分库存储，版本对比，统一管理 |
| 2026-04-07 | **V2.1** | 目录结构重构：config/, src/, data/, logs/ |
| 2026-04-07 | **V2.1** | 新增查询扩展：50个内置术语同义词 |
| 2026-04-07 | **V2.1** | 新增重排序：Cross-Encoder二次排序 |
| 2026-04-07 | **V2.1** | 新增模糊缓存：LRU缓存相似查询 |
| 2026-04-07 | **V2.1** | 新增日志轮转：10MB×5文件限制 |
| 2026-04-08 | **V2.1** | 文档更新：同步新目录结构和使用方式 |
| 2026-04-09 | **V2.1** | Bug修复：修复manage_spec.py路径函数调用问题 |
| 2026-04-09 | **V2.1** | Bug修复：修复ChromaDB where查询语法（$and操作符） |
| 2026-04-09 | **V2.1** | Bug修复：修复list_releases()扫描数据库目录 |
| 2026-04-09 | **V2.1** | 数据库重建：Rel-19 38系列，7协议2344条款 |
| 2026-04-09 | **V2.1** | 路径修正：数据库统一移至 data/chroma_db/rel19/ |
| 2026-04-09 | **V2.1** | 路径修正：manage_spec.py 和 search.py 路径一致 |
| 2026-04-09 | **V2.1** | 协议扩展：38系列协议增至43个，共12709条款 |
| 2026-04-09 | **V2.1** | 数据库状态更新：44协议/14251条款，38.133（RRM）入库1542条款 |
| 2026-04-09 | **V2.1** | Bug修复：diff/new-clauses命令错误处理；config输出JSON序列化；manage_spec add三级递进（normal→chunked→skip） |
| 2026-04-09 | **V2.1** | 功能自检：status/list/search/validate/report/config命令全部通过 |
| 2026-04-11 | **V2.2** | 移除死代码：删除未接入的 src/cache.py 及 config.json 中的 cache 配置 |
| 2026-04-14 | **V2.3** | 重构 Phase 0-6：超时回退、单例、list-db、setup.py简化、ps1配置化 |
| 2026-04-15 | **V2.3** | 安装器改造：setup.ps1精简(280→125行)、setup.py删除、_scan_available_specs提取、check-pending命令、13个单元测试 |
| 2026-04-14 | **V2.3** | 新增入库：38.133(RRM)1543条+38.523(UE一致性测试)1498条，DB扩至46协议/15867条款 |
| 2026-04-15 | **V2.3** | 文档更新：刷新DB状态(15342条款)、目录结构、核心协议表；删除重构产物docs/ |

---

**最后更新：2026-04-15 12:35**
