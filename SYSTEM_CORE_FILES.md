# Autonomous Agent System - Core Files Documentation

**Generated:** 2025-10-20  
**Purpose:** Complete reference of all core files needed to run the autonomous multi-agent system

---

## Table of Contents

1. [System Entry Point](#system-entry-point)
2. [Phase 0: Task Classification](#phase-0-task-classification)
3. [Phase 1: Task Division](#phase-1-task-division)
4. [Phase 2: Task Execution](#phase-2-task-execution)
5. [Agent Generation System](#agent-generation-system)
6. [Knowledge & Memory Systems](#knowledge--memory-systems)
7. [Shared Infrastructure](#shared-infrastructure)
8. [Configuration Files](#configuration-files)
9. [File Dependency Graph](#file-dependency-graph)

---

## System Entry Point

### `control_plane_v2/run_control_plane.py`
**Purpose:** Main entry point for the entire system  
**Role:** Orchestrates all three phases (Classification -> Division -> Execution)

**Key Functions:**
- `main()` - Entry point that runs all phases sequentially
- `parse_manifest_connections()` - Parses database/file connections from manifest
- `clean_manifest_for_llms()` - Removes instruction fields before passing to LLMs
- `run_phase_0()` - Task classification phase
- `run_phase_1()` - Task division phase
- `run_phase_2()` - Task execution phase

**Dependencies:**
- Phase 0: `TaskClassifier`, `SideTaskSolver`, `SideTaskVerifier`
- Phase 1: `CollaborativeTaskDivider`
- Phase 2: `BossWorkerOrchestrator`
- Infrastructure: `WorkspaceManager`, `KnowledgeSystem`, `create_all_model_clients`

**Usage:**
```bash
python -m control_plane_v2.run_control_plane --manifest path/to/manifest.json
```

---

## Phase 0: Task Classification

**Purpose:** Understand the task, classify it, and handle side tasks (connection validation, credential checks)

### Core Files

#### `control_plane_v2/phase_0/task_classifier.py`
**Purpose:** Coordinates Claude and GPT-5 to collaboratively classify tasks  
**Agents Used:**
- `ClaudeTaskUnderstander` - Initial task analysis
- `GPT5TaskUnderstander` - Review and refinement
- `TaskNegotiator` - Resolves disagreements
- `OverseerAgent` - Final quality control

**Key Methods:**
- `classify_task()` - Main classification workflow
- Returns: `TaskClassification` with task type, complexity, requirements

#### `control_plane_v2/phase_0/side_task_solver.py`
**Purpose:** Handles side tasks like connection validation, credential checks  
**Key Methods:**
- `solve_all_tasks()` - Executes all side tasks
- Uses `AgentFactory` to generate specialized agents dynamically

#### `control_plane_v2/phase_0/side_task_verifier.py`
**Purpose:** Verifies side task results  
**Key Methods:**
- `verify_all_results()` - Validates side task outputs

### Supporting Files

#### `control_plane_v2/phase_0/messages.py`
**Purpose:** Message protocol for Phase 0  
**Key Classes:**
- `TaskAnalysisRequest` - Input to classifier
- `TaskClassification` - Output from classifier
- `TaskClassificationProposal` - Agent proposals
- `NegotiationResult` - Negotiation outcomes

#### `control_plane_v2/phase_0/models.py`
**Purpose:** Data models for Phase 0  
**Key Classes:**
- `FileInfo` - File metadata
- `ConnectionInfo` - Database connection details

#### `control_plane_v2/phase_0/task_understanders/`
**Purpose:** Individual agent implementations for task understanding

**Files:**
- `claude_understander.py` - Claude-based task analyzer
- `gpt5_understander.py` - GPT-5 based task reviewer
- `negotiation.py` - Negotiation agent for resolving conflicts
- `overseer.py` - Quality control agent

---

## Phase 1: Task Division

**Purpose:** Break down classified tasks into executable subtasks with dependencies

### Core Files

#### `control_plane_v2/phase_1/collaborative_divider_v2.py`
**Purpose:** Main task division orchestrator using Claude and GPT-5  
**Workflow:**
1. Claude proposes task division
2. GPT-5 reviews and refines
3. Negotiation if needed
4. Overseer validates final plan

**Key Methods:**
- `divide_task()` - Main division workflow
- Returns: `TaskDivisionResult` with subtasks and dependencies

#### `control_plane_v2/phase_1/task_divider.py`
**Purpose:** Core task division logic (used by collaborative divider)  
**Key Methods:**
- `divide()` - Analyzes task and creates subtask breakdown

### Supporting Files

#### `control_plane_v2/phase_1/messages.py`
**Purpose:** Message protocol for Phase 1  
**Key Classes:**
- `TaskDivisionRequest` - Input to divider
- `TaskDivisionResult` - Output with subtasks
- `Subtask` - Individual subtask definition

#### `control_plane_v2/phase_1/task_models.py`
**Purpose:** Data models for task division  
**Key Classes:**
- Task metadata models
- Dependency models

---

## Phase 2: Task Execution

**Purpose:** Execute subtasks using autonomous Boss-Worker agent pairs

### Core Files

#### `control_plane_v2/phase_2/orchestrator_boss_worker.py`
**Purpose:** Main orchestrator for Phase 2 execution  
**Workflow:**
1. Read execution plan from Phase 1
2. For each task:
   - Create Boss-Worker pair
   - Send `TaskMessage` to Boss
   - Wait for `TaskCompletionMessage`
   - Update catalog
3. Handle dependencies (sequential vs parallel)

**Key Methods:**
- `run()` - Main execution loop
- `_execute_task()` - Execute single task
- `_create_boss_worker_pair()` - Create agents for task

#### `control_plane_v2/phase_2/boss_agent_autonomous.py`
**Purpose:** Boss Agent (GPT-5) - Plans, delegates, verifies, adjusts  
**Model:** GPT-5 (o1-preview)

**Key Responsibilities:**
1. **Planning:** Break task into subtasks with `expected_outputs`
2. **Delegation:** Send `SubtaskMessage` to Worker
3. **Verification:** Generate and run verification code
4. **Adjustment:** Re-plan if verification fails

**Key Methods:**
- `_handle_task_message()` - Receives task from orchestrator
- `_plan_subtasks()` - Plans subtask breakdown
- `_delegate_subtask()` - Sends subtask to Worker
- `_verify_worker_output()` - Verifies Worker's results
- `_adjust_plan()` - Re-plans based on failures

**Critical Features:**
- Deep validation for reports (checks for placeholders, empty content)
- RAG-based context retrieval from previous tasks
- Dynamic re-planning capability

#### `control_plane_v2/phase_2/worker_agent_autonomous.py`
**Purpose:** Worker Agent (Claude 4.5) - Executes subtasks with retry loop  
**Model:** Claude 4.5 Sonnet

**Key Responsibilities:**
1. **Code Generation:** Generate Python code for subtask
2. **Execution:** Run code via `CodeExecutorAgent`
3. **Self-Verification:** Check if expected files created
4. **Retry:** Up to 15 attempts with learning from failures

**Key Methods:**
- `_handle_subtask_message()` - Receives subtask from Boss
- `_execute_with_retry()` - Main retry loop (15 attempts)
- `_verify_created_files()` - Checks expected outputs exist
- `_send_completion()` - Reports back to Boss

**Critical Features:**
- Incremental file generation across attempts
- Self-verification against `expected_outputs`
- Can "give up" if task deemed impossible

### Supporting Files

#### `control_plane_v2/phase_2/task_agent_messages.py`
**Purpose:** Message protocol for Boss-Worker communication  
**Key Classes:**
- `TaskMessage` - Orchestrator -> Boss
- `SubtaskMessage` - Boss -> Worker (includes `expected_outputs`)
- `SubtaskCompletionMessage` - Worker -> Boss
- `TaskCompletionMessage` - Boss -> Orchestrator

#### `control_plane_v2/phase_2/task_agent_tools.py`
**Purpose:** Tools available to Boss and Worker agents  
**Key Functions:**
- `scan_directory()` - Directory structure scanning
- `TaskAgentTools` class with:
  - `get_catalog_info()` - Query file catalog
  - `get_knowledge_context()` - Query RAG system
  - `execute_code()` - Code execution wrapper

#### `control_plane_v2/phase_2/rag_injector.py`
**Purpose:** Injects task outputs into RAG system for semantic search  
**Key Methods:**
- `inject_task_outputs()` - Add task results to vector store
- `inject_json_file()` - Parse and embed JSON files

#### `control_plane_v2/phase_2/task_agent_factory.py`
**Purpose:** Factory for creating Boss-Worker pairs  
**Key Methods:**
- `create_boss_worker_pair()` - Creates agents for a task
- `cleanup_agents()` - Cleanup after task completion

---

## Agent Generation System

**Purpose:** Dynamically generate specialized agents for side tasks

### Core Files

#### `control_plane_v2/agent_generator/factory.py`
**Purpose:** Main factory for agent lifecycle management  
**Key Methods:**
- `generate_agent()` - Generate new agent
- `execute_agent()` - Execute generated agent
- `cleanup_agent()` - Remove agent and workspace

#### `control_plane_v2/agent_generator/generator.py`
**Purpose:** Agent code generation using Claude 4.5  
**Key Methods:**
- `_handle_generation_request()` - Generate agent code
- Uses AutoGen patterns for code execution

#### `control_plane_v2/agent_generator/executor.py`
**Purpose:** Execute generated agents  
**Key Methods:**
- `execute()` - Run generated agent code

#### `control_plane_v2/agent_generator/verifier.py`
**Purpose:** Verify agent execution results  
**Key Methods:**
- `verify()` - Validate agent outputs

### Supporting Files

#### `control_plane_v2/agent_generator/messages.py`
**Purpose:** Message protocol for agent generation  
**Key Classes:**
- `AgentGenerationRequest`
- `AgentGenerationResult`
- `AgentExecutionRequest`
- `AgentExecutionResult`

#### `control_plane_v2/agent_generator/model_clients.py`
**Purpose:** Create LLM clients for all models  
**Key Functions:**
- `create_all_model_clients()` - Returns dict of all model clients
  - `claude_sonnet` - Claude 4.5 Sonnet
  - `gpt5` - GPT-5 (o1-preview)
  - `gpt4` - GPT-4 Turbo

#### `control_plane_v2/agent_generator/model_selector.py`
**Purpose:** Select appropriate model for tasks  
**Key Methods:**
- `select_model()` - Choose best model for task type

---

## Knowledge & Memory Systems

**Purpose:** Store, retrieve, and query task execution history and data artifacts

### Core Files

#### `control_plane_v2/knowledge_system.py`
**Purpose:** Unified interface for catalog + RAG memory  
**Key Methods:**
- `register_file()` - Add file to catalog
- `register_task_summary()` - Store task results
- `query_knowledge()` - Semantic search over history
- `get_file_info()` - Retrieve file metadata

**Integrates:**
- `DataCatalog` - Structured metadata
- `AzureOpenAIRAGMemory` - Semantic search

#### `control_plane_v2/data_catalog.py`
**Purpose:** Structured catalog of all data artifacts  
**Key Methods:**
- `register_file()` - Add file with metadata
- `get_file_by_id()` - Retrieve file info
- `get_files_by_task()` - Get all files from task
- `get_task_summary()` - Get task results

**Stores:**
- File paths, schemas, checksums
- Task lineage and dependencies
- Task summaries and learnings

#### `control_plane_v2/azure_openai_rag_memory.py`
**Purpose:** RAG system using Azure OpenAI embeddings + ChromaDB  
**Key Methods:**
- `add_learning()` - Store task learning
- `query()` - Semantic search
- `add_task_output()` - Index task results

**Uses:**
- Azure OpenAI `text-embedding-ada-002`
- ChromaDB for vector storage

#### `control_plane_v2/rag_memory.py`
**Purpose:** Alternative RAG implementation (local embeddings)  
**Note:** Currently not used; system uses Azure OpenAI version

---

## Shared Infrastructure

### Core Files

#### `control_plane_v2/workspace_manager.py`
**Purpose:** Manages hierarchical workspace structure  
**Directory Structure:**
```
runs/
  run_YYYYMMDD_HHMMSS/
    phase0/
      classification_result.json
      side_tasks/
    phase1/
      execution_plan.json
    phase2/
      task_1_name/
        outputs/
        task_files.json
      task_2_name/
        outputs/
        task_files.json
    file_catalog.json
    vectordb/
```

**Key Methods:**
- `create_run()` - Create new run directory
- `get_phase_dir()` - Get phase directory
- `get_task_dir()` - Get task workspace
- `copy_user_files()` - Copy input files to workspace

#### `control_plane_v2/bedrock_client.py`
**Purpose:** AWS Bedrock client wrapper  
**Note:** Currently not actively used; system uses Azure OpenAI

### Supporting Files

#### `control_plane_v2/shared/models.py`
**Purpose:** Shared data models across phases  
**Key Classes:**
- Common Pydantic models used by multiple phases

#### `control_plane_v2/utils/__init__.py`
**Purpose:** Utility functions  
**Note:** Currently minimal; utilities are distributed across modules

---

## Configuration Files

### Required Configuration

#### `env_info.json` (Root directory)
**Purpose:** Environment configuration with LLM credentials  
**Required Fields:**
```json
{
  "azure_openai": {
    "endpoint": "https://your-endpoint.openai.azure.com/",
    "api_key": "your-api-key",
    "api_version": "2024-02-15-preview",
    "deployments": {
      "gpt4": "gpt-4-turbo",
      "gpt5": "o1-preview",
      "claude_sonnet": "claude-sonnet-4-5"
    }
  },
  "anthropic": {
    "api_key": "your-anthropic-key"
  }
}
```

#### Manifest File (User-provided)
**Purpose:** Task definition and configuration  
**Required Fields:**
```json
{
  "task_name": "Task description",
  "input_data": {
    "primary_file": "path/to/file",
    "connections": []
  },
  "transformation_config": {
    "skip_side_tasks": false,
    "mapping_plan_path": "optional/path"
  },
  "user_uploads": [
    {
      "source": "path/to/source",
      "target_filename": "filename_in_workspace"
    }
  ],
  "output_requirements": {
    "format": "json/csv/html",
    "quality_level": "high"
  }
}
```

### Optional Configuration

#### `control_plane_v2/requirements_rag.txt`
**Purpose:** Python dependencies for RAG system  
**Key Packages:**
- `chromadb` - Vector database
- `openai` - Azure OpenAI client
- `autogen-core` - AutoGen framework
- `autogen-ext` - AutoGen extensions
- `pydantic` - Data validation

---

## File Dependency Graph

### Phase Flow
```
run_control_plane.py
  |
  +-- Phase 0: Classification
  |     |
  |     +-- task_classifier.py
  |     |     +-- claude_understander.py
  |     |     +-- gpt5_understander.py
  |     |     +-- negotiation.py
  |     |     +-- overseer.py
  |     |
  |     +-- side_task_solver.py
  |     |     +-- agent_generator/factory.py
  |     |           +-- generator.py
  |     |           +-- executor.py
  |     |           +-- verifier.py
  |     |
  |     +-- side_task_verifier.py
  |
  +-- Phase 1: Division
  |     |
  |     +-- collaborative_divider_v2.py
  |           +-- task_divider.py
  |
  +-- Phase 2: Execution
        |
        +-- orchestrator_boss_worker.py
              |
              +-- task_agent_factory.py
              |     +-- boss_agent_autonomous.py
              |     |     +-- task_agent_tools.py
              |     |     +-- rag_injector.py
              |     |     +-- knowledge_system.py
              |     |
              |     +-- worker_agent_autonomous.py
              |           +-- task_agent_tools.py
              |           +-- rag_injector.py
              |           +-- knowledge_system.py
              |
              +-- knowledge_system.py
                    +-- data_catalog.py
                    +-- azure_openai_rag_memory.py
```

### Infrastructure Dependencies
```
All Phases depend on:
  - workspace_manager.py (Directory management)
  - agent_generator/model_clients.py (LLM clients)
  - knowledge_system.py (Data tracking)

Phase 2 additionally depends on:
  - data_catalog.py (File metadata)
  - azure_openai_rag_memory.py (Semantic search)
  - rag_injector.py (Embedding generation)
```

---

## Critical Files Summary

### Must Have (System Won't Run Without These)

**Entry Point:**
1. `control_plane_v2/run_control_plane.py`

**Phase 0 (8 files):**
2. `control_plane_v2/phase_0/task_classifier.py`
3. `control_plane_v2/phase_0/side_task_solver.py`
4. `control_plane_v2/phase_0/side_task_verifier.py`
5. `control_plane_v2/phase_0/messages.py`
6. `control_plane_v2/phase_0/models.py`
7. `control_plane_v2/phase_0/task_understanders/claude_understander.py`
8. `control_plane_v2/phase_0/task_understanders/gpt5_understander.py`
9. `control_plane_v2/phase_0/task_understanders/negotiation.py`
10. `control_plane_v2/phase_0/task_understanders/overseer.py`

**Phase 1 (4 files):**
11. `control_plane_v2/phase_1/collaborative_divider_v2.py`
12. `control_plane_v2/phase_1/task_divider.py`
13. `control_plane_v2/phase_1/messages.py`
14. `control_plane_v2/phase_1/task_models.py`

**Phase 2 (8 files):**
15. `control_plane_v2/phase_2/orchestrator_boss_worker.py`
16. `control_plane_v2/phase_2/boss_agent_autonomous.py`
17. `control_plane_v2/phase_2/worker_agent_autonomous.py`
18. `control_plane_v2/phase_2/task_agent_factory.py`
19. `control_plane_v2/phase_2/task_agent_messages.py`
20. `control_plane_v2/phase_2/task_agent_tools.py`
21. `control_plane_v2/phase_2/rag_injector.py`
22. `control_plane_v2/phase_2/orchestrator_phase2_v2.py` (for FileCatalog, SimpleVectorStore)

**Agent Generation (6 files):**
23. `control_plane_v2/agent_generator/factory.py`
24. `control_plane_v2/agent_generator/generator.py`
25. `control_plane_v2/agent_generator/executor.py`
26. `control_plane_v2/agent_generator/verifier.py`
27. `control_plane_v2/agent_generator/messages.py`
28. `control_plane_v2/agent_generator/model_clients.py`
29. `control_plane_v2/agent_generator/model_selector.py`

**Knowledge Systems (3 files):**
30. `control_plane_v2/knowledge_system.py`
31. `control_plane_v2/data_catalog.py`
32. `control_plane_v2/azure_openai_rag_memory.py`

**Infrastructure (2 files):**
33. `control_plane_v2/workspace_manager.py`
34. `control_plane_v2/shared/models.py`

**Configuration (2 files):**
35. `env_info.json` (root directory)
36. User manifest file (e.g., `manifest_genomics_deep_analysis.json`)

**Total Core Files: 36 files**

---

## File Size Estimates

**Small (<100 lines):**
- All `messages.py` files
- All `models.py` files
- `__init__.py` files

**Medium (100-500 lines):**
- Most agent implementations
- Tool files
- Utility files

**Large (500-1000 lines):**
- `run_control_plane.py` (~733 lines)
- `boss_agent_autonomous.py` (~985 lines)
- `worker_agent_autonomous.py` (~892 lines)
- `orchestrator_boss_worker.py` (~457 lines)

---

## Execution Flow Summary

1. **User runs:** `python -m control_plane_v2.run_control_plane --manifest manifest.json`

2. **Phase 0 (Classification):**
   - `TaskClassifier` analyzes task using Claude + GPT-5
   - `SideTaskSolver` validates connections/credentials
   - Output: `classification_result.json`

3. **Phase 1 (Division):**
   - `CollaborativeTaskDivider` breaks task into subtasks
   - Identifies dependencies (sequential vs parallel)
   - Output: `execution_plan.json`

4. **Phase 2 (Execution):**
   - `BossWorkerOrchestrator` reads execution plan
   - For each task:
     - Creates Boss (GPT-5) + Worker (Claude 4.5) pair
     - Boss plans subtasks with `expected_outputs`
     - Worker executes with retry loop (up to 15 attempts)
     - Boss verifies outputs with deep validation
     - Results stored in `task_files.json` and catalog
   - Output: Task-specific outputs + `file_catalog.json`

5. **Knowledge Accumulation:**
   - All outputs indexed in `DataCatalog`
   - Task learnings embedded in `AzureOpenAIRAGMemory`
   - Future tasks query this knowledge for context

---

## Key Design Patterns

### 1. Message-Based Communication
- All agent interactions use Pydantic message classes
- Type-safe, structured communication
- Easy to debug and log

### 2. Autonomous Retry Loops
- Worker has 15 attempts to complete subtask
- Boss can re-delegate if verification fails
- System learns from failures

### 3. Explicit Expected Outputs
- Boss specifies exact files Worker must create
- Worker verifies against this list
- Prevents false success claims

### 4. Deep Validation
- Boss generates custom verification code
- Checks for placeholders, empty content, data quality
- Ensures high-quality outputs

### 5. RAG-Based Context
- Previous task outputs embedded and searchable
- Agents query for relevant context
- Enables learning across runs

### 6. Hierarchical Workspace
- Clean separation: run -> phase -> task
- Easy to debug and inspect
- Supports parallel execution

---

## Notes

- **Windows Compatibility:** System uses `WindowsProactorEventLoopPolicy` for AutoGen code execution
- **LLM Models:** 
  - Boss: GPT-5 (o1-preview) for planning and verification
  - Worker: Claude 4.5 Sonnet for code generation
  - Side tasks: Dynamically selected based on task type
- **Vector Store:** Azure OpenAI embeddings + ChromaDB
- **Code Execution:** AutoGen's `LocalCommandLineCodeExecutor` with 30-minute timeout
- **Max Retries:** Worker attempts up to 15 times, Boss can re-delegate indefinitely

---

## Troubleshooting

### Common Issues

1. **Missing env_info.json**
   - System will fail immediately
   - Ensure all API keys are valid

2. **ChromaDB not available**
   - RAG functionality will be limited
   - Install: `pip install chromadb`

3. **Code execution timeout**
   - Default: 30 minutes (1800 seconds)
   - Adjust in `worker_agent_autonomous.py` line 47

4. **Worker claiming success prematurely**
   - Check `expected_outputs` in Boss's subtask planning
   - Verify `_verify_created_files()` implementation

5. **Boss rejecting valid outputs**
   - Check Boss's verification code generation
   - Ensure it only checks `expected_outputs`

---

## Future Enhancements

1. **Parallel Task Execution**
   - Currently sequential within each package
   - Could parallelize independent tasks

2. **Dynamic Model Selection**
   - Currently hardcoded (Boss=GPT-5, Worker=Claude)
   - Could select based on task complexity

3. **Incremental Checkpointing**
   - Save state after each subtask
   - Resume from failure point

4. **Cost Tracking**
   - Log token usage per task
   - Optimize expensive operations

5. **Web UI**
   - Real-time progress monitoring
   - Interactive debugging

---

**End of Documentation**

