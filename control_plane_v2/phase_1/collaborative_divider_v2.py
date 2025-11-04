"""
Phase 1: Collaborative Task Divider V2 - FLAG-BASED REDESIGN

ARCHITECTURE:
- Phase 1a: Structure Analysis (Claude solo, flag-based completion)
  - Claude executes code to analyze data
  - Saves structure_analysis.json with analysis_complete flag
  - Loops until flag = True
  
- Phase 1b: Task Division Debate (Claude + GPT-5 collaboration)
  - Uses structure_analysis.json from Phase 1a
  - No more code execution needed
  - Clean debate on how to divide tasks

Engineers:
- Claude 4.5 (Data Engineer) - analysis & proposal
- GPT-5 Medium (Senior Data Engineer) - review & quality check
"""

import json
import logging
import re
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime

from autogen_core.models import ChatCompletionClient, UserMessage, AssistantMessage
from autogen_core.code_executor import CodeBlock
from autogen_core import CancellationToken, SingleThreadedAgentRuntime, TRACE_LOGGER_NAME
from autogen_ext.code_executors import CodeExecutor

from .messages import (
    TaskDivisionRequest, 
    TaskDivisionResult, 
    Subtask, 
    SubtaskPackage,
    TaskDivisionProposal,
    ReviewResult
)
from .task_models import TaskDivisionProposal as PydanticTaskDivisionProposal, ReviewResult as PydanticReviewResult
from ..phase_1_to_2z_messages import ExecutionCompletionMessage
from ..workspace_manager import WorkspaceManager

# Use AutoGen Core trace logging
logger = logging.getLogger(f"{TRACE_LOGGER_NAME}.phase1.collaborative_divider")


