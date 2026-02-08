---
title: Python-Agent
emoji: 🤖
colorFrom: blue
colorTo: green
sdk: gradio
app_file: app.py  # <--- 添加这一行，指定启动文件
pinned: false
---


# Python Agent

A modular Python-based AI agent service built with FastAPI, integrating **Nacos** for service discovery and **Model Context Protocol (MCP)** for extensible tool usage. This agent uses **LangGraph** to orchestrate agentic workflows.

## Features

- **FastAPI Framework**: High-performance, easy-to-learn web framework.
- **Service Discovery**: Seamless integration with Nacos for service registration and discovery.
- **LangGraph**: Stateful, multi-actor applications with cycles (agentic orchestration).
- **Model Context Protocol (MCP)**:
    - **Stdio Client**: Connects to local CLI tools (e.g., Brave Search via Node.js).
    - **SSE Client**: Connects to remote services (e.g., Java backend) via Server-Sent Events.

## Prerequisites

- **Python 3.10+**
- **Node.js**: Required for running the Brave Search MCP server (`npx`).
- **Nacos Server 2.x**: A running Nacos instance is required for the application to start.

## Installation

1. Clone the repository:
   ```bash
   git clone <repository_url>
   cd python-agent
   ```

2. Create and activate a virtual environment:
   ```bash
   python -m venv .venv
   # Windows
   .venv\Scripts\activate
   # Linux/Mac
   source .venv/bin/activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Configuration

The application is configured via environment variables. You can create a `.env` file in the root directory (see `.env.example`).

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_ENV` | `development` | Application environment (`development` or `production`). |
| `HOST` | `0.0.0.0` | Host to bind the server to. |
| `PORT` | `8181` | Port to listen on. |
| `NACOS_SERVER_ADDR` | `` | Address of the Nacos server. |
| `NACOS_NAMESPACE` | `public` | Nacos namespace ID. |
| `NACOS_USERNAME` | `` | Nacos username. |
| `NACOS_PASSWORD` | `` | Nacos password. |
| `SERVICE_NAME` | `python-agent` | Name of this service in Nacos. |
| `MCP_BRAVE_PATH` | (Auto-detected) | Optional override for `npx` path. |
| `NACOS_GATEWAY_SERVICE_NAME` | `gateway` | Name of the Java/Gateway service to discover. |

## Usage

### Running the Application

Using `python`:
```bash
python main.py
```

Using `uvicorn` (with hot reload):
```bash
uvicorn main:app --reload --port 8181
```

> **Note**: The application will fail to start if it cannot connect to the configured Nacos server.

### API Endpoints

- **Health Check**: `GET /health`
- **Chat**: `POST /chat`
    ```json
    {
      "message": "Search for the latest news on AI."
    }
    ```

## Project Structure

The project follows a modular package structure:

```text
python-agent/
├── app/
│   ├── core/           # Core configuration & infrastructure (Nacos, Config)
│   ├── services/       # External service clients (MCP)
│   ├── agent/          # LangGraph logic (State, Graph, Nodes)
│   └── setup.py        # Startup setup scripts
├── main.py             # Entry point
└── ...
```
