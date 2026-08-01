# AiSync Web

此压缩包已经包含构建后的前端页面，运行时不需要安装 Node.js 或 npm。

## 环境要求

- Windows
- Python 3.11 或更高版本
- 首次安装后端依赖时需要联网

## 启动

在解压后的目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

首次启动会在当前目录创建 `.venv` 并安装后端依赖。完成后访问：

```text
http://127.0.0.1:27631
```

以后启动会复用 `.venv`，不需要重新安装依赖。

## 可选命令

只安装依赖：

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

安装 Chroma 向量后端：

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1 -WithChroma
```

使用其他端口：

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1 -Port 28631
```

允许局域网访问：

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1 -Lan
```

局域网模式当前没有登录或鉴权，只应在可信网络使用。
