# GraphRAG - Neo4j 图数据库
# 用于存储知识图谱的实体与关系，对应 grag_config.yaml 中 graph_databases.neo4j
# 默认连接: bolt://localhost:7687, 用户 neo4j, 密码见 NEO4J_PASSWORD

FROM neo4j:5.26.0-community

# 环境变量（可被 docker-compose 或运行时覆盖）
ENV NEO4J_AUTH=neo4j/change-me-in-production \
    NEO4J_PLUGINS='["apoc"]' \
    NEO4J_dbms_memory_heap_initial__size=512m \
    NEO4J_dbms_memory_heap_max__size=1G \
    NEO4J_dbms_memory_pagecache_size=512m

# 暴露 Bolt 与 HTTP
EXPOSE 7474 7687

# 可选：挂载自定义配置
# COPY neo4j.conf /var/lib/neo4j/conf/neo4j.conf

USER neo4j
# 使用官方镜像默认入口，无需覆盖
