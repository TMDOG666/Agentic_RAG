# grag.data_client

数据层（Data Layer）模块，负责统一管理 GraphRAG 运行时所需的三类存储客户端：

- Neo4j（图数据库）
- Milvus（向量数据库）
- PostgreSQL（关系数据库）

本模块的核心目标是：

- 为上层（graph_construction / retrieval / storage_impl / scripts）提供 **一致的获取 client 的方式**
- 从 `grag.config` 读取配置（`grag_config.yaml`）并延迟初始化依赖（neo4j / pymilvus / psycopg2）

## 模块结构

- `data_client_manager.py`
  - `DataManager`：统一持有并懒加载 Neo4j/Milvus/Postgres client
  - `get_data_manager()`：全局单例入口（推荐）

- `neo4j_client.py`
  - `Neo4jClient`：封装 Neo4j Driver 创建、健康检查、关闭
  - `get_neo4j_client()`：Neo4jClient 的“单 client 单例”入口

- `milvus_client.py`
  - `MilvusClient`：封装 Milvus 连接、断开、健康检查
  - `get_milvus_client()`：MilvusClient 的“单 client 单例”入口

- `postgres_client.py`
  - `PostgresClient`：封装 Postgres 连接参数组装、连接获取、健康检查
  - `get_postgres_client()`：PostgresClient 的“单 client 单例”入口

- `__init__.py`
  - 对外 re-export：`get_data_manager/get_neo4j_client/get_milvus_client/get_postgres_client` 等

## 推荐调用入口（你应该怎么用）

### 1) 推荐：统一从 `get_data_manager()` 获取

上层模块通常使用：

```python
from grag.data_client import get_data_manager

dm = get_data_manager()
neo4j = dm.get_neo4j_client()
milvus = dm.get_milvus_client()
pg = dm.get_postgres_client()
```

好处：

- 只需要持有一个对象（DataManager）
- client 是懒加载的（首次调用才创建）
- 有统一的 `test_all_connections()` / `cleanup()`

### 2) 直接使用单 client getter（仅在你确实只想要某一个库时）

```python
from grag.data_client import get_milvus_client
milvus = get_milvus_client()
```

## 配置来源

所有 client 都通过 `get_config_manager().get_settings()` 读取配置，配置文件默认位置由配置层决定（通常是 `config/grag_config.yaml`）。

关键配置项：

- `graph_db_provider` -> `graph_databases.<provider>`
- `vector_db_provider` -> `vector_databases.<provider>`
- `relational_db_provider` -> `relational_databases.<provider>`

密码推荐使用 `*_env` 从环境变量注入。

## 依赖与延迟导入

为了避免“只 import 模块就强制要求装齐所有 DB SDK”，本模块对依赖做了延迟导入：

- Neo4j：`neo4j` 包在真正 `get_driver()` 时才导入
- Milvus：`pymilvus` 在真正 `connect()` 时才导入
- Postgres：`psycopg2` 在真正 `get_connection()` 时才导入

这样做可以让非 DB 场景（例如部分单测、静态分析）更稳定。

## 是否存在冗余代码？（当前观察）

是的，有一处明显的“功能重叠/冗余入口”：

- **DataManager 里已经缓存了三个 client 的单例**（`self._neo4j/_milvus/_postgres`）
- 同时每个 client 模块里又提供了各自的 **全局单例**：
  - `get_neo4j_client()` / `get_milvus_client()` / `get_postgres_client()`

这会带来两个问题：

- **同一进程里可能出现两套单例**：
  - 你如果有时用 `get_data_manager().get_milvus_client()`
  - 有时又用 `get_milvus_client()`
  - 可能得到的是两个不同的 `MilvusClient` 实例（各自维护连接状态），容易困惑。

- **维护成本更高**：
  - 任何“默认 provider 规则、缓存策略、清理策略”的变更都可能要在两套入口里同步。

### 建议（不做破坏性修改的前提下）

- **规范调用**：在业务代码里统一使用 `get_data_manager()`，避免混用。
- **未来可精简**：保留 `get_data_manager()` 作为唯一单例入口；把 `get_*_client()` 改为“简单工厂”（不再持有全局单例）或标记为内部/不推荐。

> 我当前只做了文档说明，没有对代码做破坏性重构；如果你希望我进一步“去冗余”，我可以按你偏好给出一个最小改动方案。
