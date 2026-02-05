# GraphRAG - Milvus 向量数据库
# 用于存储文档/实体向量，对应 grag_config.yaml 中 vector_databases.milvus
# 默认连接: localhost:19530 (gRPC)

FROM milvusdb/milvus:v2.4.15

# 单机模式所需组件已包含在镜像中
# 暴露 gRPC 与 metrics
EXPOSE 19530 9091

# 使用默认配置运行 standalone
# 数据持久化通过 volume 挂载
USER milvus
ENTRYPOINT ["milvus"]
CMD ["run", "standalone"]
