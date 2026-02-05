# GraphRAG - PostgreSQL 关系数据库
# 用于存储元数据、流水记录等，对应 grag_config.yaml 中 relational_databases.postgres
# 默认连接: localhost:5432, 数据库 grag, 用户 postgres, 密码见 POSTGRES_PASSWORD

FROM postgres:16-alpine

# 时区与编码
ENV TZ=Asia/Shanghai \
    POSTGRES_INITDB_ARGS="--encoding=UTF8 --locale=C"

# 初始化时创建应用库（若需自定义可挂载 init 脚本）
ENV POSTGRES_DB=grag \
    POSTGRES_USER=postgres

# 默认密码仅用于开发；生产请通过 POSTGRES_PASSWORD 或 secrets 注入
ENV POSTGRES_PASSWORD=postgres

EXPOSE 5432

# 可选：挂载初始化 SQL
# COPY init.sql /docker-entrypoint-initdb.d/

USER postgres
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["postgres"]
