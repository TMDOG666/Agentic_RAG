# Graph Builder Module

KNOWLEDGE_FUSION_PROMPT = """
**Role (角色):**
你是一位资深的知识图谱编纂专家和数据融合工程师。你的任务是审查一组从不同来源抽取的、描述相似或相同实体的碎片化信息，并将它们整合成一个单一、权威、全面的知识实体。

**Goal (目标):**
对输入的 JSON 实体列表进行实体对齐（Entity Resolution）和知识融合（Knowledge Fusion）。
1.  **对齐 (Align)**: 识别出列表中哪些条目实际上是指向同一个现实世界对象的（例如，同义词、别名、全称与简称、不同语言的称呼等）。
2.  **融合 (Fuse)**: 将被对齐的所有实体的信息（类型、描述、属性）合并，生成一段全新的、信息密度更高、逻辑更连贯的综合描述。
3.  **标准化 (Standardize)**: 为合并后的实体确定一个最常用或最官方的“标准名称”（Canonical Name）。

**Input Format (输入格式):**
一个 JSON 列表，其中每个对象包含：`name` (名称), `type` (类型), `description` (来自不同文档的碎片化描述)。

**Output Format (输出格式):**
请仅输出一个合法的 JSON 列表，不要包含任何 Markdown 标记或解释性文字。
*   如果所有输入实体都被合并为一个，则列表只包含一个对象。
*   如果输入实体中有多个独立对象，则列表包含多个对象。

**输出 JSON 对象的结构:**
[
  {{
    "canonical_name": "标准名称 (最常用或最官方的名称)",
    "type": "统一后的最准确类型",
    "aliases": ["别名1", "别名2", "输入中的其他名称"],
    "description": "融合后的综合描述 (必须整合所有来源的核心事实，如时间、地点、关键属性、因果关系，50字以内)"
  }},
  ...
]

**Critical Rules (关键原则):**
1.  **保守合并原则**: 只有当你**高度确定**两个实体是同一个时才进行合并。如果存在歧义（例如，同名但描述明显不同），请将它们保留为独立的实体，并通过修改 `canonical_name` 来区分，例如 `李明 (歌手)` 和 `李明 (教授)`。
2.  **信息无损原则**: 融合后的 `description` 必须包含所有被合并实体描述中的**核心事实**，不能丢失重要信息。如果信息有时间先后，请按时间顺序组织。
3.  **类型选择**: `type` 应选择最具体、最准确的那个。例如，在 `Organization` 和 `Company` 中选择 `Company`。

***

**Example (示例):**

**Input:**
[
  {{"name": "国际商业机器公司", "type": "Organization", "description": "一家美国的跨国科技公司，总部位于纽约州阿蒙克。"}},
  {{"name": "IBM", "type": "Company", "description": "在2011年开发了问答电脑系统“沃森”。"}},
  {{"name": "深蓝", "type": "Product", "description": "IBM公司研发的，在1997年击败国际象棋世界冠军卡斯帕罗夫的超级计算机。"}},
  {{"name": "沃森", "type": "AI System", "description": "一种能够回答自然语言问题的人工智能程序。"}}
]

**Output:**
[
  {{
    "canonical_name": "IBM",
    "type": "Company",
    "aliases": ["国际商业机器公司"],
    "description": "一家总部位于纽约州阿蒙克的美国跨国科技公司，开发了著名的人工智能系统“沃森”(2011年)和超级计算机“深蓝”(1997年)。"
  }},
  {{
    "canonical_name": "深蓝",
    "type": "Product",
    "aliases": [],
    "description": "由IBM公司研发的超级计算机，在1997年击败了国际象棋世界冠军加里·卡斯帕罗夫。"
  }},
  {{
    "canonical_name": "沃森",
    "type": "AI System",
    "aliases": [],
    "description": "由IBM公司于2011年开发的一种能够回答自然语言问题的人工智能计算机系统。"
  }}
]

***

**待处理实体列表 (JSON):**
{entities_json}
"""