import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.types import CallToolRequestParams

# Java 服务的地址 (注意：/mcp/sse 是你在 Java Controller 定义的 endpoint)
# 如果你是 Docker 部署，请确保这里能访问到 Java 容器
JAVA_MCP_URL = "http://localhost:8080/mcp/sse"

async def run_test():
    print(f"🔌 正在连接 Java MCP Server: {JAVA_MCP_URL} ...")
    
    try:
        # 1. 建立 SSE 连接
        async with sse_client(JAVA_MCP_URL) as (read, write):
            # 2. 建立 MCP 会话 (握手)
            async with ClientSession(read, write) as session:
                await session.initialize()
                print("✅ 握手成功 (Initialize)")

                # 3. 列出可用工具 (List Tools)
                tools_result = await session.list_tools()
                print(f"\n🛠️  Java 端暴露了 {len(tools_result.tools)} 个工具:")
                for tool in tools_result.tools:
                    print(f"   - {tool.name}: {tool.description}")

                # 4. 发起工具调用 (Call Tool)
                tool_name = "query_order"
                test_args = {"orderId": "CN-8888"}
                
                print(f"\n🚀 正在调用工具 [{tool_name}] 参数: {test_args} ...")
                
                result = await session.call_tool(
                    name=tool_name,
                    arguments=test_args
                )

                # 5. 解析结果
                print("\n📩 Java 返回结果:")
                for content in result.content:
                    if content.type == 'text':
                        print(f"   >> {content.text}")
                    else:
                        print(f"   >> (非文本数据) {content}")

    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        print("💡 提示：请检查 Java 服务是否启动，以及 URL 是否正确。")

if __name__ == "__main__":
    asyncio.run(run_test())