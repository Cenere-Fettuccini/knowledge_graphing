# Step 6: Tool Execution (LangGraph Agent Actions)

**Status**: Planning Complete / Implementation Pending
**Context**: We have finished the persistence layer (ChromaDB + Neo4j). The next step is to upgrade the Agent from a simple loop into a LangGraph `StateGraph`.

## Planned Architecture
1. **User input** -> Context retrieval.
2. **`call_model` node**: Gemini decides if it needs a tool.
3. **Router**: Routes to `execute_tools` node or `__end__`.
4. **`execute_tools` node**: Runs the tool and loops back to `call_model`.

## Immediate Tasks
1. Create `src/core/state.py` for the Agent state.
2. Create `src/core/tools/` registry.
3. Build the first tool: `get_current_time`.
4. Refactor `src/core/agent.py` to use `StateGraph`.

---
*Note: This file serves as a checkpoint to resume from Step 6.*
