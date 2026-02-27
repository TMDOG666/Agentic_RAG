# script.grag

本目录放置可直接运行的脚本（非 pytest），用于手工验证 / 端到端评测。

## 1) 智云科技 2024 年报摘要评测脚本

### 脚本

- `eval_zhiyun_2024_report.py`

### 运行方式（模块模式）

在项目根目录 `G:\Agentic_RAG` 下执行：

```bash
python -m script.grag.eval_zhiyun_2024_report
```

#### PowerShell 注意事项

如果你在 Windows PowerShell 里运行：

- PowerShell **不支持** Bash 的 `\` 续行写法。
- PowerShell 续行请使用反引号 `` ` ``（注意：反引号后面不能有多余空格）。

一行写法：

```powershell
python -m script.grag.eval_zhiyun_2024_report --docx "test/grag/test_data/input/文档正文：智云科技股份有限公司 2024 年度报告（摘要）.docx" --top-k 10 --graph-index-collection grag_graph_index --no-cleanup
```

续行写法：

```powershell
python -m script.grag.eval_zhiyun_2024_report `
  --docx "test/grag/test_data/input/文档正文：智云科技股份有限公司 2024 年度报告（摘要）.docx" `
  --top-k 10 `
  --graph-index-collection grag_graph_index `
  --no-cleanup
```

打印图（实体/边）用于评估：

```powershell
python -m script.grag.eval_zhiyun_2024_report --print-graph --graph-top-n 30 --no-cleanup
```

只检索（不入库）模式：

```powershell
python -m script.grag.eval_zhiyun_2024_report --skip-ingest --group-id "<已有group_id>" --milvus-collection "<已有collection>" --doc-id "<已有doc_id>" --print-graph --graph-top-n 30
```

### 参数

```bash
python -m script.grag.eval_zhiyun_2024_report \
  --docx "test/grag/test_data/input/文档正文：智云科技股份有限公司 2024 年度报告（摘要）.docx" \
  --top-k 10 \
  --graph-index-collection grag_graph_index \
  --no-cleanup
```

- `--docx`
  - 要入库并评测的 docx 路径。
- `--top-k`
  - 各检索模式返回 top_k 条。
- `--skip-ingest`
  - 只跑检索，不执行入库（不会读取 docx，也不会写 Postgres/Milvus/Neo4j）。
  - 开启后必须显式传 `--group-id` 和 `--milvus-collection`。
- `--group-id`
  - 指定 group_id（不传则自动生成）。
- `--milvus-collection`
  - 指定 Milvus collection（不传则自动生成）。
- `--graph-index-collection`
  - Milvus graph_index collection name (默认：`grag_graph_index`)。
- `--doc-id`
  - 可选。只检索模式下用于从 Postgres 自动选一个实体（用于 local/global_ 扩图）。
- `--graph-entity`
  - 可选。显式指定图检索入口实体名（优先级高于 `--doc-id` 自动挑选）。
- `--no-cleanup`
  - 不清理本次写入的数据（便于使用 Attu/Neo4j Browser 手工检查）。
- `--print-graph`
  - 打印 local/global_ 检索返回的图结构（nodes/edges），并尽量展示节点/边的 description。
- `--graph-top-n`
  - 控制最多打印多少个 node/edge（默认 30），避免输出过长。

### 做了什么

- 使用 `PreprocessingManager(use_llm=False)` 解析 docx -> 文本（只做解析 + basic_clean）。
- 使用 `GRAG.build_kg(...)` 入库（Postgres + Milvus + Neo4j + graph_index collection）。
- 依次评测检索模式：
  - `GRAG.chunks_keyword(...)`
  - `GRAG.chunks_vector(...)`
  - `GRAG.entities(...)`
  - `GRAG.relations(...)`
- 根据原文构造若干问题，打印每种模式的：
  - hits 数量
  - top1 是否命中 / 是否有任意命中（简单召回/质量指标）
  - TopN 命中 chunk 文本预览

### 依赖与前置条件

- 外部服务：Postgres / Milvus / Neo4j 可用（脚本启动时会打印连接测试结果）。
- `python-docx`：用于解析 docx（`grag.preprocessing.DocumentProcessor` 依赖）。
- 模型侧配置：embedding/LLM 的 provider 与 key/endpoint（取决于你的 `config/grag_config.yaml` 与环境变量）。

### 常见问题

- 关键词检索命中为 0
  - keyword 检索通常是连续子串匹配（ILIKE）。问题语句如果完全不包含原文片段，可能导致 keyword 召回低。
- local/global 跑不起来
  - 这两种模式依赖图入库后的实体信息。脚本会从 Postgres 抽一个实体作为入口；若抽不到会自动跳过。
