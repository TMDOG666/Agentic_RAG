"""app.event_extraction_pipeline
 
 应用层（Application Layer）：事件抽取流水线
 
 该模块实现一个“多技能串联”的事件抽取流程，典型步骤：
 
 1. 文本预处理 / 指代消解（text-preprocess-coref）
 2. 分句（sentence-segmentation）
 3. 逐句事件抽取（event-extraction-srl）
 4. 文档级聚合（event-aggregation）
 
 关键设计点：
 - 模型输出不稳定：即使要求“只输出 JSON”，也可能夹杂解释文本，因此做 JSON 提取容错。
 - 可能触发限流：检测 429/TPM 等提示并做指数退避重试。
 - 可能输出错误的工具调用格式（例如 tool_call 标签）：通过追加约束提示纠偏。
 
 注意：
 - 该模块依赖 `agent_with_skills.run_once()` 作为单轮调用入口。
 - 该模块不关心 LangGraph/Tools/Skills 的内部实现，只负责按步骤编排与聚合。
 """

import json
import time

import agent_with_skills


def _extract_first_json(text: str):
     """尽力从模型输出中提取第一个 JSON（对象或数组）。
 
     说明：许多模型在被要求“只输出 JSON”时仍可能在 JSON 前后夹杂解释性文字。
     这里采用：定位首个 '{' 或 '['，然后用 `json.JSONDecoder().raw_decode()` 解析。
 
     Args:
         text: 模型输出文本。
 
     Returns:
         Any: 解析得到的 JSON 值（dict/list/...）。
 
     Raises:
         ValueError: 无法找到 JSON 起始或解析失败。
     """
     if not text:
         raise ValueError("Empty response")
 
     # 找到所有可能的 JSON 起始位置（最早的那个通常是我们要的）。
     start_candidates = [i for i, ch in enumerate(text) if ch in "[{"]
     if not start_candidates:
         raise ValueError(f"No JSON start found in response: {text[:200]}")
 
     start = start_candidates[0]
 
     decoder = json.JSONDecoder()
     try:
         # raw_decode 会从给定字符串起始位置解析出一个 JSON 值，并返回 (obj, end_pos)。
         obj, _end = decoder.raw_decode(text[start:])
         return obj
     except json.JSONDecodeError as e:
         raise ValueError(f"Failed to parse JSON from response: {text[:200]}") from e
 
 
def _looks_like_tool_call(text: str) -> bool:
     """粗略判断文本是否像“错误的工具调用输出”。 """
     if not text:
         return False
     t = text.lstrip()
     return t.startswith("<tool_call>") or '"tool_call"' in t or '"name": "sentence-segmentation"' in t
 
 
def _is_rate_limited_text(text: str) -> bool:
     """判断文本是否包含“限流/配额”相关提示。 """
     if not text:
         return False
     lowered = text.lower()
     return ("超出限制" in text) or ("rate" in lowered) or ("quota" in lowered) or ("tpm" in lowered) or ("429" in lowered)
 
 
def run_once_json(prompt: str, *, max_retries: int = 5, base_sleep: float = 2.0):
     """调用单轮 agent，并把回复解析为 JSON（带重试/容错）。 """
     last_raw = ""
     for attempt in range(max_retries):
         # 单轮调用：底层会经历 LangGraph 的“模型-工具”循环，最终返回一段文本。
         raw = agent_with_skills.run_once(prompt)
         last_raw = raw or ""
 
         # 1) 限流：指数退避重试。
         if _is_rate_limited_text(last_raw):
             if attempt < max_retries - 1:
                 sleep_s = base_sleep * (2**attempt)
                 time.sleep(sleep_s)
                 continue
             raise RuntimeError(last_raw.strip() or "rate limited")
 
         # 2) 错误 tool_call 格式：追加更强约束提示纠偏。
         if _looks_like_tool_call(last_raw):
             prompt = (
                 prompt
                 + "\n\n重要：你只能使用 load_skill/read_skill_file/execute_skill_script 这三个工具。"
                 + "不要输出 <tool_call>，最终必须直接输出严格 JSON。"
             )
             if attempt < max_retries - 1:
                 time.sleep(base_sleep)
                 continue
 
         # 3) 正常路径：解析首个 JSON。
         try:
             return _extract_first_json(last_raw)
         except Exception:
             if attempt < max_retries - 1:
                 prompt = prompt + "\n\n再次强调：只输出 JSON，不要包含解释性文字。"
                 time.sleep(base_sleep)
                 continue
             raise
 
     raise RuntimeError(f"Failed to parse JSON after retries. last_raw={last_raw[:200]}")
 
 
def run_pipeline(input_text: str):
     """运行完整事件抽取流水线。 """
     if not input_text or not input_text.strip():
         raise ValueError("input_text is empty")
     # Step 1) 文本预处理：主语补全 + 指代消解。
     preprocess_prompt = (
         "使用 text-preprocess-coref 技能。\n"
         "对下面文本做主语补全与指代消解，并严格只输出 JSON。\n\n"
         "重要：resolved_text 必须是非空字符串；如果无法确定如何改写，请原样返回输入文本作为 resolved_text。\n\n"
         f"文本：\n{input_text}"
     )
     preprocess = run_once_json(preprocess_prompt)

     if not isinstance(preprocess, dict):
         raise ValueError(f"preprocess returned non-object json: {type(preprocess).__name__}")

     resolved_text = preprocess.get("resolved_text")
     if not isinstance(resolved_text, str) or not resolved_text.strip():
         fallback_text = (input_text or "").strip()
         if fallback_text:
             preprocess["resolved_text"] = fallback_text
             resolved_text = fallback_text
         else:
             raise ValueError(
                 "preprocess returned empty resolved_text. preprocess="
                 + json.dumps(preprocess, ensure_ascii=False)[:500]
             )

     # Step 2) 分句：得到 sentence 列表（带 id）。
     seg_prompt = (
         "使用 sentence-segmentation 技能。\n"
         "对下面文本分句，并严格只输出 JSON。\n\n"
         f"文本：\n{resolved_text}"
     )
     seg = run_once_json(seg_prompt)
 
     sentences = seg.get("sentences", [])
     if not isinstance(sentences, list) or not sentences:
         raise ValueError("sentence segmentation returned no sentences")
 
     # Step 3) 逐句事件抽取。
     sentence_events = []
     for item in sentences:
         sid = item.get("id")
         sent = item.get("sentence")
         if not sid or not sent:
             continue
 
         ee_prompt = (
             "使用 event-extraction-srl 技能。\n"
             "对下面句子做事件抽取与语义角色标注，并严格只输出 JSON。\n\n"
             f"sentence_id: {sid}\n"
             f"sentence: {sent}\n"
         )
         ee = run_once_json(ee_prompt)
         sentence_events.append(ee)
 
     # Step 4) 文档级聚合。
     agg_prompt = (
         "使用 event-aggregation 技能。\n"
         "将 sentence_events 汇总为文档级事件，并严格只输出 JSON。\n\n"
         f"resolved_text: {resolved_text}\n"
         f"sentence_events: {json.dumps(sentence_events, ensure_ascii=False)}"
     )
     aggregated = run_once_json(agg_prompt)
 
     return {
         "preprocess": preprocess,
         "segmentation": seg,
         "sentence_events": sentence_events,
         "aggregated": aggregated,
     }
