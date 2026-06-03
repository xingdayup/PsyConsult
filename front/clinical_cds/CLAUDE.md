# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

临床决策支持系统（精神科）前端 — Vue 3 + TypeScript + Vite 单页应用，搭配 Python 后端（`127.0.0.1:5000`）提供 Multi-Agent 诊疗决策支持。

## 技术栈

- **框架**: Vue 3.5 + Composition API (`<script setup lang="ts">`)
- **构建**: Vite 8, TypeScript ~6.0
- **UI**: Element Plus 2.13 + `@element-plus/icons-vue`
- **其他**: `marked`（Markdown 渲染）, `axios`（HTTP，已安装但当前未用到）

## 常用命令

```bash
npm run dev          # 启动 Vite 开发服务器
npm run build        # 先 type-check 再构建
npm run build-only   # 仅 vite build（跳过 type-check）
npm run type-check   # vue-tsc --build 类型检查
npm run preview      # 预览构建产物
```

## 目录结构

```
src/
  main.ts          # 入口：挂载 Vue app + Element Plus + 全局 CSS
  App.vue          # 根组件，包含所有页面逻辑（单页应用，无路由）
  assets/
    base.css       # 全局 CSS reset 和变量
    main.css       # #app 容器样式 + 引入 base.css
  components/      # 子组件目录（当前为空）
dist/              # Vite 构建产物
```

## 架构要点

- **无路由**：整个应用是单文件（App.vue, ~820 行），没有 vue-router。所有 UI 状态通过本地 `ref` 管理。
- **三栏布局**：左侧工作区导航（会话列表 + 新建按钮）、中间主工作台（消息面板 + 输入框）、右侧信息面板（工作流阶段 + 知识源）。响应式断点 1180px / 820px。
- **路径别名**：`@/` 映射到 `src/`（vite.config.ts 和 tsconfig 中配置）。
- **聊天流**：POST `http://127.0.0.1:5000/api/chat`（JSON body: `{query, user_id, session_id}`），读取 SSE 流式响应（`text/event-stream`），每行 JSON `{content}` 增量追加到助手消息。
- **会话管理**：纯前端管理，`sessions` ref 数组，切换时清空消息列表，不持久化。
- **Element Plus** 已在 `main.ts` 全局注册，组件中直接使用 `<el-*>` 标签即可，图标从 `@element-plus/icons-vue` 按需导入。
- **样式方案**：Scoped CSS（`<style scoped>`），使用 `oklch()` 颜色空间，用 `:deep()` 穿透 Element Plus 组件内部样式。