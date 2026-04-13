# GraphRAG 数据库 Docker 编排

本目录提供 **Neo4j**、**Milvus**、**PostgreSQL** 三个数据库的 docker-compose 编排，直接使用官方镜像，与项目根目录 `config/grag_config.yaml` 中的默认连接一致。

## 服务与端口

| 服务     | 容器名         | 端口              | 说明           |
|----------|----------------|-------------------|----------------|
| Neo4j    | grag-neo4j     | 7474 (HTTP), 7687 (Bolt) | 图数据库       |
| Milvus   | grag-milvus    | 19530 (gRPC), 9091 (metrics) | 向量库，依赖 etcd + minio |
| etcd     | grag-milvus-etcd  | 2379 (内部)       | Milvus 元数据  |
| minio    | grag-milvus-minio | 9000, 9001        | Milvus 对象存储 |
| PostgreSQL | grag-postgres | 5430              | 关系库         |

## 使用步骤

1. **配置环境变量（推荐）**

   ```bash
   cp .env.example .env
   # 编辑 .env，设置 NEO4J_PASSWORD、POSTGRES_PASSWORD
   ```

2. **启动所有服务**

   ```bash
   cd infrastructure/docker
   docker compose up -d
   ```

3. **查看状态**

   ```bash
   docker compose ps
   docker compose logs -f
   ```

4. **停止并删除容器（数据卷保留）**

   ```bash
   docker compose down
   ```

5. **停止并删除容器与数据卷**

   ```bash
   docker compose down -v
   ```

## 与 grag_config 的对应关系

- **Neo4j**：`graph_databases.neo4j`  
  - `uri: bolt://localhost:7687`  
  - `user: neo4j`  
  - 密码：环境变量 `NEO4J_PASSWORD`

- **Milvus**：`vector_databases.milvus`  
  - `host: localhost`  
  - `port: 19530`

- **PostgreSQL**：`relational_databases.postgres`  
  - `host: localhost`  
  - `port: 5430`  
  - `database: grag`  
  - `user: postgres`  
  - 密码：环境变量 `POSTGRES_PASSWORD`

应用启动前请确保已设置上述环境变量（或在 `.env` 中配置），以便配置层能正确连接三库。

## 目录结构

```
infrastructure/docker/
├── docker-compose.yml   # 编排入口
├── .env.example         # 环境变量示例
└── README.md            # 本说明
```

## 数据持久化

以下命名卷在 `docker-compose.yml` 中定义，重启或 `docker compose down` 不会删除数据（除非使用 `down -v`）：

- `neo4j_data`
- `milvus_etcd`
- `milvus_minio`
- `milvus_data`
- `postgres_data`
