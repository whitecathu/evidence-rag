# 架构与接口

## 数据流

`app/core.py` 负责原文解析、分块、Embedding、存储和检索；`app/main.py` 暴露 API。SQLite 存储知识库、原始文件及分块；Qdrant 保存向量与文档/知识库过滤字段。所有查询通过知识库 ID 限定范围，只返回 ready 文档。

长段落按 800 字符窗口、650 字符步长切片，重叠 150 字符。独立 Markdown 标题用于更新分块元数据，不单独作为答案片段。中文检索采用单字与双字切分，英文采用词切分；这是轻量基线，不是专业中文分词器。

文件先写入 queued 状态，BackgroundTasks 处理为 processing → ready/failed。处理中的进程中断后，重启将其标记为 failed，用户可重试。上传内容按 SHA256 在知识库内去重。失败的部分索引不会用于搜索，重试前清理。SQLite 与 Qdrant 没有分布式事务，因此删除遇到向量服务错误时保留元数据，避免谎报完成；可再次删除恢复。

生产扩展方向：持久化作业队列、按知识库分片、用户认证、资源授权、解析进程隔离。当前解析任务在同一进程，适合可信的小型本地文档。

## API

| 接口 | 行为 |
|---|---|
| `GET /api/health` | 服务状态与 demo/live 模式 |
| `GET/POST /api/libraries` | 列出/创建知识库 |
| `GET/POST /api/libraries/{kb}/documents` | 文档列表 / multipart 上传 |
| `POST /api/documents/{id}/retry` | 重新处理文档 |
| `DELETE /api/documents/{id}` | 删除向量、分块、原文件记录 |
| `POST /api/libraries/{kb}/search` | 检索调试，返回原文、来源定位与排名分数 |
| `POST /api/libraries/{kb}/chat` | 先返回 sources，再返回 token，最后 done 或 error |

搜索与问答请求：`{"question":"问题", "strategy":"hybrid"}`。策略为 `vector`、`hybrid`、`rerank`。重排未配置时明确报错。完整 schema 见运行服务的 `/docs`。

SSE `done` 包含耗时、模式、被引用的来源编号及编号范围检查结果。前端用纯文本显示模型内容，避免直接执行 HTML；引用列表可展开原文。语义是否受到来源支持需要评测，范围检查只检查编号合法性。

参考：[Qdrant Python local mode](https://github.com/qdrant/qdrant-client)、[Qdrant Query API](https://api.qdrant.tech/api-reference/search/query-points)。
