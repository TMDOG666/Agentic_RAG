# grag.graph_construction

图构建（Knowledge Graph Construction）模块：把一份文档文本加工为可入库的图谱资产（文档/分块/向量/实体/关系），并最终写入后端存储（Postgres + Milvus + Neo4j）。

## 推荐入口（你应该怎么调用）

### 1) 对外推荐：`GRAG.build_kg(...)`

如果你是业务方/脚本/服务调用方，建议通过 Facade：

```python
from grag.entrypoint import GRAG

api = GRAG()
res = api.build_kg(
    text="...",
    doc_time="2026-01-01T00:00:00Z",
    doc_name="example",
    group_id="my_group",
    doc_id="doc_001",
)
```

`GRAG.build_kg` 的职责是：

- 自动初始化配置（`get_config_manager().initialize()`）
- 创建 `DataClientGraphStorage`（决定写入到哪个 Milvus collection / graph index collection）
- 创建并调用 `GraphBuilder.build_and_save(...)`

你不需要了解内部如何组装 storage / builder。

### 2) 内部/测试入口：`GraphBuilder.build_and_save(...)`

当你需要：

- 自定义 storage（FakeStorage / InMemoryStorage）
- 注入 embedding_fn（避免真实 embedding 调用）
- 控制构建过程的依赖注入

可以直接使用 `GraphBuilder`：

```python
from grag.graph_construction.graph_builder import GraphBuilder
from grag.storage.storage_impl import DataClientGraphStorage

storage = DataClientGraphStorage(
    milvus_collection_name="my_collection",
    milvus_graph_index_collection_name="grag_graph_index",
    milvus_upsert_strategy="delete_then_insert",
)

builder = GraphBuilder(storage=storage)
res = builder.build_and_save(
    text="...",
    doc_time="2026-01-01T00:00:00Z",
    doc_name="example",
    group_id="my_group",
    doc_id="doc_001",
)
```

### 3) 仅跑流水线（不落库）：`GraphConstructionManager.run(...)`

当你只想拿到“中间产物”（coref、chunk、抽取 raw、解析结果、fusion 输出等），用于：

- 调试抽取质量
- 做离线分析
- 不希望写库

可以直接用 `GraphConstructionManager`：

```python
from grag.graph_construction.graph_construction_manager import GraphConstructionManager

mgr = GraphConstructionManager()
result = mgr.run(
    text="...",
    doc_time="2026-01-01T00:00:00Z",
    doc_name="example",
    group_id="my_group",
    doc_id="doc_001",
)
```

注意：这条路径 **不会** 计算 embedding，也 **不会** 落库。

## 主流程（Pipeline 概览）

整体可以理解为两层：

- **流程编排层（orchestration）**：`GraphConstructionManager`
- **资产构建与落库层（asset building + persistence）**：`GraphBuilder` + `GraphStorage`

典型流程：

1. Coreference Resolution（指代消解）
2. Chunking（分块）
3. Entity/Relation Extraction（实体关系抽取，LLM）
4. Parsing（将 raw 文本解析为结构化实体/关系）
5. Intra-document Fusion（文档内实体融合、关系重写）
6. Embedding（对 chunk 计算向量）
7. Save（写入 storage：Postgres/Milvus/Neo4j）

## 主要模块与职责

- `coreference_resolver.py`
  - 指代消解（将“他/她/公司”等指代替换为更明确实体）

- `chunker.py`
  - `SemanticChunker`：把长文拆分为适合 LLM 的 chunk

- `entity_relation_extractor.py`
  - `EntityRelationExtractor`：逐 chunk 调用 LLM 抽取实体/关系（raw 文本）

- `entity_relation_parser.py`
  - `parse_entity_relation_raw`：把抽取 raw 文本解析为结构化对象

- `entity_resolution_knowledge_fusion.py`
  - 文档内实体归一、别名合并、关系重写等 fusion 逻辑

- `graph_construction_manager.py`
  - `GraphConstructionManager`：串联上述步骤，产出 `GraphConstructionResult`

- `graph_builder.py`
  - `GraphBuilder`：
    - 调用 manager
    - 计算 chunk embedding
    - 构造 `DocumentRecord/ChunkRecord/ChunkEmbeddingRecord/GraphEntityRecord/GraphRelationRecord`
    - 调用 `GraphStorage` 落库

## 与 storage / data_client 的关系

- `GraphBuilder` 不直接依赖数据库驱动。
- 通过 `grag.storage.GraphStorage` 接口写入。
- 生产实现通常是 `DataClientGraphStorage`：内部使用 `grag.data_client.get_data_manager()` 来拿到 Postgres/Milvus/Neo4j client。

## 产物（输出数据结构）

- `GraphConstructionResult`（来自 manager）
  - coref 结果
  - chunks 的抽取/解析结果
  - fusion 结果（通常挂在 `graph` 字段里）

- `GraphBuildResult`（来自 builder/build_kg）
  - `construction`（完整 pipeline 结果）
  - `document/chunks/embeddings/entities/relations`（可入库资产）

## 常见踩坑

- **入口混用**：推荐对外统一用 `GRAG.build_kg`，避免业务侧直接 new builder/manager。
- **配置初始化**：Facade 会自动初始化配置；如果你绕开 Facade，记得先初始化配置。
- **外部依赖**：LLM / embedding provider 需要正确的 API Key 环境变量与网络可用。
