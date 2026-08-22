# 11 踩坑实录：9 个真实 bug

> 这 9 个 bug 全部来自 2026-08-22/23 的重构与全链路验证，每个都附定位过程。面试讲"排查过的最难问题"直接从这里取材。
> 通用教训在最后。

## 坑 1：CLI 调用了不存在的方法（幽灵方法）

- **现象**：CLI 每 5 轮打印"Triggering long-term memory extraction..."但 Milvus 永远没数据；退出时 finally 块直接 `AttributeError`
- **根因**：`memory.extract_and_save_preferences(...)` —— MemoryManager 根本没有这个方法（早期重构改名成 `background_extract`/`finalize_session`，CLI 没跟着改）；`asyncio.create_task` 包住的异常静默吞掉，只有 finally 里那次裸抛
- **修复**：改为真实方法并传入提取 LLM；后台任务持有强引用
- **教训**：`create_task` 的异常默认不可见——要么存引用加回调，要么 await

## 坑 2：redis:7-alpine 没有 RediSearch

- **现象**：`Checkpointer disabled: unknown command 'FT.INFO'`，图静默降级为无状态
- **根因**：`langgraph-checkpoint-redis` 用 RediSearch（FT.*）建索引起索引，官方 redis 镜像不带该模块
- **修复**：compose 换 `redis/redis-stack-server:7.4.0-v0`；`FT.INFO checkpoint` 返回 "Unknown index name"（而非 unknown command）即达标
- **教训**：依赖中间件的高级特性先查模块支持；降级日志救了这个 bug（否则多轮失效无人知晓）

## 坑 3：最小配置下一连串"静默禁用"

- **现象**：`agent/.env` 只配 `DASHSCOPE_API_KEY` 时，长期记忆、语义缓存、向量工具各自打印"disabled: no embedding key"
- **根因**：三个地方各自实现了一套 embedding key 判定逻辑，都缺"仅 DashScope key"的回退；且互不一致
- **修复**：settings 里统一 `get_embedding_api_key()`（显式 key > LLM 渠道组合 > 纯 DashScope 回退），工具层全部改为复用
- **教训**：同一配置的判定逻辑出现第二份时，就该收敛成一份

## 坑 4：ChatOpenAI 默认连 api.openai.com

- **现象**：orchestrator 节点 `OpenAIConnectionError: Connection error`，SSE 流中断
- **根因**：没配 `BASE_URL` 时 langchain-openai 默认 OpenAI 端点，DashScope key 打过去必失败
- **修复**：`get_model_config()` 在未配独立 LLM 渠道时默认 `https://dashscope.aliyuncs.com/compatible-mode/v1`
- **教训**："OpenAI 兼容"不等于"免配置"——端点是兼容的一部分

## 坑 5：Neo4j 连接读的是占位符默认值

- **现象**：`Could not connect ... ensure that the url is correct`，URL 是 `bolt://YOUR_NEO4J_HOST:7687`
- **根因**：`graph_tool.py` 用 `os.getenv("NEO4J_URI", "bolt://YOUR_NEO4J_HOST:7687")`，根本没走 settings/.env
- **修复**：改用 `get_settings()` 的 neo4j 配置
- **教训**：模板代码里的 YOUR_XXX 占位符是雷，接入时全局搜一遍

## 坑 6：Neo4j 密码配置漂移

- **现象**：连接到了 Neo4j 但报凭证错误；独立脚本用 `password123` 能连
- **定位**：打印 settings 值的指纹（首尾字符）发现是 8 位——`settings.py` 默认 `password`，compose 是 `password123`，两边默认值不一致
- **修复**：settings 默认值对齐 compose
- **教训**：同一凭据出现在两处配置源时，默认值必须一致；对比测试时**硬编码的"成功样本"与"失败样本"只差在配置**，就查配置指纹

## 坑 7：语义缓存从不写入

- **现象**：重复提问永远 miss（每次都全流程 60s）
- **根因**：`set_cache` 只有预载脚本调用，在线链路推理成功后没人写缓存
- **修复**：chat_service 推理完成后 `set_cache(query, response, user_id)`，缓存自填充
- **教训**：读路径验证完必须验证写路径——缓存这种"读着读着才有"的组件尤其容易漏

## 坑 8：app 层 Settings 必填字段挡启动

- **现象**：uvicorn 启动即 `ValidationError: redis_url Field required`
- **根因**：`app/app_config/settings.py` 的 `redis_url: str` 无默认值，而 agent 层同名字段有默认——两套 Settings 行为不一致
- **修复**：补默认值
- **教训**：同一环境变量在两套配置类里的"必填性"也要对齐

## 坑 9：load_preferences 漏了必填参数（自己刚写的 bug）

- **现象**：第 5 轮提取正确触发，但 `Extraction failed: missing 1 required positional argument: 'query'`
- **根因**：重写 MemoryManager 时给 `load_preferences` 的 `query` 加了必填，内部调用没传
- **修复**：参数补默认值 + 去重时显式传宽泛查询并拉 top_k=20
- **教训**：触发周期长的后台逻辑（每 5 轮）单测覆盖不到——冒烟测试要显式调用一次完整路径

## 通用教训（面试收尾用）

1. **静默降级 + 告警日志 = 可自愈也可自欺**：每个"disabled"都要有人在验证清单上打勾
2. **配置漂移是原型项目第一大 bug 来源**（9 个坑里 5 个是）：同义配置收敛到单一 source of truth
3. **验证靠客观断言**：直读 Redis/Milvus/日志事件，别信"看起来返回正常"
