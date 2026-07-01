# SOP Execution

- 严格按 SOP 的阶段/步骤执行，不偏离流程
- 每步的目标由 system prompt 的 "Current step goal" 给定
- 步骤 prompt 里的 `${...}` 变量已插值，直接按内容执行
- 若该步有 expected_output，返回符合 schema 的有效 JSON（纯 JSON 或包在 ```json 代码块里均可）
- 完成本步即交还（产出最终答案），不要越界做下一步
