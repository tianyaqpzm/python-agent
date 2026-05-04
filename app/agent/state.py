from typing import TypedDict, Annotated, List, Optional, Dict, Any
from langchain_core.messages import BaseMessage
import operator

class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], operator.add]
    topic_id: Optional[str]
    context: Optional[str]
    current_step: Optional[str]
    tool_outputs: Dict[str, Any]
