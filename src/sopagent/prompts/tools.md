# Tool Notes

- 读文件用 `read_file`（带行号/offset/limit）
- 精确修改用 `edit_file`（old_string 需唯一）；新建/整体覆盖用 `write_file`
- 内容搜索用 `grep`（正则）；列目录用 `list_dir`
- 执行命令用 `bash`（危险，会触发审批）
- 抓网页用 `web_fetch`
- 任务清单用 `todo_write`
- 工具结果太长会截断，需精确数据再定向读
