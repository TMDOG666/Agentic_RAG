# Agentic RAG WebUI

Vue3 + Vite + Element Plus 前端。

## 开发

1. 安装依赖

```bash
npm i
```

2. 启动

```bash
npm run dev
```

默认会将 `/api/*` 代理到 `http://127.0.0.1:8080`。

如果你的 FastAPI 端口不同，可以在启动时设置环境变量：

- Windows PowerShell:

```powershell
$env:VITE_DEV_PROXY_TARGET='http://127.0.0.1:8000'; npm run dev
```

## 生产/预览

通过 `.env` 设置：

- `VITE_API_BASE_URL=http://127.0.0.1:8080`

然后：

```bash
npm run build
npm run preview
```
