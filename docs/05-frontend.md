# 前端 Vue 应用

## 前端职责

`front/clinical_cds/` 是一个 Vite + Vue 3 + TypeScript 单页应用，提供医生使用的聊天式临床决策支持界面。

主要功能：

- 创建诊疗会话。
- 输入患者症状或用药情况。
- 提供常见场景快捷卡片。
- 调用后端 `/api/chat`。
- 读取 SSE 流式响应。
- 使用 Markdown 渲染 CDS 回复。

## 目录结构

```text
front/clinical_cds/
├── index.html
├── package.json
├── vite.config.ts
├── tsconfig.json
├── tsconfig.app.json
├── tsconfig.node.json
└── src/
    ├── App.vue
    ├── main.ts
    └── assets/
        ├── base.css
        └── main.css
```

## 技术栈

核心依赖：

- `vue`
- `element-plus`
- `@element-plus/icons-vue`
- `marked`
- `axios`

开发依赖：

- `vite`
- `typescript`
- `vue-tsc`
- `@vitejs/plugin-vue`
- `vite-plugin-vue-devtools`

虽然安装了 `axios`，当前 `App.vue` 实际使用的是浏览器原生 `fetch()`。

## 启动命令

```bash
cd front/clinical_cds
npm install
npm run dev
```

类型检查：

```bash
npm run type-check
```

生产构建：

```bash
npm run build
```

预览构建结果：

```bash
npm run preview
```

## Vite 配置

文件：

```text
front/clinical_cds/vite.config.ts
```

配置点：

- 启用 Vue 插件。
- 启用 Vue DevTools 插件。
- 设置 `@` 别名指向 `src/`。

```ts
resolve: {
  alias: {
    '@': fileURLToPath(new URL('./src', import.meta.url))
  },
}
```

## 应用入口

文件：

```text
front/clinical_cds/src/main.ts
```

做的事情：

1. 引入本地样式 `./assets/main.css`。
2. 引入 Element Plus 样式。
3. 创建 Vue app。
4. 安装 Element Plus。
5. 挂载到 `#app`。

```ts
const app = createApp(App)
app.use(ElementPlus)
app.mount('#app')
```

## 主页面 `App.vue`

当前前端所有主要逻辑都集中在：

```text
front/clinical_cds/src/App.vue
```

页面布局：

- 左侧侧边栏：
  - 系统品牌。
  - 会话列表。
  - 新建诊疗会话按钮。
  - 当前医生用户标识。
- 右侧主区域：
  - 标题。
  - 医疗免责声明。
  - 消息区。
  - 输入区。

## 会话状态

核心状态：

```ts
const userId = ref('doctor_001')
const currentSessionId = ref('session_' + Date.now())
const sessions = ref([{ id: currentSessionId.value, name: '新诊疗会话' }])
const messages = ref<any[]>([])
const inputMessage = ref('')
const isThinking = ref(false)
```

说明：

- `userId` 固定为 `doctor_001`。
- `currentSessionId` 用时间戳生成。
- `sessions` 只存在浏览器内存中，刷新页面会丢失。
- `messages` 是当前会话的前端消息数组。
- 后端短期记忆由 `user_id + session_id` 决定。

## 预设场景卡片

欢迎页提供 6 个快捷场景：

- 抑郁筛查。
- 双相鉴别。
- 精神病性症状。
- 强迫症状。
- 焦虑障碍。
- 药物审查。

点击卡片会直接调用：

```ts
sendQuery('预设病例文本')
```

## 请求后端

核心函数：

```ts
async function sendQuery(preset?: string) {
  const query = preset || inputMessage.value.trim()
  ...
  const response = await fetch('http://127.0.0.1:5000/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      query,
      user_id: userId.value,
      session_id: currentSessionId.value
    }),
  })
}
```

请求体：

```json
{
  "query": "患者近两周情绪低落、失眠、食欲下降",
  "user_id": "doctor_001",
  "session_id": "session_..."
}
```

## SSE 读取逻辑

后端返回的是 `text/event-stream`，前端用 reader 逐块读取：

```ts
const reader = response.body!.getReader()
const decoder = new TextDecoder()
```

解析逻辑：

1. 读取二进制 chunk。
2. 用 `TextDecoder` 转成字符串。
3. 按换行切分。
4. 找到 `data: ` 开头的行。
5. `JSON.parse(data)`。
6. 如果有 `content` 字段，追加到助手消息。

```ts
if (parsed.content) {
  messages.value[msgIdx].content += parsed.content
}
```

## Markdown 渲染

使用 `marked`：

```ts
function renderMarkdown(text: string) {
  return marked.parse(text, { breaks: true, gfm: true })
}
```

模板中使用：

```vue
<div v-html="renderMarkdown(msg.content)"></div>
```

注意：`v-html` 会渲染 HTML。如果未来接入真实外部内容，建议增加 HTML 清洗逻辑，防止 XSS。

## 样式文件

`src/assets/base.css`：

- Vue 默认主题变量。
- 亮色/暗色配色变量。
- 全局 box-sizing。
- body 字体和背景。

`src/assets/main.css`：

- 引入 `base.css`。
- 设置 `#app` 最大宽度、居中、padding。
- 定义链接样式。
- 在大屏幕下设置 body 居中和 `#app` 双列 grid。

当前 `App.vue` 里使用了很多类名，例如：

- `clinical-app`
- `brand`
- `session-list`
- `message-row`
- `message-bubble`
- `input-area`

如果这些类没有额外样式，页面主要依赖 Element Plus 默认样式和全局 CSS。后续可以将 `App.vue` 的业务结构和样式进一步拆分。

## 后端地址配置建议

当前后端地址写死为：

```text
http://127.0.0.1:5000/api/chat
```

学习阶段可以这样使用。后续更推荐用 Vite 环境变量：

```dotenv
VITE_API_BASE_URL=http://127.0.0.1:5000
```

然后在代码里使用：

```ts
const apiBaseUrl = import.meta.env.VITE_API_BASE_URL
```

这样开发、测试、生产可以使用不同后端地址。

## 常见问题

### 请求失败

前端会显示：

```text
请求失败，请检查后端服务是否启动。
```

检查：

- 后端是否运行在 5000 端口。
- 浏览器是否能访问 `http://127.0.0.1:5000`。
- 后端 CORS 是否允许当前前端地址。
- Docker 基础服务是否影响后端初始化。

### 页面没有样式或构建失败

检查：

- `src/assets/main.css` 是否存在。
- `src/assets/base.css` 是否存在。
- `main.ts` 中的 import 路径是否正确。

### Markdown 表格显示不理想

后端药物审查可能返回 Markdown 表格。可以在 CSS 中补充：

```css
.message-bubble table {
  border-collapse: collapse;
  width: 100%;
}

.message-bubble th,
.message-bubble td {
  border: 1px solid #ddd;
  padding: 6px 8px;
}
```
