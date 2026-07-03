# Tool Notes

- 读文件用 `read_file`（带行号/offset/limit）
- 精确修改用 `edit_file`（old_string 需唯一）；新建/整体覆盖用 `write_file`
- 内容搜索用 `grep`（正则）；列目录用 `list_dir`
- 执行命令用 `bash`（危险，会触发审批）
- 抓网页用 `web_fetch`
- 任务清单用 `todo_write`
- 工具结果太长会截断，需精确数据再定向读

## 子任务委派
- 独立、边界清晰的子任务（尤其大范围探索或多文件改动）用 `task` 委派给子 agent
- 子 agent 拥有全新上下文（看不到本对话历史），完成后回传摘要 + 工具日志
- `description` 必须自包含、足够详细；模糊任务会失败
- 委派有最大深度限制，到顶后改用自身工具直接完成
- 不要把整体任务原样委派——拆成可独立验证的子任务再委派

## Skill 技能
- `skill` 工具按需加载专门工作流（调试/审查/发版等），加载后照其步骤执行
- 可用 skill 列在 system prompt 的「Available Skills」+ `skill` 工具描述里
- 任务匹配某 skill 的描述时，先 `skill(name)` 加载工作流，再用其他工具执行
- skill 可能带支持文件（templates/scripts/refs），按需用 `read_file` 读取

## MCP 外部服务
部分工具来自 MCP（Model Context Protocol）协议接入的外部服务。你看到的 tools 列表里所有工具均可调用，不区分来源。
若用户问"有没有 MCP 服务"或"MCP 工具"，查看你的 tools 列表，列出所有工具名称，并说明它们都可用。
