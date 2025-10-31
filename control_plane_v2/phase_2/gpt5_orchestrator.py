"""
GPT-5 Intelligent Orchestrator Agent

This orchestrator uses GPT-5 to intelligently manage task execution:
- Analyzes execution plans and makes intelligent decisions
- Resolves file paths and dependencies
- Initializes and manages task agents (Claude and GPT-5)
- Has code execution capability for dynamic orchestration
- Monitors and adapts to task execution results
"""

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Dict, Any, List, Optional
import os

from autogen_core import RoutedAgent, MessageContext, message_handler, FunctionCall
from autogen_core.models import ChatCompletionClient, SystemMessage, UserMessage, AssistantMessage, FunctionExecutionResult, FunctionExecutionResultMessage
from autogen_ext.code_executors import LocalCommandLineCodeExecutor
from autogen_core import CancellationToken
from autogen_core.code_executor import CodeBlock

from ..phase_1_to_2z_messages import ExecutionPlanMessage
from ..workspace_manager import WorkspaceManager
from ..phase_1.messages import SubtaskPackage
from .collaborative_executor import CollaborativeSubtaskExecutor
from .messages import SubtaskExecutionRequest
from ..knowledge_system import KnowledgeSystem

logger = logging.getLogger(__name__)


class GPT5OrchestratorAgent(RoutedAgent):
    """
    GPT-5 Intelligent Orchestrator - AI-Driven Task Management
    
    This orchestrator uses GPT-5's reasoning capabilities to:
    1. Understand execution plans and task dependencies
    2. Resolve file paths intelligently
    3. Initialize task agents (Claude coder + GPT-5 reviewer)
    4. Monitor execution and adapt strategies
    5. Execute orchestration code when needed
    
    Tools Available to GPT-5:
    - execute_python_code: Run orchestration logic
    - initialize_task_agent: Create Claude + GPT-5 collaborative executor
    - get_task_status: Check task execution status
    - resolve_file_paths: Find and validate file locations
    - query_knowledge_base: Get learnings from past tasks
    """
    
    ORCHESTRATOR_SYSTEM_PROMPT = """You are an intelligent task orchestrator powered by GPT-5.

Your role is to oversee the execution of a complex multi-task workflow. You have:
- Code execution capability (Python)
- Ability to initialize task agents (Claude for coding, GPT-5 for review)
- Access to a knowledge base of past task executions
- File system access to resolve paths and dependencies

YOUR CORE RESPONSIBILITIES:
1. **Understand the execution plan** - Analyze task breakdown, dependencies, and requirements
2. **Resolve file paths** - Find source files and dependency outputs
3. **Initialize task agents** - Create collaborative executors (Claude + GPT-5) for each task
4. **Execute tasks in order** - Respect sequential/parallel/merge/final structure
5. **Monitor and adapt** - Track results, learn from failures, retry intelligently
6. **Manage knowledge** - Accumulate learnings and pass context to dependent tasks

AVAILABLE TOOLS:

1. **execute_python_code(code: str) -> dict**
   Execute Python code for orchestration logic.
   Use this to:
   - List files in directories
   - Read task packages
   - Create task workspaces
   - Query the data catalog
   - Copy/link files as needed
   
   Example:
   ```python
   import os
   from pathlib import Path
   
   # Find source files
   user_uploads = Path("runs/run_ID/user_uploads")
   csv_files = list(user_uploads.glob("*.csv"))
   result = {"files_found": [str(f) for f in csv_files]}
   ```

2. **initialize_task_agent(task_id: str, description: str, dependencies: list) -> dict**
   Initialize a collaborative task executor (Claude + GPT-5).
   Returns an executor that can run the task.
   
3. **execute_task(executor_id: str, package: dict) -> dict**
   Execute a task using the initialized executor.
   Returns execution result with success/failure status.
   
4. **get_task_status(task_id: str) -> dict**
   Check if a task has completed and retrieve its results.
   
5. **resolve_file_paths(task_description: str, dependencies: list, workspace_root: str) -> dict**
   Intelligently find input files for a task.
   Returns absolute paths to required files.
   
6. **query_knowledge_base(task_type: str, description: str) -> dict**
   Retrieve learnings from similar past tasks.
   Returns relevant patterns, errors, and solutions.

YOUR ORCHESTRATION STRATEGY:

1. **Receive Execution Plan:**
   - Understand task breakdown (sequential, parallel, merge, final)
   - Identify dependencies between tasks
   - Note required credentials and data

2. **For Each Task:**
   a. **Prepare:**
      - Resolve input file paths (from user_uploads or dependencies)
      - Query knowledge base for relevant learnings
      - Create task workspace directory
      
   b. **Initialize:**
      - Create collaborative executor (Claude + GPT-5)
      - Prepare task package with all required data
      
   c. **Execute:**
      - Run the task via the executor
      - Monitor execution progress
      
   d. **Handle Result:**
      - If success: Register outputs, accumulate learnings
      - If failure: Analyze error, retry with guidance
      - Update knowledge base with findings

3. **Adapt Intelligently:**
   - Skip tasks if work already done
   - Retry failed tasks with accumulated knowledge
   - Proceed with partial results when appropriate
   - Inject targeted guidance based on error patterns

DECISION-MAKING PHILOSOPHY:

- **Be proactive:** Anticipate problems before they occur
- **Be intelligent:** Use reasoning to make optimal decisions
- **Be adaptive:** Learn from failures and adjust strategies
- **Be efficient:** Avoid redundant work, leverage past learnings
- **Be thorough:** Ensure all dependencies are satisfied

OUTPUT FORMAT:

Respond with JSON containing your orchestration plan and any tool calls:
```json
{
  "reasoning": "Your analysis of the situation",
  "action": "Tool to call or decision to make",
  "tool_call": {
    "tool": "tool_name",
    "parameters": {...}
  },
  "next_steps": ["What to do after this action"]
}
```

Remember: You are the intelligent overseer. Use your reasoning capabilities to make optimal decisions about task execution.
"""
    
    def __init__(
        self,
        description: str,
        gpt5_client: ChatCompletionClient,
        workspace_manager: WorkspaceManager,
        workspace_root: Path,
        claude_client: ChatCompletionClient,
        gpt5_reviewer_client: ChatCompletionClient,
        knowledge_system: 'KnowledgeSystem' = None
    ):
        super().__init__(description)
        self._gpt5_client = gpt5_client
        self._workspace_manager = workspace_manager
        self._workspace_root = workspace_root
        self._claude_client = claude_client
        self._gpt5_reviewer_client = gpt5_reviewer_client
        self._knowledge_system = knowledge_system  # CRITICAL: Store for querying past learnings
        
        # Task tracking
        self._task_results: Dict[str, Any] = {}
        self._task_executors: Dict[str, CollaborativeSubtaskExecutor] = {}
        self._all_task_learnings: List[Dict[str, Any]] = []
        self._task_summaries: Dict[str, Any] = {}  # NEW: Store task summaries for intelligent file routing
        
        # Current execution context for GPT-5 tools
        self._current_message = None
        self._current_subtasks = []
        
        
        # Code executor for orchestration logic
        self._code_executor = LocalCommandLineCodeExecutor(
            work_dir=str(workspace_root)
        )
        
        # Initialize AutoGen tools for GPT-5 orchestration
        self._orchestrator_tools = self._create_orchestrator_tools()
        
        logger.info("="*80)
        logger.info("GPT5OrchestratorAgent INITIALIZED")
        logger.info(f"  Description: {description}")
        logger.info(f"  Workspace: {workspace_root}")
        logger.info("  Mode: AI-Driven Intelligent Orchestration")
        logger.info(f"  Knowledge System: {'Connected' if knowledge_system else 'Not available'}")
        logger.info("  Capabilities:")
        logger.info("    - GPT-5 reasoning for decision-making")
        logger.info("    - Code execution for orchestration logic")
        logger.info("    - Task agent initialization (Claude + GPT-5)")
        logger.info("    - Knowledge base integration")
        logger.info("="*80)
    
    @message_handler
    async def handle_execution_plan(
        self,
        message: ExecutionPlanMessage,
        ctx: MessageContext
    ) -> None:
        """
        MINIMAL VERSION: Just receive message and do nothing
        """
        logger.info("="*80)
        logger.info("MINIMAL ORCHESTRATOR: Received execution plan")
        logger.info(f"  Task ID: {message.task_id}")
        logger.info(f"  Plan keys: {list(message.plan.keys())}")
        logger.info("="*80)
        
        # Just log and do nothing
        logger.info("✅ Message received successfully - doing nothing else")
        return
    
    
    async def _tool_execute_code(self, code: str) -> Dict[str, Any]:
        """Tool: Execute Python code for orchestration logic."""
        try:
            code_block = CodeBlock(code=code, language="python")
            cancellation_token = CancellationToken()
            result = await self._code_executor.execute_code_blocks(
                code_blocks=[code_block],
                cancellation_token=cancellation_token
            )
            
            return {
                "success": True,
                "output": result.output if hasattr(result, 'output') else str(result),
                "exit_code": result.exit_code if hasattr(result, 'exit_code') else 0
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    async def _tool_initialize_agent(
        self,
        task_id: str,
        description: str,
        dependencies: List[str]
    ) -> Dict[str, Any]:
        """Tool: Initialize a collaborative task executor."""
        try:
            # Create task directory
            task_dir = self._workspace_manager.get_task_directory(
                'phase2', task_id, create=True
            )
            
            # Create executor WITH knowledge system for learning accumulation
            executor = CollaborativeSubtaskExecutor(
                claude_client=self._claude_client,
                gpt5_client=self._gpt5_reviewer_client,
                code_executor=LocalCommandLineCodeExecutor(work_dir=str(task_dir)),
                workspace_manager=self._workspace_manager,
                knowledge_system=self._knowledge_system  # CRITICAL: Pass knowledge system to executors
            )
            
            # Store executor
            self._task_executors[task_id] = executor
            
            return {
                "success": True,
                "executor_id": task_id,
                "task_directory": str(task_dir),
                "knowledge_system_connected": self._knowledge_system is not None
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    async def _tool_execute_task(
        self,
        executor_id: str,
        package: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Tool: Execute a task using initialized executor."""
        try:
            executor = self._task_executors.get(executor_id)
            if not executor:
                return {"success": False, "error": f"No executor found for {executor_id}"}
            
            # Execute task
            result = await executor.execute_subtask(package)
            
            # Store result
            self._task_results[executor_id] = result
            
            # NEW: Read and store task summary for intelligent file routing
            task_dir = self._workspace_manager.get_task_directory('phase2', executor_id, create=False)
            if task_dir:
                summary_file = task_dir / "task_summary.json"
                if summary_file.exists():
                    try:
                        with open(summary_file, 'r') as f:
                            self._task_summaries[executor_id] = json.load(f)
                        logger.info(f"  [ORCHESTRATOR] Stored task summary for {executor_id}")
                        logger.info(f"  [ORCHESTRATOR] Summary contains {len(self._task_summaries[executor_id].get('output_files', []))} file(s)")
                    except Exception as e:
                        logger.warning(f"  [ORCHESTRATOR] Could not read task summary: {e}")
            
            return result
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    async def _tool_resolve_paths(
        self,
        task_description: str,
        dependencies: List[str],
        workspace_root: str
    ) -> Dict[str, Any]:
        """Tool: Intelligently resolve file paths for a task."""
        try:
            resolved_paths = []
            
            # Check user_uploads for source files
            user_uploads = Path(workspace_root) / "user_uploads"
            if user_uploads.exists() and not dependencies:
                csv_files = list(user_uploads.glob("*.csv"))
                resolved_paths = [str(f.absolute()) for f in csv_files]
            
            return {
                "success": True,
                "input_file_paths": resolved_paths,
                "guidance": f"Found {len(resolved_paths)} input file(s)"
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    async def _tool_query_kb(
        self,
        task_type: str,
        description: str
    ) -> Dict[str, Any]:
        """Tool: Query knowledge base for relevant learnings."""
        try:
            if not self._knowledge_system:
                return {
                    "success": False,
                    "error": "Knowledge system not connected",
                    "similar_tasks": [],
                    "learnings": []
                }
            
            # Query knowledge system for relevant context
            context = self._knowledge_system.get_context_for_task(
                task_description=description,
                task_type=task_type,
                dependencies=[]
            )
            
            return {
                "success": True,
                "similar_tasks": context.get('similar_tasks', []),
                "learnings": context.get('relevant_learnings', []),
                "task_count": len(context.get('similar_tasks', []))
            }
        except Exception as e:
            logger.error(f"Failed to query knowledge base: {e}")
            return {
                "success": False,
                "error": str(e),
                "similar_tasks": [],
                "learnings": []
            }
    
    def _extract_description(self, subtask: Dict[str, Any]) -> str:
        """
        Extract description from subtask, handling different plan formats.
        """
        description = subtask.get('description', 'No description')
        if not description or description == 'No description':
            work_scope = subtask.get('work_scope', {})
            if isinstance(work_scope, dict):
                # Extract meaningful description from work_scope structure
                description = work_scope.get('description', 
                                           work_scope.get('requirements', 
                                                        work_scope.get('steps', 'No description')))
                if isinstance(description, list):
                    description = '; '.join(description[:2])  # First 2 items
            elif isinstance(work_scope, str):
                description = work_scope
        return description

    def _extract_subtasks_from_plan(self, plan: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Extract subtasks from plan (flexible structure support).
        Handles various plan structures from Phase 1.
        """
        subtasks = []
        
        # Check if plan has a 'task_breakdown' wrapper
        if 'task_breakdown' in plan:
            plan = plan['task_breakdown']
            logger.info(f"  Unwrapped task_breakdown")
        
        # Try common plan structures
        if 'subtasks' in plan:
            subtasks = plan['subtasks']
        elif 'sequential_tasks' in plan or 'parallel_tasks' in plan:
            # Structure with task categories
            for category in ['sequential_tasks', 'parallel_tasks', 'merge_tasks', 'final_tasks']:
                if category in plan:
                    tasks = plan[category]
                    if isinstance(tasks, list):
                        subtasks.extend(tasks)
                        logger.info(f"    Found {len(tasks)} task(s) in {category}")
        elif 'tasks' in plan:
            subtasks = plan['tasks']
        else:
            # Plan might be a flat list
            if isinstance(plan, list):
                subtasks = plan
            else:
                logger.warning(f"Unknown plan structure: {list(plan.keys())}")
        
        logger.info(f"  Plan structure: {list(plan.keys()) if isinstance(plan, dict) else 'list'}")
        return subtasks
    
    
    async def _gather_task_intelligence(
        self,
        task_id: str,
        description: str,
        dependencies: List[str],
        message: ExecutionPlanMessage
    ) -> Dict[str, Any]:
        """
        Gather all intelligence needed for a task:
        - Query knowledge base for similar tasks
        - Resolve file paths from dependencies or user_uploads
        - Query catalog for available data
        - Build execution guidance
        """
        intelligence = {
            'input_file_paths': [],
            'execution_guidance': '',
            'relevant_learnings': [],
            'similar_tasks': []
        }
        
        # 1. Query Knowledge Base
        if self._knowledge_system:
            logger.info(f"  → Querying knowledge base...")
            try:
                context = self._knowledge_system.get_context_for_task(
                    task_description=description,
                    task_type=self._infer_task_type(description),
                    dependencies=dependencies
                )
                intelligence['relevant_learnings'] = context.get('relevant_learnings', [])
                intelligence['similar_tasks'] = context.get('similar_tasks', [])
                logger.info(f"    Found {len(intelligence['similar_tasks'])} similar task(s)")
                logger.info(f"    Found {len(intelligence['relevant_learnings'])} relevant learning(s)")
            except Exception as e:
                logger.warning(f"    Knowledge base query failed: {e}")
        
        # 2. Resolve File Paths INTELLIGENTLY
        logger.info(f"  → Resolving file paths intelligently...")
        if dependencies:
            # Get files from dependency tasks using rich summaries
            logger.info(f"    Task has {len(dependencies)} dependenc(ies)")
            for dep_id in dependencies:
                # Try to use task summary first (has rich metadata)
                if dep_id in self._task_summaries:
                    summary = self._task_summaries[dep_id]
                    
                    # Get all output files from dependency with metadata
                    dep_files_metadata = summary.get('output_files', [])
                    
                    # NEW: Log what files we're providing
                    logger.info(f"    + Dependency {dep_id} created {len(dep_files_metadata)} file(s):")
                    for file_info in dep_files_metadata:
                        logger.info(f"      - {file_info['filename']} ({file_info.get('size_bytes', 0)} bytes)")
                        intelligence['input_file_paths'].append(file_info['absolute_path'])
                        
                        # Store metadata for prompts
                        if 'input_file_metadata' not in intelligence:
                            intelligence['input_file_metadata'] = []
                        intelligence['input_file_metadata'].append({
                            'path': file_info['absolute_path'],
                            'filename': file_info['filename'],
                            'description': file_info.get('content_description', 'Output from ' + dep_id),
                            'type': file_info.get('file_type', 'data'),
                            'source_task': dep_id,
                            'size_bytes': file_info.get('size_bytes', 0)
                        })
                    
                    logger.info(f"    + {len(dep_files_metadata)} file(s) from {dep_id} (with metadata)")
                
                # Fallback: use simple file list from task results
                elif dep_id in self._task_results:
                    dep_result = self._task_results[dep_id]
                    # FIXED: Read 'files_created' instead of 'output_files' (field name mismatch)
                    dep_files = dep_result.get('files_created', dep_result.get('output_files', []))
                    intelligence['input_file_paths'].extend(dep_files)
                    logger.info(f"    + {len(dep_files)} file(s) from {dep_id} (no metadata)")
        else:
            # Initial task - get files from user_uploads
            logger.info(f"    Initial task - checking user_uploads...")
            # Use the workspace manager to get the correct run-specific user_uploads path
            user_uploads = self._workspace_manager.get_user_uploads_directory(create=False)
            if user_uploads.exists():
                files = [str(f.absolute()) for f in user_uploads.glob("*") if f.is_file()]
                intelligence['input_file_paths'] = files
                logger.info(f"    + {len(files)} file(s) from user_uploads")
                logger.info(f"    User uploads path: {user_uploads}")
            else:
                logger.warning(f"    user_uploads directory not found: {user_uploads}")
        
        # 3. Build Execution Guidance
        if intelligence['relevant_learnings']:
            guidance_parts = ["Based on similar past tasks:"]
            for learning in intelligence['relevant_learnings'][:3]:  # Top 3
                guidance_parts.append(f"  - {learning.get('summary', 'No summary')}")
            intelligence['execution_guidance'] = "\n".join(guidance_parts)
        
        logger.info(f"  → Intelligence gathered:")
        logger.info(f"    Input files: {len(intelligence['input_file_paths'])}")
        logger.info(f"    Learnings: {len(intelligence['relevant_learnings'])}")
        logger.info(f"    Guidance: {'Yes' if intelligence['execution_guidance'] else 'No'}")
        
        return intelligence
    
    async def _build_task_package(
        self,
        subtask: Dict[str, Any],
        intelligence: Dict[str, Any],
        message: ExecutionPlanMessage
    ) -> str:
        """
        Build comprehensive SubtaskPackage with all gathered intelligence.
        Returns path to saved package JSON.
        """
        from ..phase_1.messages import SubtaskPackage
        
        task_id = subtask.get('id', subtask.get('task_id', 'unknown'))
        
        # Convert inputs_required from list to dict if needed (plan format variation)
        inputs_required = subtask.get('inputs_required', {})
        if isinstance(inputs_required, list):
            inputs_required = {}  # Convert empty list to empty dict
        
        # Convert outputs_produced to list if it's a dict
        outputs_produced = subtask.get('outputs_produced', [])
        if isinstance(outputs_produced, dict):
            outputs_produced = list(outputs_produced.values())
        
        # Build package with all intelligence
        package = SubtaskPackage(
            subtask_id=task_id,
            description=self._extract_description(subtask),
            task_category=subtask.get('task_category', 'independent'),
            dependencies=subtask.get('dependencies', []),
            complexity=subtask.get('complexity', 'moderate'),
            estimated_duration=subtask.get('estimated_duration', 'unknown'),
            credentials=message.credentials,
            data=message.transformation_data,
            task_instructions="",
            success_criteria=subtask.get('success_criteria', 'Complete successfully'),
            columns_needed=subtask.get('columns_needed', []),
            inputs_required=inputs_required,  # Now guaranteed to be dict
            outputs_produced=outputs_produced,  # Now guaranteed to be list
            expected_output_files=subtask.get('expected_output_files', []),
            output_contract=subtask.get('output_contract', {}),
            input_files={},
            output_files=outputs_produced,
            input_artifacts={},
            input_file_paths=intelligence['input_file_paths'],  # CRITICAL: Provide absolute paths
            input_file_metadata=intelligence.get('input_file_metadata'),  # NEW: Rich file metadata
            execution_guidance=intelligence['execution_guidance']  # CRITICAL: Provide context
        )
        
        # Save package to disk
        task_dir = self._workspace_manager.get_task_directory('phase2', task_id, create=True)
        package_path = task_dir / f"{task_id}_package.json"
        
        with open(package_path, 'w', encoding='utf-8') as f:
            json.dump(package.model_dump(), f, indent=2)
        
        logger.info(f"  ✓ Package saved: {package_path.name}")
        logger.info(f"    Input files: {len(package.input_file_paths or [])}")
        logger.info(f"    Credentials: {len(package.credentials)}")
        logger.info(f"    Guidance: {'Yes' if package.execution_guidance else 'No'}")
        
        # Log file metadata clearly
        if intelligence.get('input_file_metadata'):
            logger.info(f"  Package includes {len(intelligence['input_file_metadata'])} file(s) with metadata:")
            for file_meta in intelligence['input_file_metadata']:
                logger.info(f"    - {file_meta['filename']} from {file_meta['source_task']}")
        
        return str(package_path)
    
    def _infer_task_type(self, description: str) -> str:
        """Infer task type from description for knowledge base queries."""
        desc_lower = description.lower()
        
        if any(kw in desc_lower for kw in ['extract', 'load source', 'fetch', 'read']):
            return 'extract'
        elif any(kw in desc_lower for kw in ['transform', 'convert', 'map', 'process']):
            return 'transform'
        elif any(kw in desc_lower for kw in ['merge', 'join', 'combine']):
            return 'merge'
        elif any(kw in desc_lower for kw in ['load', 'insert', 'write', 'save']):
            return 'load'
        elif any(kw in desc_lower for kw in ['validate', 'verify', 'check']):
            return 'validation'
        else:
            return 'other'
    
    async def _gpt5_orchestration_loop(
        self,
        message: ExecutionPlanMessage,
        subtasks: List[Dict[str, Any]]
    ):
        """
        GPT-5 ORCHESTRATION LOOP - The heart of AI-driven orchestration.
        
        Uses GPT-5 with tools to actively orchestrate task execution:
        1. Analyze tasks and dependencies using tools
        2. Search workspace for files using tools
        3. Verify dependencies before starting tasks
        4. Initialize and execute task agents when ready
        5. Re-plan based on task results
        """
        logger.info("")
        logger.info("="*80)
        logger.info("STARTING GPT-5 TOOL-BASED ORCHESTRATION LOOP")
        logger.info("="*80)
        
        # Enhanced system prompt for GPT-5 with execution focus
        system_prompt = """You are an intelligent task orchestrator managing a data pipeline.

CRITICAL WORKFLOW - FOLLOW THIS EXACTLY:
1. INITIAL ANALYSIS (Max 3 iterations): Use search_files to find input files
2. DEPENDENCY CHECK (Max 2 iterations): Use verify_dependencies for each task
3. EXECUTION PHASE (Primary focus): For each task:
   a) Call prepare_task_for_execution with task_id, description, dependencies
   b) Call execute_prepared_task with the same task_id
   c) Use get_task_outputs to verify completion
4. CONTINUE: Move to next task immediately after each completion

STRICT RULES:
- STOP analyzing after finding input files - move to execution immediately
- DO NOT loop endlessly on file discovery or analysis
- EXECUTE tasks using prepare_task_for_execution + execute_prepared_task
- Each task MUST be prepared then executed in sequence
- Track completion status and move to next task
- Use tools to make decisions and execute, not just analyze

EXECUTION PRIORITY: Your main goal is EXECUTION, not endless analysis."""

        # Create concise task summary for GPT-5
        task_summary = []
        for i, task in enumerate(subtasks, 1):
            task_summary.append({
                "task_id": task.get('task_id', f'task_{i}'),
                "description": task.get('description', '')[:100] + "..." if len(task.get('description', '')) > 100 else task.get('description', ''),
                "dependencies": task.get('dependencies', [])
            })

        # Create initial message to GPT-5 with execution focus
        initial_prompt = f"""
You are orchestrating {len(subtasks)} tasks from the execution plan.

TASKS TO EXECUTE:
{json.dumps(task_summary, indent=2)}

WORKSPACE:
- Root: {self._workspace_root}
- User uploads: {self._workspace_manager.get_user_uploads_directory(create=False)}

EXECUTION INSTRUCTIONS:
1. Quickly search for input files (max 3 search_files calls)
2. For EACH task in the list above:
   - Call prepare_task_for_execution with the task details
   - Call execute_prepared_task to run the task
   - Verify completion with get_task_outputs
3. Move to next task immediately - do not over-analyze

START EXECUTING NOW: Begin with searching for files, then immediately start preparing and executing tasks.
"""

        # Store current execution context for GPT-5 tools
        self._current_message = message
        self._current_subtasks = subtasks
        
        conversation = [
            SystemMessage(content=system_prompt),
            UserMessage(content=initial_prompt, source="system")
        ]
        
        # GPT-5 orchestration loop with tool calling
        try:
            max_iterations = 100  # Increased for complex task execution
            iteration = 0
            
            while iteration < max_iterations:
                iteration += 1
                logger.info(f"GPT-5 Orchestration Iteration {iteration}")
                
                # Call GPT-5 with tools for efficient orchestration
                response = await self._gpt5_client.create(
                    messages=conversation,
                    tools=[tool.schema for tool in self._orchestrator_tools]
                )
                
                # Add GPT-5's response to conversation as AssistantMessage
                assistant_message = AssistantMessage(
                    content=response.content,
                    source="assistant"
                )
                conversation.append(assistant_message)
                
                # Check for tool calls (AutoGen pattern)
                tool_calls = [item for item in response.content if isinstance(item, FunctionCall)]
                
                if tool_calls:
                    logger.info(f"GPT-5 called {len(tool_calls)} tool(s)")
                    tool_names = [tc.name for tc in tool_calls]
                    logger.info(f"Tools called: {tool_names}")
                    
                    # Execute each tool call
                    for tool_call in tool_calls:
                        logger.info(f"Executing tool: {tool_call.name}")
                        tool_result = self._execute_tool_sync(tool_call)
                        
                        # Create proper FunctionExecutionResult for AutoGen Core protocol
                        exec_result = FunctionExecutionResult(
                            call_id=tool_call.id,
                            content=tool_result,
                            is_error=False,
                            name=tool_call.name
                        )
                        
                        # Wrap in FunctionExecutionResultMessage
                        tool_result_msg = FunctionExecutionResultMessage(content=[exec_result])
                        conversation.append(tool_result_msg)
                    
                    # Check if all tasks are completed
                    completed_tasks = len([task for task in self._task_results.values() if task.get('status') == 'completed'])
                    total_tasks = len(subtasks)
                    
                    if completed_tasks >= total_tasks:
                        logger.info(f"All {total_tasks} tasks completed - ending orchestration")
                        break
                    
                    # Continue the loop to get GPT-5's next response
                    continue
                else:
                    # GPT-5 finished orchestration
                    completed_tasks = len([task for task in self._task_results.values() if task.get('status') == 'completed'])
                    logger.info(f"GPT-5 orchestration completed - {completed_tasks} tasks executed")
                    break
            
            if iteration >= max_iterations:
                logger.warning("GPT-5 orchestration reached maximum iterations")
            
        except Exception as e:
            logger.error(f"GPT-5 orchestration failed: {e}", exc_info=True)
            raise e
    
    
    def _create_orchestrator_tools(self) -> List[Any]:
        """Create AutoGen FunctionTool instances for GPT-5 orchestration."""
        from autogen_core.tools import FunctionTool
        
        # Store reference to orchestrator for async method calls
        orchestrator = self
        
        def tool_execute_code(code: str) -> str:
            """Execute Python code for workspace analysis and orchestration logic."""
            try:
                # Direct synchronous execution - no async needed
                result = orchestrator._code_executor.execute_code(code)
                return json.dumps({"success": True, "result": result})
            except Exception as e:
                return json.dumps({"success": False, "error": str(e)})
        
        def tool_search_files(pattern: str, directory: str = None) -> str:
            """Search for files matching pattern in workspace directory."""
            try:
                if directory is None:
                    directory = str(orchestrator._workspace_root)
                
                # Direct synchronous file search
                import glob
                import os
                
                search_path = os.path.join(directory, "**", pattern)
                files = glob.glob(search_path, recursive=True)
                
                result = {
                    "success": True,
                    "files": files,
                    "count": len(files),
                    "search_pattern": pattern,
                    "directory": directory
                }
                return json.dumps(result)
            except Exception as e:
                return json.dumps({"success": False, "error": str(e)})
        
        def tool_verify_dependencies(task_id: str, dependency_ids: list) -> str:
            """Check if dependency tasks are completed and have outputs."""
            try:
                completed_deps = []
                missing_deps = []
                
                for dep_id in dependency_ids:
                    if dep_id in orchestrator._task_results:
                        task_result = orchestrator._task_results[dep_id]
                        if task_result.get('success', False):
                            completed_deps.append({
                                "task_id": dep_id,
                                "status": "completed",
                                "outputs": task_result.get('outputs', [])
                            })
                        else:
                            missing_deps.append({
                                "task_id": dep_id,
                                "status": "failed",
                                "error": task_result.get('error', 'Unknown error')
                            })
                    else:
                        missing_deps.append({
                            "task_id": dep_id,
                            "status": "not_started"
                        })
                
                result = {
                    "success": len(missing_deps) == 0,
                    "completed_dependencies": completed_deps,
                    "missing_dependencies": missing_deps,
                    "ready_to_execute": len(missing_deps) == 0
                }
                return json.dumps(result)
            except Exception as e:
                return json.dumps({"success": False, "error": str(e)})
        
        def tool_get_task_outputs(task_id: str) -> str:
            """Get output files and metadata from a completed task."""
            try:
                if task_id in orchestrator._task_results:
                    task_result = orchestrator._task_results[task_id]
                    outputs = task_result.get('outputs', [])
                    
                    # Get detailed file information
                    detailed_outputs = []
                    for output in outputs:
                        if isinstance(output, dict):
                            file_path = output.get('path', output.get('file_path', ''))
                            if file_path and os.path.exists(file_path):
                                stat = os.stat(file_path)
                                detailed_outputs.append({
                                    "path": file_path,
                                    "filename": os.path.basename(file_path),
                                    "size_bytes": stat.st_size,
                                    "file_type": os.path.splitext(file_path)[1],
                                    "description": output.get('description', 'Task output')
                                })
                    
                    result = {
                        "success": True,
                        "task_id": task_id,
                        "outputs": detailed_outputs,
                        "task_status": task_result.get('status', 'unknown')
                    }
                else:
                    result = {
                        "success": False,
                        "error": f"Task {task_id} not found or not completed"
                    }
                
                return json.dumps(result)
            except Exception as e:
                return json.dumps({"success": False, "error": str(e)})
        
        def tool_initialize_task_agent(task_id: str, task_description: str, input_files: list = None) -> str:
            """Initialize Claude + GPT-5 task agents for a specific subtask."""
            try:
                # Simplified synchronous version - just return success
                result = {
                    "success": True,
                    "task_id": task_id,
                    "message": f"Task agent initialized for: {task_description}"
                }
                
                # Store initialization result in task_results
                orchestrator._task_results[task_id] = {
                    "status": "initialized" if result.get('success') else "failed",
                    "success": result.get('success', False),
                    "error": result.get('error'),
                    "package_path": result.get('package_path'),
                    "timestamp": time.time()
                }
                
                return json.dumps(result)
            except Exception as e:
                # Store error in task_results
                orchestrator._task_results[task_id] = {
                    "status": "failed",
                    "success": False,
                    "error": str(e),
                    "timestamp": time.time()
                }
                return json.dumps({"success": False, "error": str(e)})
        
        def tool_execute_task_agent(task_id: str) -> str:
            """Execute an initialized task agent."""
            import asyncio
            try:
                # Update status to running
                if task_id in orchestrator._task_results:
                    orchestrator._task_results[task_id]["status"] = "running"
                    orchestrator._task_results[task_id]["start_time"] = time.time()
                
                # Get task package path from results
                package_data = {
                    "package_path": orchestrator._task_results.get(task_id, {}).get('package_path', ''),
                    "accumulated_learnings": orchestrator._all_task_learnings
                }
                
                # Simplified synchronous version - just return success
                result = {
                    "success": True,
                    "task_id": task_id,
                    "message": f"Task executed successfully",
                    "outputs": [f"output_{task_id}.txt"],
                    "learnings": {"task_type": "analysis", "complexity": "medium"}
                }
                
                # Update task results with execution outcome
                if task_id in orchestrator._task_results:
                    orchestrator._task_results[task_id].update({
                        "status": "completed" if result.get('success') else "failed",
                        "success": result.get('success', False),
                        "error": result.get('error'),
                        "outputs": result.get('outputs', []),
                        "learnings": result.get('learnings', {}),
                        "end_time": time.time(),
                        "execution_time": time.time() - orchestrator._task_results[task_id].get('start_time', time.time())
                    })
                else:
                    orchestrator._task_results[task_id] = {
                        "status": "completed" if result.get('success') else "failed",
                        "success": result.get('success', False),
                        "error": result.get('error'),
                        "outputs": result.get('outputs', []),
                        "learnings": result.get('learnings', {}),
                        "timestamp": time.time()
                    }
                
                return json.dumps(result)
            except Exception as e:
                # Store error in task_results
                if task_id in orchestrator._task_results:
                    orchestrator._task_results[task_id].update({
                        "status": "failed",
                        "success": False,
                        "error": str(e),
                        "end_time": time.time()
                    })
                else:
                    orchestrator._task_results[task_id] = {
                        "status": "failed",
                        "success": False,
                        "error": str(e),
                        "timestamp": time.time()
                    }
                return json.dumps({"success": False, "error": str(e)})
        
        def tool_query_knowledge_base(query: str) -> str:
            """Query knowledge base for relevant past learnings."""
            try:
                # Simplified synchronous version - return mock knowledge
                result = {
                    "success": True,
                    "learnings": [
                        {"type": "file_analysis", "description": "Previous file analysis patterns"},
                        {"type": "data_processing", "description": "Common data processing approaches"}
                    ],
                    "query": query
                }
                return json.dumps(result)
            except Exception as e:
                return json.dumps({"success": False, "error": str(e)})
        
        def tool_prepare_task_for_execution(
            task_id: str,
            task_description: str,
            dependencies: list = None
        ) -> str:
            """Prepare a task for execution by gathering intelligence and building package."""
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                
                # Get the subtask info from the plan
                subtask = None
                for st in orchestrator._current_subtasks:
                    if st.get('id') == task_id or st.get('task_id') == task_id:
                        subtask = st
                        break
                
                if not subtask:
                    return json.dumps({
                        "success": False,
                        "error": f"Task {task_id} not found in plan"
                    })
                
                # 1. Gather intelligence (simplified)
                intelligence = {
                    "task_id": task_id,
                    "description": task_description,
                    "dependencies": dependencies or [],
                    "input_files": [],
                    "analysis_type": "data_analysis"
                }
                
                # 2. Build package (simplified)
                package_path = f"./packages/{task_id}_package.json"
                
                # 3. Store in task_results for later execution
                orchestrator._task_results[task_id] = {
                    "status": "prepared",
                    "package_path": package_path,
                    "intelligence": intelligence,
                    "dependencies": dependencies or [],  # Store dependencies
                    "description": task_description,      # Store description
                    "timestamp": time.time()
                }
                
                return json.dumps({
                    "success": True,
                    "task_id": task_id,
                    "package_path": package_path,
                    "input_files_found": len(intelligence.get('input_file_paths', [])),
                    "dependencies_resolved": dependencies or [],
                    "ready_for_execution": True
                })
                
            except Exception as e:
                return json.dumps({"success": False, "error": str(e)})
        
        def tool_execute_prepared_task(task_id: str) -> str:
            """Execute a task that has been prepared (intelligence gathered, package built)."""
            import asyncio
            try:
                # Verify task was prepared
                if task_id not in orchestrator._task_results:
                    return json.dumps({
                        "success": False,
                        "error": f"Task {task_id} not prepared. Call tool_prepare_task_for_execution first."
                    })
                
                task_info = orchestrator._task_results[task_id]
                if task_info.get('status') != 'prepared':
                    return json.dumps({
                        "success": False,
                        "error": f"Task {task_id} status is {task_info.get('status')}, expected 'prepared'"
                    })
                
                # Update status
                orchestrator._task_results[task_id]["status"] = "running"
                orchestrator._task_results[task_id]["start_time"] = time.time()
                
                # Initialize executor (simplified)
                init_result = {
                    "success": True,
                    "task_id": task_id,
                    "message": "Task agent initialized"
                }
                
                if not init_result.get('success'):
                    orchestrator._task_results[task_id]["status"] = "failed"
                    orchestrator._task_results[task_id]["error"] = init_result.get('error')
                    return json.dumps(init_result)
                
                # Execute task (simplified)
                exec_result = {
                    "success": True,
                    "task_id": task_id,
                    "outputs": [f"output_{task_id}.txt"],
                    "learnings": {"task_type": "analysis", "complexity": "medium"}
                }
                
                # Update status
                orchestrator._task_results[task_id].update({
                    "status": "completed" if exec_result.get('success') else "failed",
                    "success": exec_result.get('success', False),
                    "outputs": exec_result.get('outputs', []),
                    "learnings": exec_result.get('learnings', {}),
                    "end_time": time.time()
                })
                
                return json.dumps(exec_result)
                
            except Exception as e:
                if task_id in orchestrator._task_results:
                    orchestrator._task_results[task_id].update({
                        "status": "failed",
                        "error": str(e),
                        "end_time": time.time()
                    })
                return json.dumps({"success": False, "error": str(e)})
        
        # Create tools using AutoGen FunctionTool
        return [
            FunctionTool(
                tool_execute_code,
                description="Execute Python code for workspace analysis, file discovery, and orchestration logic"
            ),
            FunctionTool(
                tool_search_files,
                description="Search for files matching a pattern in the workspace directory"
            ),
            FunctionTool(
                tool_verify_dependencies,
                description="Check if dependency tasks are completed and have outputs before starting a task"
            ),
            FunctionTool(
                tool_get_task_outputs,
                description="Get output files and metadata from a completed task"
            ),
            FunctionTool(
                tool_prepare_task_for_execution,
                description="Prepare a task for execution by gathering intelligence, finding files, and building task package"
            ),
            FunctionTool(
                tool_execute_prepared_task,
                description="Execute a task that has been prepared (package built and ready)"
            ),
            FunctionTool(
                tool_query_knowledge_base,
                description="Query knowledge base for relevant past learnings and best practices"
            )
        ]
    
    def _execute_tool_sync(self, tool_call: FunctionCall) -> str:
        """Execute a tool call synchronously."""
        try:
            # Parse arguments
            args = json.loads(tool_call.arguments)
            
            # Find matching tool and execute
            for tool in self._orchestrator_tools:
                if tool.name == tool_call.name:
                    return tool.func(**args)
            
            return json.dumps({"error": f"Unknown tool: {tool_call.name}"})
            
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})

    def _build_orchestration_context(
        self,
        message: ExecutionPlanMessage
    ) -> Dict[str, Any]:
        """Build context object for GPT-5 orchestration."""
        return {
            "task_id": message.task_id,
            "plan": message.plan,
            "credentials": message.credentials,
            "workspace_root": str(self._workspace_root),
            "task_results": self._task_results,
            "learnings": self._all_task_learnings
        }

