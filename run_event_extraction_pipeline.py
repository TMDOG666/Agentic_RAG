"""run_event_extraction_pipeline
 
 事件抽取流水线的命令行入口（CLI wrapper）。
 
 该脚本是一个“薄封装”，职责非常单一：
 
 - 读取输入文本文件
 - 调用应用层的 `app.event_extraction_pipeline.run_pipeline()`
 - 将结果（或错误）以统一 JSON 结构写入输出文件
 
 说明：
 - 真实的编排逻辑在 `app/event_extraction_pipeline.py`。
 - 该脚本不直接调用 LangGraph/Tools/Skills，仅作为用户友好的 CLI。
 """
 
import argparse
import json
from pathlib import Path
 
from app.event_extraction_pipeline import run_pipeline


def main():
    """CLI 主入口。
 
    约定参数：
 - `--input`: 输入 .txt 文件路径（必填）
 - `--output`: 输出 .json 文件路径（默认 `event_output.json`）
 
    输出格式（始终写入）：
 
    ```json
    {
      "ok": true/false,
      "error": {"type": "...", "message": "..."} | null,
      "result": { ... } | null
    }
    ```
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Path to input .txt")
    parser.add_argument("--output", default="event_output.json", help="Path to output json")
    args = parser.parse_args()

    # 读取输入文本：统一用 UTF-8。
    input_path = Path(args.input)
    text = input_path.read_text(encoding="utf-8")

    # 调用应用层流水线，并将异常结构化到 error 字段。
    result = None
    error = None
    try:
        result = run_pipeline(text)
    except Exception as e:
        error = {
            "type": type(e).__name__,
            "message": str(e),
        }

    # 统一输出对象：无论成功/失败都落盘，便于上层脚本/程序消费。
    output_obj = {
        "ok": error is None,
        "error": error,
        "result": result,
    }

    # 写出 JSON：
    # - ensure_ascii=False 保留中文
    # - indent=2 便于阅读/调试
    Path(args.output).write_text(
        json.dumps(output_obj, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if error is None:
        print(f"[OK] wrote {args.output}")
    else:
        print(f"[ERROR] wrote {args.output} with error={error['type']}: {error['message']}")

if __name__ == "__main__":
    main()
