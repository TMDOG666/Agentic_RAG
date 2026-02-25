# DB Scripts (script/db)

本目录存放 **数据库维护/清理脚本**，用于在本地或测试环境中快速清理 GraphRAG（`grag`）使用的各类后端存储。

目前包含：

- `cleanup_all_dbs.py`：清理 Postgres / Neo4j / Milvus 中的 GRAG 数据（**高风险**）。

## 运行方式（推荐：模块调用）

请在项目根目录（例如 `G:\Agentic_RAG`）下执行：

```powershell
python -m script.db.cleanup_all_dbs --help
```

之所以推荐 `python -m ...`：

- 以模块方式运行时，Python 会正确设置包导入路径
- 避免直接运行文件导致的 `No module named 'grag'`

## 前置条件

- 你已激活包含项目依赖的 Python 环境
- 你的配置文件可被读取（默认 `config/grag_config.yaml`，具体见 `grag.config.ConfigManager` 的加载逻辑）
- 对应的数据库服务可连通：
  - Postgres
  - Neo4j
  - Milvus

脚本会在创建各类 client 之前初始化配置：

- `from grag.config import get_config_manager`
- `get_config_manager().initialize()`

## cleanup_all_dbs.py

### 目标

统一入口清理 GRAG 相关数据：

- **Postgres**：删除 `grag_documents / grag_chunks / grag_entities / grag_relations` 表中的数据（或可选 DROP 并重建 schema）
- **Neo4j**：按 label 删除 `:Entity`、`:Document` 节点（会 `DETACH DELETE`）
- **Milvus**：
  - 安全模式：清空你指定的 collection（`--milvus-collections`）
  - 危险模式：直接 drop 当前 Milvus 连接下的所有 collection（`--milvus-drop-all-collections`）

### 安全机制（非常重要）

- 默认是 **dry-run**：
  - 你不传 `--yes` 时，不会执行真实删除
  - 只会打印将要执行的操作

- Milvus 额外保护：
  - 你传了 `--milvus` 但 **没传** `--milvus-collections` / `--milvus-drop-all-collections` 时，会直接跳过 Milvus：

```text
[Milvus] skip: no --milvus-collections provided and --milvus-drop-all-collections not set
```

### 参数说明

- `--yes`
  - **必须**显式传入才会真的删除数据

- `--dry-run`
  - 强制只打印操作、不执行（即使传了 `--yes`）

- `--postgres`
  - 清理 Postgres GRAG 表数据（DELETE）

- `--postgres-drop-tables`
  - **危险**：DROP GRAG 表并重建 schema（用于 schema drift 修复）

- `--neo4j`
  - 清理 Neo4j 中 `:Entity`、`:Document`

- `--milvus`
  - 清理 Milvus（需要结合下面两个参数之一）

- `--milvus-collections c1 c2 ...`
  - 清空指定 collection（更安全）

- `--milvus-drop-all-collections`
  - **极度危险**：drop 当前 Milvus 连接下的所有 collection（忽略 `--milvus-collections`）

### 常用命令示例

1) 查看帮助

```powershell
python -m script.db.cleanup_all_dbs --help
```

2) Dry-run（默认行为）：查看将要删除什么

```powershell
python -m script.db.cleanup_all_dbs --postgres --neo4j --milvus
```

3) 真正清理 Postgres + Neo4j（不动 Milvus）

```powershell
python -m script.db.cleanup_all_dbs --yes --postgres --neo4j
```

4) 真正清理 Milvus（清空指定 collection，推荐）

```powershell
python -m script.db.cleanup_all_dbs --yes --milvus --milvus-collections grag_documents grag_graph_index
```

5) 真正清理 Milvus（drop 所有 collection，不推荐）

```powershell
python -m script.db.cleanup_all_dbs --yes --milvus --milvus-drop-all-collections
```

## 注意事项

- 这些脚本**默认假设你正在操作测试/本地环境**。在共享数据库或生产环境运行前，请先确认连接配置。
- Neo4j 删除逻辑是按 label 删除，仍然属于破坏性操作。
- Milvus 的 `--milvus-drop-all-collections` 可能会删除不属于本项目的 collection（如果你复用了同一个 Milvus 实例）。
