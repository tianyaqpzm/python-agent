import asyncio
import logging
import sys
from app.core.database import engine, init_db
from app.core.config import settings
from psycopg_pool import AsyncConnectionPool
from app.agent.factory import get_graph_runnable
from langchain_core.messages import HumanMessage

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


async def verify():
    print("Verifying Unified Driver Implementation...")
    lg_pool = None
    try:
        # 1. Initialize DB Tables
        await init_db()

        # 2. Setup Pool for LangGraph
        pg_uri = str(settings.DB_URI).replace("+asyncpg", "").replace("+psycopg", "")
        lg_pool = AsyncConnectionPool(
            conninfo=pg_uri, max_size=1, kwargs={"autocommit": True}
        )
        await lg_pool.open()

        # 3. Get Runnable & Invoke
        async with lg_pool.connection() as conn:
            # This will internally assert that db_manager.langgraph_pool is ready
            graph = await get_graph_runnable(conn)
            print("Graph runnable obtained.")

            # 4. Invoke Graph
            print("Invoking graph...")
            config = {"configurable": {"thread_id": "verify_unified_1"}}
            input_message = HumanMessage(content="Hello, unified world!")

            final_response = ""
            async for event in graph.astream_events(
                {"messages": [input_message]}, config, version="v1"
            ):
                kind = event["event"]
                if kind == "on_chain_end":
                    if event["name"] == "agent":
                        output_messages = event["data"]["output"]["messages"]
                        if output_messages:
                            ai_message = output_messages[-1]
                            final_response = ai_message.content
                            print(f"AI Response: {final_response}")

            if "Echo: Hello, unified world!" in final_response:
                print("SUCCESS: Graph returned expected response.")
            else:
                print(f"FAILURE: Unexpected response: {final_response}")

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback

        traceback.print_exc()
    finally:
        if lg_pool:
            await lg_pool.close()
        await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(verify())
    except KeyboardInterrupt:
        pass