class CollaborativeTaskDivider:
    """
    FLAG-BASED Two-phase collaborative task division:
    1a. Structure Analysis (Claude solo with code + flag)
    1b. Division Debate (Claude + GPT-5 with real data)
    """
    
    # Phase 1a: Structure Analysis Prompt (Claude Solo)
    CLAUDE_PHASE1A_ANALYSIS_PROMPT = """You are a Data Engineer. Your task:

READ a file, UNDERSTAND its structure deeply, THEN save your analysis.

GUIDANCE (use your best judgment):
1. Prefer ASCII in print statements if possible (Windows console compatibility)
2. Write code however works best for you (single block or multiple)
3. **CRITICAL: Each code block runs in a NEW Python process - include ALL imports at the top of EVERY block**
4. Analyze the data thoroughly and save what you discover
5. Use real data from actual analysis, avoid placeholder/stub values
6. Discover field names dynamically rather than hardcoding assumptions
7. For JSON serialization: convert bytes to strings (b'5' -> '5'), use JSON-serializable types
8. Take whatever approach works best to understand the data structure
9. **CRITICAL: DO NOT print binary data (PDF contents, images, etc.) - only print metadata/summaries**

YOUR WORKFLOW (GO SLOW, STEP BY STEP):

STEP 1: List file paths ONLY (don't open yet)
- If tar/zip: List archive contents
- Get file names, sizes, extensions
- Don't read file contents yet

STEP 2: Sample a FEW files (2-5 files maximum)
- Pick diverse samples (different types/sizes)
- Read first 1000 characters or first 20 lines only
- Don't try to load entire files

STEP 3: Build structure analysis from samples
- Summarize what you discovered
- Estimate counts, note patterns
- Use samples to infer overall structure

STEP 4: Save findings to 'structure_analysis.json'
- "analysis_complete": true (REQUIRED FLAG)
- Real data from your sampling

⚠️ GO SLOW: Break work into multiple small code blocks
⚠️ SAMPLE ONLY: Don't read entire large files
⚠️ EACH BLOCK: Include imports at the top

If you encounter errors, they will be shown to you. Fix and retry.

Start now - ANALYZE FIRST, SAVE SECOND!
"""

    # Phase 1b: Task Division Prompts (Claude + GPT-5 Debate)
    CLAUDE_PHASE1B_PROPOSAL_PROMPT = """You are dividing the work into tasks for Phase 2Z orchestrator.

CONTEXT: Each task will be executed by an independent AI agent (Worker powered by Claude 4.5).
- Make task descriptions self-contained with complete instructions
- Specify explicit dependencies (agents can't infer relationships)
- Include all necessary context in work_scope
- Agents only see their own task, not others

WORKER AGENT CAPABILITIES (Plan tasks accordingly):
Worker agents executing your tasks have access to these powerful tools:

1. NATIVE PDF EXTRACTION (Claude 4.5 built-in):
   - extract_pdf_data: Extract structured data from a single PDF with native reading
   - extract_multiple_pdfs: Batch process MULTIPLE PDFs in parallel (can handle dozens at once!)
   - Auto-translates Spanish/Portuguese to English
   - Handles complex layouts, tables, multi-column formats
   - IMPLICATION: Don't create separate tasks per PDF! Worker can process many PDFs in one task.
   
2. FILE EDITING TOOLS:
   - Can edit ANY file type without regenerating (HTML, JSON, Python, YAML, CSV, etc.)
   - Precise search/replace, insert, delete operations
   - IMPLICATION: Can create "fix report styling" tasks instead of "regenerate entire report"

3. CODE EXECUTION:
   - Full Python with pandas, numpy, matplotlib, visualization libraries
   - Can install additional packages via pip
   - Persistent kernel across retry attempts
   
4. WORKSPACE TOOLS:
   - Directory scanning, TODO tracking, file management

TASK PLANNING BEST PRACTICES:
- For 10-20 PDFs: Create ONE task that processes all PDFs (Worker uses extract_multiple_pdfs)
- For large HTML generation: Worker can use templates + file editing for efficiency
- For data pipelines: Worker can handle multi-step transformations in one task
- Don't over-divide work - Worker is powerful and can handle complex tasks

CRITICAL - CHECK SKIP_SIDE_TASKS:
- If manifest has transformation_config.skip_side_tasks: true, ONLY create transformation/core tasks
- SKIP validation tasks (validate schemas, connectivity checks, etc.)
- SKIP preparation tasks unless absolutely required for transformations to run
- Focus ONLY on the core work: extract, transform, merge, load

TASK PLANNING GUIDELINES:
- Aim for 5-10 tasks by default; combine related work when logical
- EXCEPTION: If manifest explicitly requests separate tasks per item (e.g., "process EACH PDF as separate task"), honor that request even if it creates 20+ tasks
- Prefer sequential tasks unless parallelization is necessary
- Check manifest execution_preferences and additional_instructions for task organization guidance
- Manifest requirements override default consolidation preferences

USE STRUCTURE ANALYSIS:
- Reference EXACT field names from structure_analysis.json
- Don't assume or invent field names not in the analysis

REQUIRED STRUCTURE:
{
  "task_breakdown": {
    "tasks": [
      // Simple list of ALL tasks - no categorization needed!
      // Orchestrator will determine execution order based on dependencies
      // Example: 
      // {
      //   "task_id": "extract_data",
      //   "description": "Extract source data...",
      //   "credentials": {...},
      //   "work_scope": {...},
      //   "dependencies": [],  // Runs first (no dependencies)
      //   "expected_output_files": [...]
      // },
      // {
      //   "task_id": "transform_data",
      //   "description": "Transform extracted data...",
      //   "credentials": {...},
      //   "work_scope": {...},
      //   "dependencies": ["extract_data"],  // Runs after extract_data
      //   "expected_output_files": [...]
      // }
    ]
  }
}

FOR EACH TASK, INCLUDE:
- task_id: unique identifier (use descriptive names)
- description: what this task does (be specific and clear)
- work_scope: what portion of the work this task handles (define based on structure_analysis and deep understanding)
- credentials: what credentials/resources needed
- dependencies: list of task_ids that must complete first
  CRITICAL: If this task needs files created by another task, that task MUST be listed in dependencies
  Validate: Does this task reference any files? If yes, which task creates them? Add those tasks to dependencies.
- expected_output_files: Logical filenames with specific extensions chosen based on task type

CREDENTIALS:
When tasks need data sources, tell them to "use provided credentials" (not environment variables).

INSTRUCTION FILES:
Don't parse instruction files yourself. Tell agents: "Read <file>, extract relevant section, apply it."

OUTPUT FILES:
- Specify logical filenames with appropriate extensions
- Use relative paths (e.g., 'outputs/result.json')
- Name files descriptively for downstream tasks

Output JSON only.
"""

    GPT5_PHASE1B_REVIEW_PROMPT = """Review GPT-5's task division plan.

Your job: Check for CRITICAL BLOCKERS only, not to redesign the plan.

REMEMBER: Workers have powerful capabilities (see below), so simple tasks are fine.

CHECK FOR (3 questions):
1. CIRCULAR dependencies? (A→B→A) - If YES, REJECT
2. MISSING dependencies? (Task reads file X but no task creates X) - If YES, REJECT  
3. IMPOSSIBLE operations? (Reading non-existent data sources) - If YES, REJECT

If all 3 are NO → APPROVE immediately.

DO NOT REJECT FOR:
- Field naming inconsistencies, credentials format, validation steps (workers will handle)
- Architectural choices, task grouping, complexity level
- DSL ambiguities or reasonable assumptions about data
- Any issue a competent worker can resolve during execution
- Tasks that seem "too big" (Workers can batch process many PDFs, handle complex operations)

WORKER CAPABILITIES TO CONSIDER:
- Workers can process dozens of PDFs in ONE task (extract_multiple_pdfs tool)
- Workers can edit files without regenerating them (file editing tools)
- Workers have full Python capabilities with libraries
- Don't require tasks to be overly granular

RESPOND WITH JSON:
{
  "approved": true/false,
  "feedback": "brief reasoning (1-2 sentences)",
  "issues": ["only if rejected - list specific CRITICAL blockers"]
}
"""
    
    def __init__(
        self,
        claude_client: ChatCompletionClient,
        gpt5_client: ChatCompletionClient,
        claude_executor: CodeExecutor,
        gpt5_executor: CodeExecutor,
        workspace_manager: WorkspaceManager,
        max_iterations: int = 15  # Increased for complex tasks
    ):
        self._claude_client = claude_client
        self._gpt5_client = gpt5_client
        self._claude_executor = claude_executor
        self._gpt5_executor = gpt5_executor
        self._workspace_manager = workspace_manager
        self._max_iterations = max_iterations
        
        logger.info("CollaborativeTaskDivider V2 (Flag-Based) initialized")
        logger.info(f"  Max debate iterations: {max_iterations}")
    
    async def divide_task(
        self,
        request: TaskDivisionRequest,
        runtime: 'SingleThreadedAgentRuntime',
        output_dir: Optional[Path] = None
    ) -> 'ExecutionCompletionMessage':
        """
        Main entry point - Creates plan and DIRECTLY runs Phase 2Z
        
        Phase 1a: Claude analyzes with code -> saves structure_analysis.json -> sets flag
        Phase 1b: Claude + GPT-5 debate and agree on plan
        Phase 1c: Send ExecutionPlanMessage to Phase 2Z orchestrator
        
        Returns:
            ExecutionCompletionMessage from Phase 2Z
        """
        from ..phase_1_to_2z_messages import ExecutionPlanMessage, ExecutionCompletionMessage, SubtaskPlan
        from ..phase_2.gpt5_orchestrator import GPT5OrchestratorAgent
        from autogen_ext.code_executors import LocalCommandLineCodeExecutor
        from autogen_core import AgentId
        
        logger.info(f"Starting FLAG-BASED task division: {request.task_id}")
        
        # Store request for helper methods
        self._current_request = request
        
        # Load plan content first
        plan_content = self._load_plan(request)
        
        # ================================================================
        # PHASE 1A: STRUCTURE ANALYSIS (Claude Solo with Flag)
        # ================================================================
        structure_analysis = await self._phase_1a_structure_analysis(request, plan_content)
        
        if not structure_analysis or not structure_analysis.get('analysis_complete'):
            logger.error("Phase 1a failed - structure analysis incomplete")
            raise RuntimeError("Phase 1a FAILED: Claude did not complete structure analysis")
        
        logger.info(f"✓ Phase 1a complete!")
        logger.info(f"  Chains discovered: {structure_analysis.get('total_chains', 0)}")
        logger.info(f"  Primary key: {structure_analysis.get('primary_key', 'N/A')}")
        
        # ================================================================
        # PHASE 1B: TASK DIVISION DEBATE (Claude + GPT-5)
        # ================================================================
        logger.info("")
        logger.info("="*60)
        logger.info("PHASE 1B: TASK DIVISION DEBATE")
        logger.info("="*60)
        
        result = await self._phase_1b_debate(request, plan_content, structure_analysis)
        
        if not result:
            logger.error("Phase 1b failed - no valid proposal")
            raise RuntimeError("Phase 1b FAILED: Claude and GPT-5 could not agree on task division")
        
        # ================================================================
        # PHASE 1C: SEND PLAN TO PHASE 2Z ORCHESTRATOR
        # ================================================================
        logger.info("")
        logger.info("="*60)
        logger.info("PHASE 1C: SENDING PLAN TO PHASE 2Z ORCHESTRATOR")
        logger.info("="*60)
        
        # Build execution plan message - ACCEPT ANY STRUCTURE from Claude/GPT-5
        # Just wrap it with necessary metadata for Phase 2Z
        execution_plan = ExecutionPlanMessage(
            task_id=request.task_id,
            plan=result,  # Raw dict from Claude/GPT-5 - any structure is fine!
            structure_analysis=structure_analysis,  # Real data from Phase 1a
            credentials=self._extract_all_credentials(request),
            transformation_data=plan_content,
            workspace_root=str(self._workspace_manager.base_dir),
            additional_context=request.additional_context or {}
        )
        
        # LOG THE EXECUTION PLAN
        logger.info("="*60)
        logger.info("EXECUTION PLAN CREATED")
        logger.info("="*60)
        logger.info(f"Task ID: {request.task_id}")
        logger.info(f"Plan structure: {list(result.keys()) if isinstance(result, dict) else type(result)}")
        logger.info(f"Plan content: {json.dumps(result, indent=2)}")
        logger.info("="*60)
        
        # SAVE EXECUTION PLAN AS JSON FILE (include credentials)
        run_dir = self._workspace_manager.run_dir
        if run_dir:
            phase1_dir = run_dir / "phase1"
            phase1_dir.mkdir(exist_ok=True)
            
            # Add credentials and additional instructions to the plan before saving
            # Extract additional instructions from manifest (can come from execution_preferences.worker_instructions or other sources)
            manifest = request.additional_context.get('manifest', {})
            additional_instructions = manifest.get("execution_preferences", {}).get("worker_instructions", "")
            
            full_plan = {
                **result,  # task_breakdown, reasoning, confidence
                "credentials": execution_plan.credentials,  # Add credentials from ExecutionPlanMessage
                "additional_instructions": additional_instructions  # General field for any extra instructions to pass to workers
            }
            
            execution_plan_file = phase1_dir / "execution_plan.json"
            with open(execution_plan_file, 'w') as f:
                json.dump(full_plan, f, indent=2)
            
            logger.info(f"  Execution plan saved to: {execution_plan_file}")
            logger.info(f"  Credentials included: {len(execution_plan.credentials)} credential sets")
        
        logger.info(f"  Plan ready - passing to Phase 2Z orchestrator")
        
        # Phase 1: Only use Data Catalog (no RAG)
        # RAG is initialized later by Phase 2 for semantic search
        from ..data_catalog import DataCatalog
        run_dir = self._workspace_manager.run_dir
        if run_dir is None:
            raise ValueError("Run directory not set in WorkspaceManager")
        
        # Use catalog directory from workspace_manager
        catalog_dir = self._workspace_manager.get_catalog_directory(create=True)
        catalog_path = catalog_dir / "data_catalog.json"
        data_catalog = DataCatalog(str(catalog_path))
        logger.info(f"  Data Catalog initialized at: {catalog_path}")
        logger.info(f"  (RAG will be initialized by Phase 2 when needed)")
        
        # Register user upload files from run directory (flat structure)
        from pathlib import Path
        user_uploads_dir = self._workspace_manager.get_user_uploads_directory(create=False)
        if user_uploads_dir.exists():
            # No subdirectories - just register all files in user_uploads/
            for file_path in user_uploads_dir.glob("*"):
                if file_path.is_file():
                    # Infer file type from extension or name
                    file_type = "unknown"
                    if "mapping" in file_path.name.lower():
                        file_type = "mapping_plan"
                    elif file_path.suffix in ['.csv', '.json', '.parquet', '.xlsx']:
                        file_type = "input_file"
                    elif "schema" in file_path.name.lower():
                        file_type = "schema"
                    
                    data_catalog.register_file(
                        file_path=str(file_path.absolute()),
                        task_id="user_upload",
                        file_type=file_type,
                        metadata={
                            "source": "user_upload",
                            "upload_location": str(file_path.absolute())
                        }
                    )
            logger.info(f"  Registered {len(list(user_uploads_dir.glob('*')))} user upload files in catalog")
        else:
            logger.warning(f"  User uploads directory not found: {user_uploads_dir}")
        
        # Phase 2 will initialize full KnowledgeSystem (Catalog + RAG)
        # For now, Phase 1 only needs catalog for path registration
        knowledge_system = None  # Phase 1 doesn't use KnowledgeSystem
        
        # Create Phase 2 executor and orchestrator
        phase2_dir = self._workspace_manager.get_phase_directory('phase2', create=True)
        phase2_executor = LocalCommandLineCodeExecutor(work_dir=str(phase2_dir))
        
        # Phase 2 executor needs full KnowledgeSystem (Catalog + RAG)
        # Initialize it here for Phase 2 with proper directories
        from ..knowledge_system import KnowledgeSystem
        catalog_dir_str = str(self._workspace_manager.get_catalog_directory(create=True))
        vectordb_dir_str = str(self._workspace_manager.get_vectordb_directory(create=True))
        phase2_knowledge_system = KnowledgeSystem(
            workspace_root=str(run_dir),
            catalog_dir=catalog_dir_str,
            vectordb_dir=vectordb_dir_str
        )
        logger.info(f"  Phase 2 Knowledge System initialized (Catalog + RAG)")
        logger.info(f"    Catalog: {catalog_dir_str}")
        logger.info(f"    VectorDB: {vectordb_dir_str}")
        
        # NOTE: We do NOT create a shared executor here
        # The GPT-5 Orchestrator creates task-specific executors with their own working directories
        # This avoids duplicate executors and ensures proper task isolation
        
        # Register GPT-5 Intelligent Orchestrator
        logger.info("  Registering GPT-5 Intelligent Orchestrator agent...")
        await GPT5OrchestratorAgent.register(
            runtime,
            "phase2z_orchestrator",
            lambda: GPT5OrchestratorAgent(
                "GPT-5 Intelligent Orchestrator",
                gpt5_client=self._gpt5_client,
                workspace_manager=self._workspace_manager,
                workspace_root=self._workspace_manager.base_dir,
                claude_client=self._claude_client,
                gpt5_reviewer_client=self._gpt5_client,  # Using same GPT-5 for orchestration and review
                knowledge_system=phase2_knowledge_system  # CRITICAL: Pass knowledge system for learning accumulation
            )
        )
        logger.info("  ✓ GPT-5 Intelligent Orchestrator registered (with knowledge system)")
        
        # Send plan to orchestrator (fire-and-forget)
        orchestrator_id = AgentId("phase2z_orchestrator", "default")
        logger.info(f"  Sending plan to Phase 2Z...")
        
        # Fire-and-forget: Phase 1's job is done after sending
        # The message is queued and will be processed asynchronously by Phase 2Z
        logger.info(f"  Attempting to send ExecutionPlanMessage to {orchestrator_id}")
        logger.info(f"  Message type: {type(execution_plan)}")
        logger.info(f"  Message has plan: {hasattr(execution_plan, 'plan')}")
        
        try:
            send_result = await runtime.send_message(execution_plan, orchestrator_id)
            logger.info(f"  send_message returned: {type(send_result)}")
            if send_result:
                logger.info(f"  Result content: {send_result}")
        except Exception as e:
            logger.error(f"  send_message raised exception: {e}", exc_info=True)
        
        # Extract task counts from the plan (result is from Phase 1b)
        task_breakdown = result.get('task_breakdown', {})
        total_tasks = len(task_breakdown.get('tasks', []))
        
        logger.info(f"  ✓ Plan sent to Phase 2Z")
        logger.info(f"    Total tasks created: {total_tasks}")
        logger.info(f"  Phase 1 complete - execution handed off to Phase 2Z")
        
        # Phase 1 returns its own completion status
        return ExecutionCompletionMessage(
            task_id=request.task_id,
            overall_status='plan_created_and_sent',
            total_tasks=total_tasks,
            successful_tasks=total_tasks,  # Phase 1 succeeded in creating all tasks
            failed_tasks=0,
            task_summaries=[
                {
                    'phase': 'Phase 1a - Structure Analysis',
                    'status': 'complete',
                    'chains_discovered': structure_analysis.get('total_chains', 0)
                },
                {
                    'phase': 'Phase 1b - Task Division',
                    'status': 'complete',
                    'tasks_created': total_tasks
                },
                {
                    'phase': 'Phase 1c - Plan Delivery',
                    'status': 'sent_to_phase2z',
                    'orchestrator': 'phase2z_orchestrator'
                }
            ],
            execution_time=0.0,  # Can be calculated if needed
            notes=f"Phase 1 complete. Created {total_tasks} tasks and sent to Phase 2Z for execution."
        )
    
    async def _phase_1a_structure_analysis(
        self,
        request: TaskDivisionRequest,
        plan_content: Dict
    ) -> Optional[Dict]:
        """
        Phase 1a: Claude analyzes data structure with FLAG-BASED completion
        
        Claude executes code -> saves structure_analysis.json -> sets analysis_complete=True
        We loop until the flag is True
        """
        logger.info("="*60)
        logger.info("PHASE 1A: STRUCTURE ANALYSIS (Claude Solo)")
        logger.info("="*60)
        
        # Get workspace directory for saving structure_analysis.json (FIRST!)
        phase1_dir = self._workspace_manager.get_phase_directory('phase1', create=True)
        analysis_file_path = phase1_dir / 'structure_analysis.json'
        
        # Build prompt with EXACT paths
        prompt_parts = [self.CLAUDE_PHASE1A_ANALYSIS_PROMPT]
        
        # ALWAYS provide user_uploads directory location - crucial for any file-based task
        user_uploads_dir = self._workspace_manager.get_user_uploads_directory(create=False)
        import os
        from pathlib import Path
        
        # Add user_uploads context - ALWAYS needed for file discovery
        prompt_parts.append(f"\n\n{'='*60}")
        prompt_parts.append("FILE LOCATIONS - USE THESE PATHS:")
        prompt_parts.append(f"{'='*60}")
        prompt_parts.append(f"USER_UPLOADS_DIR = r\"{user_uploads_dir}\"")
        prompt_parts.append("")
        prompt_parts.append("All user-provided files are in the USER_UPLOADS_DIR (flat structure, no subdirectories).")
        
        # Check what files are actually in user_uploads
        available_files = []
        if user_uploads_dir.exists():
            available_files = [f.name for f in user_uploads_dir.glob("*") if f.is_file()]
            if available_files:
                prompt_parts.append(f"Available files in USER_UPLOADS_DIR:")
                for filename in available_files:
                    file_path = user_uploads_dir / filename
                    file_size = file_path.stat().st_size if file_path.exists() else 0
                    prompt_parts.append(f"  - {filename} ({file_size:,} bytes)")
                    logger.info(f"  User file: {filename} ({file_size:,} bytes)")
        
        # Check manifest for specific file references (optional)
        if request.additional_context and request.additional_context.get('manifest'):
            manifest = request.additional_context['manifest']
            
            # Look for any file reference in transformation_config
            transformation_config = manifest.get('transformation_config', {})
            if transformation_config:
                for key, value in transformation_config.items():
                    if isinstance(value, str) and (value.endswith('.json') or value.endswith('.csv') or value.endswith('.txt')):
                        # Resolve to full path
                        filename = Path(value).name
                        full_path = str((user_uploads_dir / filename).absolute())
                        file_exists = os.path.exists(full_path)
                        
                        logger.info(f"  Referenced file: {filename}")
                        logger.info(f"  Full path: {full_path}")
                        logger.info(f"  Exists: {file_exists}")
                        
                        if file_exists:
                            prompt_parts.append(f"{key.upper()}_FILE = r\"{full_path}\"")
        
        prompt_parts.append(f"{'='*60}")
        
        # Final instruction - DYNAMIC based on what files exist
        prompt_parts.append("\n\nYOUR TASK:")
        if available_files:
            prompt_parts.append("1. Examine the files listed above in USER_UPLOADS_DIR")
            prompt_parts.append("2. Execute Python code to READ and ANALYZE the relevant file(s)")
            prompt_parts.append("3. Understand the data structure, count items, identify patterns")
            prompt_parts.append(f"4. Save your REAL findings to this ABSOLUTE PATH: {analysis_file_path}")
            prompt_parts.append("5. Set 'analysis_complete': true when done")
            prompt_parts.append("")
            prompt_parts.append("CRITICAL: Use the full path above, not a relative path!")
        else:
            logger.warning("  No files found in user_uploads - Phase 1a may not have data to analyze")
            prompt_parts.append("1. Note: No files found in USER_UPLOADS_DIR")
            prompt_parts.append("2. Check if task requires file analysis or is file-independent")
            prompt_parts.append(f"3. Save your analysis to this ABSOLUTE PATH: {analysis_file_path}")
            prompt_parts.append("4. Set 'analysis_complete': true when done")
        
        conversation_prompt = "\n".join(prompt_parts)
        
        logger.info(f"  Analysis output will be saved to: {analysis_file_path}")
        
        # Loop until Claude sets analysis_complete=True
        max_iterations = 15  # Increased for complex analysis
        
        # Add explicit instruction to write Python code
        first_file = available_files[0] if available_files else "file.csv"
        code_instruction = f"""

CRITICAL INSTRUCTION:
You MUST write Python code to analyze the data and save the JSON file.
Do NOT just describe the analysis - write executable Python code in ```python blocks.

Example:
```python
import pandas as pd
import json

# Load and analyze data
df = pd.read_csv(r'{user_uploads_dir / first_file}')

# Create analysis structure
analysis = {{
    "analysis_complete": True,
    "file_info": {{"filename": "{first_file}", ...}},
    ...
}}

# Save to the EXACT path below
with open(r'{analysis_file_path}', 'w') as f:
    json.dump(analysis, f, indent=2)

print("Analysis saved successfully")
```

Write the code NOW in your next response."""
        
        messages = [UserMessage(content=conversation_prompt + code_instruction, source="system")]
        
        for iteration in range(1, max_iterations + 1):
            logger.info(f"  Analysis iteration {iteration}/{max_iterations}")
            
            try:
                # Call Claude with accumulated conversation history
                response = await self._claude_client.create(
                    messages=messages
                )
                
                response_text = response.content if hasattr(response, 'content') else str(response)
                logger.info(f"  Claude response: {len(response_text)} chars")
                
                # SAVE CLAUDE'S FULL RESPONSE TO FILE
                debug_dir = phase1_dir / "debug_logs"
                debug_dir.mkdir(exist_ok=True)
                
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                response_file = debug_dir / f"iteration_{iteration}_{timestamp}_response.txt"
                with open(response_file, 'w', encoding='utf-8') as f:
                    f.write(f"=== ITERATION {iteration} - CLAUDE RESPONSE ===\n")
                    f.write(f"Timestamp: {timestamp}\n")
                    f.write(f"Length: {len(response_text)} chars\n")
                    f.write(f"\n{'='*80}\n")
                    f.write(response_text)
                logger.info(f"  Saved response to: {response_file.name}")
                
                # Check if Claude generated Python code
                if "```python" in response_text:
                    logger.info("  Executing Claude's code...")
                    code_blocks = self._extract_code_blocks(response_text)
                    
                    if code_blocks:
                        for i, code in enumerate(code_blocks, 1):
                            # SAVE CODE TO FILE
                            code_file = debug_dir / f"iteration_{iteration}_{timestamp}_code_block_{i}.py"
                            with open(code_file, 'w', encoding='utf-8') as f:
                                f.write(f"# Iteration {iteration} - Code Block {i}\n")
                                f.write(f"# Generated at: {timestamp}\n\n")
                                f.write(code)
                            logger.info(f"  Saved code block {i} to: {code_file.name}")
                            
                            result = await self._claude_executor.execute_code_blocks(
                                code_blocks=[CodeBlock(language="python", code=code)],
                                cancellation_token=CancellationToken()
                            )
                            
                            # SAVE FULL EXECUTION OUTPUT TO FILE
                            output_file = debug_dir / f"iteration_{iteration}_{timestamp}_output_block_{i}.txt"
                            with open(output_file, 'w', encoding='utf-8') as f:
                                f.write(f"=== EXECUTION OUTPUT - Iteration {iteration} Block {i} ===\n")
                                f.write(f"Exit Code: {result.exit_code}\n")
                                f.write(f"Output Length: {len(result.output)} chars\n")
                                f.write(f"\n{'='*80}\n")
                                f.write(result.output)
                            logger.info(f"  Saved output to: {output_file.name}")
                            
                            if result.exit_code == 0:
                                logger.info(f"  ✓ Code block {i} succeeded")
                                logger.info(f"  Output preview: {result.output[:200]}...")
                                logger.info(f"  Full output saved to: {output_file.name}")
                            else:
                                logger.warning(f"  ✗ Code block {i} failed (exit {result.exit_code})")
                                logger.warning(f"  Error preview: {result.output[:200]}...")
                                logger.warning(f"  Full error saved to: {output_file.name}")
                        
                        # File check happens after the code execution block
                        # No need to check here - will be checked at line 679-687
                        
                        # Update conversation history with assistant's response and execution output
                        messages.append(AssistantMessage(content=response_text, source="assistant"))
                        
                        # Provide execution feedback to Claude for next iteration
                        feedback = f"Code executed. Output:\n{result.output}\n\nBased on your analysis above, save the REAL data to this ABSOLUTE PATH:\n{analysis_file_path}\n\nSet 'analysis_complete': true when done."
                        messages.append(UserMessage(content=feedback, source="system"))
                
                # Check if structure_analysis.json was created
                # Executor work_dir is now phase1_dir, so file should be in expected location
                if analysis_file_path.exists():
                    logger.info(f"  ✓ Found structure_analysis.json")
                    found_file = analysis_file_path
                else:
                    found_file = None
                
                if found_file:
                    with open(found_file, 'r', encoding='utf-8') as f:
                        analysis_data = json.load(f)
                    
                    # Check the FLAG
                    if analysis_data.get('analysis_complete'):
                        logger.info(f"  ✓✓ FLAG SET! Analysis complete")
                        logger.info(f"  Summary: {analysis_data.get('summary', 'N/A')}")
                        
                        # File is already in the correct location (phase1_dir)
                        # No need to copy since executor work_dir is phase1_dir
                        
                        return analysis_data
                    else:
                        logger.info("  File exists but flag not set, continuing...")
                        conversation_prompt = "Analysis file created but analysis_complete is not True. Please continue or set flag when ready."
                        continue
                
                # No code and no file - be more explicit
                conversation_prompt = f"""You did not generate any Python code in your last response.

REQUIRED: Write Python code in ```python blocks to:
1. Load the CSV file: {user_uploads_dir / first_file}
2. Analyze the data (schema, distributions, correlations)
3. Save analysis to: {analysis_file_path}
4. Set "analysis_complete": true in the JSON

Example structure:
```python
import pandas as pd
import json

df = pd.read_csv(r'{user_uploads_dir / first_file}')

analysis = {{
    "analysis_complete": True,
    "file_info": {{"filename": "{first_file}", "rows": len(df), ...}},
    # ... your analysis ...
}}

with open(r'{analysis_file_path}', 'w') as f:
    json.dump(analysis, f, indent=2)
```

Write the code NOW."""
                
            except Exception as e:
                logger.error(f"  Error in analysis iteration: {e}")
                import traceback
                traceback.print_exc()
                return None
        
        logger.warning("  Max iterations reached without completion flag")
        return None
    
    async def _phase_1b_debate(
        self,
        request: TaskDivisionRequest,
        plan_content: Dict,
        structure_analysis: Dict
    ) -> Optional[Dict]:  # Return raw dict
        """
        Phase 1b: GPT-5 proposes (deep reasoning), Claude reviews (fast validation)
        NO CODE EXECUTION - just use structure_analysis from Phase 1a
        ACCEPTS ANY LOGICAL JSON STRUCTURE
        """
        current_proposal: Optional[Dict] = None
        previous_feedback: Optional[str] = None
        
        for iteration in range(1, self._max_iterations + 1):
            logger.info(f"  Debate iteration {iteration}/{self._max_iterations}")
            
            # GPT-5 proposes (using its reasoning capability)
            logger.info("    GPT-5 proposing...")
            gpt5_proposal = await self._get_gpt5_proposal(
                request, structure_analysis, current_proposal, previous_feedback
            )
            
            if not gpt5_proposal:
                logger.error("    GPT-5 failed to provide proposal")
                break
            
            current_proposal = gpt5_proposal
            
            # Claude reviews (fast validation)
            logger.info("    Claude reviewing...")
            claude_review = await self._get_claude_review(request, structure_analysis, current_proposal)
            
            if not claude_review:
                logger.error("    Claude failed to review")
                break
            
            # Check for approval
            is_approved = claude_review.get('approved') or claude_review.get('satisfied') or claude_review.get('accept')
            if is_approved:
                logger.info(f"  ✓ APPROVED after {iteration} iteration(s)")
                return current_proposal  # Return raw dict directly to Phase 2Z
            
            # Prepare feedback for next iteration
            feedback_raw = claude_review.get('feedback') or claude_review.get('reasoning') or claude_review.get('comments') or "Please revise"
            previous_feedback = str(feedback_raw)  # Convert to string in case it's a dict/list
            
            # Add specific issues if provided
            issues = claude_review.get('issues') or claude_review.get('must_change') or claude_review.get('critical_issues') or []
            if issues and isinstance(issues, list):
                previous_feedback += f"\n\nSPECIFIC ISSUES:\n" + "\n".join(f"- {issue}" for issue in issues)
            
            # Safe slicing - ensure it's a string first
            feedback_preview = str(previous_feedback)[:60] if previous_feedback else "No feedback"
            logger.info(f"    Refining... Feedback: {feedback_preview}...")
        
        # Max iterations reached
        if current_proposal:
            logger.warning("  Max iterations reached, using current proposal anyway")
            return current_proposal  # Return raw dict
        
        return None
    
    async def _get_gpt5_proposal(
        self,
        request: TaskDivisionRequest,
        structure_analysis: Dict,
        previous_proposal: Optional[Dict],  # Accept any JSON structure
        previous_feedback: Optional[str]
    ) -> Optional[Dict]:  # Return raw dict
        """
        GPT-5 creates task division proposal using deep reasoning
        NO CODE EXECUTION - data already analyzed in Phase 1a
        """
        prompt_parts = [self.CLAUDE_PHASE1B_PROPOSAL_PROMPT]  # Will swap prompt next
        
        # === STRUCTURE ANALYSIS (THE REAL DATA!) ===
        prompt_parts.append("\n\n" + "="*60)
        prompt_parts.append("STRUCTURE ANALYSIS FROM PHASE 1A:")
        prompt_parts.append("="*60)
        prompt_parts.append(json.dumps(structure_analysis, indent=2))
        
        # === AVAILABLE FILES FROM CATALOG (REAL PATHS!) ===
        catalog_dir = self._workspace_manager.get_catalog_directory(create=False)
        catalog_path = catalog_dir / "data_catalog.json"
        from ..data_catalog import DataCatalog
        data_catalog = DataCatalog(str(catalog_path))
        
        # Query ALL files from catalog (especially user uploads)
        all_catalog_files = []
        try:
            # Search for common file patterns
            for pattern in ["*"]:  # Get ALL files
                found_files = data_catalog.search_files(name_pattern=pattern)
                if found_files:
                    all_catalog_files.extend(found_files)
            
            if all_catalog_files:
                prompt_parts.append("\n\n" + "="*60)
                prompt_parts.append("AVAILABLE FILES (FROM CATALOG - USE THESE PATHS!):")
                prompt_parts.append("="*60)
                prompt_parts.append("⚠️ CRITICAL: Use these EXACT file paths in your work_scope")
                prompt_parts.append("DO NOT invent paths like /app/..., /tmp/..., etc.")
                prompt_parts.append("")
                for f in all_catalog_files:
                    prompt_parts.append(f"File: {f['name']}")
                    prompt_parts.append(f"  Path: {f['path']}")
                    prompt_parts.append(f"  Size: {f.get('size_bytes', 0):,} bytes")
                    prompt_parts.append(f"  Source: {f.get('task_id', 'unknown')}")
                    prompt_parts.append("")
                logger.info(f"  Providing {len(all_catalog_files)} file paths to Claude for task division")
        except Exception as e:
            logger.warning(f"  Could not query catalog: {e}")
        
        # === PHASE 0 INSTRUCTIONS (Everything you need to know) ===
        if request.additional_context and request.additional_context.get('core_tasks'):
            prompt_parts.append("\n\n" + "="*60)
            prompt_parts.append("PHASE 0 CLASSIFICATION RESULT:")
            prompt_parts.append("="*60)
            prompt_parts.append("Phase 0 analyzed the full requirements and determined:")
            prompt_parts.append(json.dumps(request.additional_context['core_tasks'], indent=2))
        
        # === TASK TO DIVIDE ===
        prompt_parts.append("\n\n" + "="*60)
        prompt_parts.append("YOUR TASK:")
        prompt_parts.append("="*60)
        prompt_parts.append(request.core_task_description)
        prompt_parts.append("\nNote: Phase 0 has already analyzed all requirements. Follow the classification above.")
        
        # === FEEDBACK FROM PREVIOUS ITERATION ===
        if previous_proposal and previous_feedback:
            prompt_parts.append("\n\n" + "="*60)
            prompt_parts.append("YOUR PREVIOUS PROPOSAL:")
            prompt_parts.append("="*60)
            prompt_parts.append(json.dumps(previous_proposal, indent=2))  # Raw dict
            prompt_parts.append("\n\nGPT-5'S FEEDBACK:")
            prompt_parts.append(previous_feedback)
            prompt_parts.append("\n\nPlease refine your proposal.")
        
        prompt_parts.append("\n\nProvide your JSON proposal now:")
        
        full_prompt = "\n".join(prompt_parts)
        
        try:
            # Import Pydantic model for structured output
            from .task_models import TaskDivisionProposal
            
            # Use Pydantic structured output to force valid JSON
            response = await self._gpt5_client.create(
                messages=[UserMessage(content=full_prompt, source="system")],
                json_output=TaskDivisionProposal  # Force structured output
            )
            
            # DEBUG: Save GPT-5's response
            phase1_dir = self._workspace_manager.get_phase_directory('phase1', create=True)
            debug_dir = phase1_dir / "debug_logs"
            debug_dir.mkdir(exist_ok=True)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            
            # Extract the structured response
            if hasattr(response, 'content'):
                response_text = response.content
            else:
                response_text = str(response)
            
            # Save raw response for debugging
            proposal_file = debug_dir / f"phase1b_gpt5_proposal_{timestamp}.txt"
            with open(proposal_file, 'w', encoding='utf-8') as f:
                f.write(f"=== GPT-5'S PHASE 1B PROPOSAL (STRUCTURED OUTPUT) ===\n")
                f.write(f"Timestamp: {timestamp}\n")
                f.write(f"Length: {len(response_text)} chars\n\n")
                f.write("="*80 + "\n")
                f.write(response_text)
            logger.info(f"    Saved GPT-5 proposal to: {proposal_file.name}")
            
            # Parse JSON from structured output
            try:
                proposal_dict = json.loads(response_text)
            except json.JSONDecodeError as e:
                logger.error(f"    JSON decode error: {e}")
                # Try to extract JSON from response
                proposal_dict = self._extract_json_from_response(response_text)
                if not proposal_dict:
                    logger.error("    Failed to extract JSON from GPT-5")
                    return None
            
            # DEBUG: Save extracted JSON
            json_file = debug_dir / f"phase1b_extracted_json_{timestamp}.json"
            with open(json_file, 'w', encoding='utf-8') as f:
                json.dump(proposal_dict, f, indent=2)
            logger.info(f"    Saved extracted JSON to: {json_file.name}")
            
            # Validate with Pydantic model
            validated_proposal = self._validate_proposal_with_pydantic(proposal_dict)
            if validated_proposal:
                logger.info(f"    ✓ GPT-5 proposal validated with Pydantic")
                # Convert back to dict for compatibility
                proposal_dict = validated_proposal.model_dump()
            else:
                logger.warning("    ⚠️ Pydantic validation failed, using raw JSON")
            
            logger.info(f"    ✓ GPT-5 proposal received: {len(str(proposal_dict))} chars")
            return proposal_dict  # Return raw dict, not Pydantic model
            
        except Exception as e:
            logger.error(f"    Error getting GPT-5 proposal: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    async def _get_claude_review(
        self,
        request: TaskDivisionRequest,
        structure_analysis: Dict,
        proposal: Dict  # Accept any JSON structure
    ) -> Optional[Dict]:  # Return raw dict
        """Claude reviews GPT-5's proposal"""
        prompt_parts = [self.GPT5_PHASE1B_REVIEW_PROMPT]  # Will swap prompt next
        
        prompt_parts.append("\n\n" + "="*60)
        prompt_parts.append("STRUCTURE ANALYSIS (for reference):")
        prompt_parts.append("="*60)
        prompt_parts.append(json.dumps(structure_analysis, indent=2))
        
        # === PHASE 0 INSTRUCTIONS (same as GPT-5 sees) ===
        if request.additional_context and request.additional_context.get('core_tasks'):
            prompt_parts.append("\n\n" + "="*60)
            prompt_parts.append("PHASE 0 CLASSIFICATION RESULT:")
            prompt_parts.append("="*60)
            prompt_parts.append("Phase 0 analyzed the full requirements and determined:")
            prompt_parts.append(json.dumps(request.additional_context['core_tasks'], indent=2))
            prompt_parts.append("\nNote: Phase 0 already analyzed all requirements - this is what you should validate against.")
        
        prompt_parts.append("\n\n" + "="*60)
        prompt_parts.append("GPT-5'S PROPOSAL TO REVIEW:")
        prompt_parts.append("="*60)
        prompt_parts.append(json.dumps(proposal, indent=2))  # Raw dict
        
        prompt_parts.append("\n\nProvide your review (JSON):")
        
        full_prompt = "\n".join(prompt_parts)
        
        try:
            response = await self._claude_client.create(
                messages=[UserMessage(content=full_prompt, source="system")]
            )
            
            response_text = response.content if hasattr(response, 'content') else str(response)
            
            # DEBUG: Save Claude's review
            phase1_dir = self._workspace_manager.get_phase_directory('phase1', create=True)
            debug_dir = phase1_dir / "debug_logs"
            debug_dir.mkdir(exist_ok=True)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            review_file = debug_dir / f"phase1b_claude_review_{timestamp}.txt"
            with open(review_file, 'w', encoding='utf-8') as f:
                f.write(f"=== CLAUDE'S PHASE 1B REVIEW ===\n")
                f.write(f"Timestamp: {timestamp}\n")
                f.write(f"Length: {len(response_text)} chars\n\n")
                f.write("="*80 + "\n")
                f.write(response_text)
            logger.info(f"    Saved Claude review to: {review_file.name}")
            
            review_dict = self._extract_json_from_response(response_text)
            if not review_dict:
                logger.error("    Failed to extract JSON from Claude")
                return None
            
            # DEBUG: Save extracted review JSON
            review_json_file = debug_dir / f"phase1b_claude_review_json_{timestamp}.json"
            with open(review_json_file, 'w', encoding='utf-8') as f:
                json.dump(review_dict, f, indent=2)
            logger.info(f"    Saved Claude review JSON to: {review_json_file.name}")
            
            # NO VALIDATION - accept any logical review structure
            # Just check if Claude is satisfied (flexible field names)
            is_satisfied = review_dict.get('satisfied') or review_dict.get('approved') or review_dict.get('accept')
            logger.info(f"    ✓ Claude {'APPROVED' if is_satisfied else 'REJECTED'}")
            return review_dict  # Return raw dict
            
        except Exception as e:
            logger.error(f"    Error getting Claude review: {e}")
            return None
    
    # ================================================================
    # HELPER METHODS
    # ================================================================
    
    def _extract_code_blocks(self, response_text: str) -> List[str]:
        """Extract Python code blocks from markdown"""
        pattern = r'```python\s*(.*?)```'
        matches = re.findall(pattern, response_text, re.DOTALL)
        return [m.strip() for m in matches if m.strip()]
    
    def _extract_json_from_response(self, response_text: str) -> Optional[Dict]:
        """Extract JSON from LLM response using Pydantic validation"""
        # Try direct JSON parsing first
        try:
            parsed = json.loads(response_text)
            return parsed
        except json.JSONDecodeError:
            pass
        
        # Try markdown code block
        json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response_text, re.DOTALL)
        if json_match:
            try:
                json_str = json_match.group(1)
                parsed = json.loads(json_str)
                return parsed
            except json.JSONDecodeError:
                pass
        
        # Try to find any JSON object
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if json_match:
            try:
                json_str = json_match.group(0)
                parsed = json.loads(json_str)
                return parsed
            except json.JSONDecodeError:
                pass
        
        logger.error(f"Could not extract JSON from: {response_text[:200]}...")
        return None
    
    def _validate_proposal_with_pydantic(self, proposal_dict: Dict) -> Optional[PydanticTaskDivisionProposal]:
        """Validate and parse proposal using Pydantic model"""
        try:
            # Use Pydantic model for validation and parsing
            proposal = PydanticTaskDivisionProposal.model_validate(proposal_dict)
            logger.info("✅ Proposal validated with Pydantic model")
            return proposal
        except Exception as e:
            logger.warning(f"Pydantic validation failed: {e}")
            # Fall back to original dict
            return None
    
    def _validate_review_with_pydantic(self, review_dict: Dict) -> Optional[PydanticReviewResult]:
        """Validate and parse review using Pydantic model"""
        try:
            # Use Pydantic model for validation and parsing
            review = PydanticReviewResult.model_validate(review_dict)
            logger.info("✅ Review validated with Pydantic model")
            return review
        except Exception as e:
            logger.warning(f"Pydantic review validation failed: {e}")
            # Fall back to original dict
            return None
    
    def _build_result(
        self,
        task_id: str,
        proposal: TaskDivisionProposal
    ) -> TaskDivisionResult:
        """Build TaskDivisionResult from proposal"""
        subtasks = []
        for st in proposal.subtasks:
            subtasks.append(Subtask(
                id=st["id"],
                description=st["description"],
                task_category=st.get("task_category", "independent"),
                dependencies=st.get("dependencies", []),
                estimated_duration=st.get("estimated_duration", "medium"),
                complexity=st.get("complexity", "moderate"),
                inputs_required=st.get("inputs_required", {}),
                outputs_produced=st.get("outputs_produced", []),
                expected_output_files=st.get("expected_output_files", []),  # NEW: Parse contract files
                chain_ids=st.get("chain_ids", []),
                columns_needed=st.get("columns_needed", [])
            ))
        
        return TaskDivisionResult(
            task_id=task_id,
            can_be_divided=proposal.can_be_divided,
            reasoning=proposal.reasoning,
            subtasks=subtasks,
            execution_strategy=proposal.execution_strategy,
            estimated_total_duration=proposal.estimated_total_duration,
            confidence=0.9,
            warnings=[]
        )
    
    async def _generate_packages(
        self,
        request: TaskDivisionRequest,
        result: TaskDivisionResult,
        output_dir: Optional[Path]
    ) -> List[Path]:
        """Generate JSON packages for Phase 2"""
        if not output_dir:
            phase1_dir = self._workspace_manager.get_phase_directory('phase1', create=True)
            output_dir = phase1_dir / 'packages'
        
        output_dir.mkdir(parents=True, exist_ok=True)
        
        plan_content = self._load_plan(request)
        all_chains = plan_content.get("transformation_chains", [])
        
        # Re-initialize catalog to look up file paths
        # (Catalog from main flow is not accessible here)
        run_dir = self._workspace_manager.run_dir
        catalog_dir = self._workspace_manager.get_catalog_directory(create=False)
        catalog_path = catalog_dir / "data_catalog.json"
        from ..data_catalog import DataCatalog
        data_catalog = DataCatalog(str(catalog_path))
        
        package_files = []
        
        for subtask in result.subtasks:
            # Provide catalog information to ALL tasks
            # Tasks can query catalog at runtime if they need to find files
            task_data = {
                "catalog_location": str(catalog_path),
                "catalog_note": "Query catalog at runtime if you have file location issues - it tracks all files with full paths"
            }
            
            # Optionally provide file paths if they're already in catalog (helps but not required)
            try:
                all_files = data_catalog.search_files(name_pattern="*")
                if all_files:
                    task_data["available_files"] = {
                        f['name']: f['path'] for f in all_files
                    }
                    logger.info(f"  Providing {len(all_files)} file paths to {subtask.id} (catalog accessible for more)")
            except Exception as e:
                logger.debug(f"  Could not pre-load file paths for {subtask.id}: {e}")
            
            # Pass metadata about transformations if present (for context, not parsing)
            all_chains = plan_content.get("transformation_chains", [])
            if all_chains:
                task_data["transformation_metadata"] = {
                    "chains_count": len(all_chains),
                    "summary": f"{len(all_chains)} operations defined in instruction file"
                }
                logger.info(f"  Transformation metadata available for {subtask.id}")
            
            # Get input files from dependencies
            input_files = {}
            input_file_paths = []
            
            if subtask.dependencies:
                # Has dependencies - will get files from previous tasks
                for dep_id in subtask.dependencies:
                    dep_subtask = next((s for s in result.subtasks if s.id == dep_id), None)
                    if dep_subtask and dep_subtask.outputs_produced:
                        input_files[dep_id] = dep_subtask.outputs_produced[0]
            else:
                # No dependencies - this is an initial task, provide user_uploads files
                user_uploads_dir = self._workspace_manager.get_user_uploads_directory(create=False)
                if user_uploads_dir.exists():
                    # Get all files from user_uploads (not just CSV)
                    all_files = [f for f in user_uploads_dir.glob("*") if f.is_file()]
                    input_file_paths = [str(f.absolute()) for f in all_files]
                    logger.info(f"  Task {subtask.id} (no deps): providing {len(input_file_paths)} user_uploads file(s)")
            
            # Extract credentials (all available)
            credentials = self._extract_credentials(request.additional_context)
            
            # Parse execution hints from manifest
            from shared.models import ExecutionHints
            exec_hints = ExecutionHints()
            if request.additional_context:
                manifest = request.additional_context.get('manifest', {})
                transformation_config = manifest.get('transformation_config', {})
                if transformation_config.get('zero_copy_mode', False):
                    exec_hints.materialize_mode = "none"
                elif transformation_config.get('use_links', False):
                    exec_hints.materialize_mode = "link"
            
            package = SubtaskPackage(
                subtask_id=subtask.id,
                description=subtask.description,
                task_category=subtask.task_category,
                dependencies=subtask.dependencies,
                complexity=subtask.complexity,
                estimated_duration=subtask.estimated_duration,
                credentials=credentials,
                data=task_data,
                task_instructions="",
                success_criteria=request.success_criteria or "Complete successfully",
                columns_needed=subtask.columns_needed,
                inputs_required=subtask.inputs_required,
                outputs_produced=subtask.outputs_produced,
                expected_output_files=subtask.expected_output_files,  # NEW: Pass through contract
                output_contract=subtask.output_contract,  # NEW: Pass through rich contract
                input_files=input_files,
                output_files=subtask.outputs_produced,
                input_artifacts={},  # NEW: Will be populated by orchestrator
                execution_hints=exec_hints,  # NEW: Typed execution hints
                input_file_paths=input_file_paths if input_file_paths else None  # NEW: Absolute paths to input files
            )
            
            # Save package
            package_file = output_dir / f"{subtask.id}.json"
            with open(package_file, 'w', encoding='utf-8') as f:
                json.dump(package.model_dump(), f, indent=2)
            
            logger.info(f"  Created: {package_file.name}")
            package_files.append(package_file)
        
        return package_files
    
    def _load_plan(self, request: TaskDivisionRequest) -> Dict:
        """Load plan content"""
        if request.plan_content:
            return request.plan_content
        
        if request.plan_file_path:
            try:
                with open(request.plan_file_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to load plan: {e}")
        
        return {}
    
    def _extract_all_credentials(self, request: TaskDivisionRequest) -> Dict[str, Any]:
        """
        Extract ALL credentials from manifest - TRULY GENERAL
        Recursively searches for any objects with credential-like fields
        
        Handles any manifest structure:
        - Nested credentials (input_data.source_database, config.db.primary, etc.)
        - Top-level credentials
        - Multiple sources/targets with any naming
        - API keys, secrets, tokens
        """
        credentials = {}
        
        if not request.additional_context or not request.additional_context.get('manifest'):
            return credentials
        
        manifest = request.additional_context['manifest']
        
        # Credential indicator fields
        cred_indicators = ['host', 'server', 'api_key', 'password', 'token', 'secret', 
                          'access_key', 'username', 'user', 'connection_string', 'endpoint']
        
        def extract_recursive(obj, path=""):
            """Recursively search for credential objects at any nesting level"""
            if isinstance(obj, dict):
                # Check if this dict itself has credential fields
                has_creds = any(key in obj for key in cred_indicators)
                
                if has_creds:
                    # This object contains credentials - extract it
                    # Use the last component of the path as the key
                    key_name = path.split('.')[-1] if path else 'credentials'
                    credentials[key_name] = obj
                else:
                    # No credentials here, recurse into nested objects
                    for key, value in obj.items():
                        new_path = f"{path}.{key}" if path else key
                        extract_recursive(value, new_path)
            elif isinstance(obj, list):
                # Search in list items
                for i, item in enumerate(obj):
                    extract_recursive(item, f"{path}[{i}]")
        
        # Start recursive extraction from manifest root
        extract_recursive(manifest)
        
        # Also check dedicated top-level sections (if not already found)
        if 'credentials' in manifest and 'credentials' not in credentials:
            credentials['credentials'] = manifest['credentials']
        if 'connections' in manifest and 'connections' not in credentials:
            credentials['connections'] = manifest['connections']
        
        return credentials
    
    def _create_fallback_result(self, task_id: str) -> TaskDivisionResult:
        """Fallback when division fails"""
        return TaskDivisionResult(
            task_id=task_id,
            can_be_divided=False,
            reasoning="Division failed",
            subtasks=[],
            execution_strategy="sequential",
            confidence=0.0,
            warnings=["Division failed"]
        )
