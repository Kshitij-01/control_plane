# Autonomous Agent System - How It Works

**Generated:** 2025-10-20  
**Purpose:** Detailed explanation of system operation with code examples and workflow

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Complete Execution Flow](#complete-execution-flow)
3. [Phase 0: Task Classification](#phase-0-task-classification)
4. [Phase 1: Task Division](#phase-1-task-division)
5. [Phase 2: Task Execution](#phase-2-task-execution)
6. [Boss-Worker Communication Protocol](#boss-worker-communication-protocol)
7. [Knowledge & Memory System](#knowledge--memory-system)
8. [Code Execution Mechanism](#code-execution-mechanism)
9. [Retry and Recovery Logic](#retry-and-recovery-logic)
10. [File Catalog and Path Resolution](#file-catalog-and-path-resolution)
11. [Example Walkthrough](#example-walkthrough)

---

## System Overview

### Architecture Diagram

```
User Manifest
     |
     v
run_control_plane.py (Main Entry Point)
     |
     +---> Phase 0: Classification (Claude + GPT-5)
     |       |
     |       +---> TaskClassifier
     |       |       +---> ClaudeTaskUnderstander (Initial Analysis)
     |       |       +---> GPT5TaskUnderstander (Review & Refine)
     |       |       +---> TaskNegotiator (Resolve Conflicts)
     |       |       +---> OverseerAgent (Quality Control)
     |       |
     |       +---> SideTaskSolver (Validate Prerequisites)
     |               +---> AgentFactory (Generate Specialized Agents)
     |
     +---> Phase 1: Division (Claude + GPT-5)
     |       |
     |       +---> CollaborativeTaskDivider
     |               +---> Claude Proposes Task Breakdown
     |               +---> GPT-5 Reviews & Refines
     |               +---> Negotiation if Needed
     |               +---> Overseer Validates
     |
     +---> Phase 2: Execution (Boss-Worker Pairs)
             |
             +---> BossWorkerOrchestrator
                     |
                     +---> For Each Task:
                           |
                           +---> Boss Agent (GPT-5)
                           |       +---> Plans Subtasks
                           |       +---> Delegates to Worker
                           |       +---> Verifies Results
                           |       +---> Adjusts Plan if Needed
                           |
                           +---> Worker Agent (Claude 4.5)
                                   +---> Generates Code
                                   +---> Executes Code
                                   +---> Self-Verifies
                                   +---> Retries (up to 15x)
```

### Key Design Principles

1. **Collaborative Intelligence**: Multiple LLMs work together, each contributing their strengths
2. **Autonomous Retry**: Agents learn from failures and retry automatically
3. **Explicit Contracts**: Boss specifies exact expected outputs, Worker verifies against them
4. **Deep Validation**: Boss generates custom verification code for quality assurance
5. **Knowledge Accumulation**: All outputs indexed for semantic search by future tasks

---

## Complete Execution Flow

### Step-by-Step Process

```python
# File: control_plane_v2/run_control_plane.py

async def main():
    # 1. SETUP (Lines 263-341)
    # - Load manifest JSON
    # - Load env_info.json with API keys
    # - Create run directory (runs/run_YYYYMMDD_HHMMSS/)
    # - Copy user files to user_uploads/
    
    workspace_manager = WorkspaceManager()
    run_dir = workspace_manager.create_run_directory()
    
    # Handle user_uploads array from manifest
    if "user_uploads" in manifest:
        for upload_item in manifest["user_uploads"]:
            source_path = project_root / upload_item["source"]
            target_filename = upload_item["filename"]
            shutil.copy2(source_path, run_uploads / target_filename)
    
    # 2. CREATE LLM CLIENTS (Lines 376-393)
    # - Claude 4.5 Sonnet (code generation)
    # - GPT-5 o1-preview (planning & verification)
    # - GPT-4 Turbo (fallback)
    
    clients = create_all_model_clients(env_config)
    
    # 3. CREATE KNOWLEDGE SYSTEMS (Lines 394-407)
    # - DataCatalog: Structured file metadata
    # - AzureOpenAIRAGMemory: Semantic search
    
    knowledge_systems = {
        "catalog": DataCatalog(catalog_path),
        "rag_memory": AzureOpenAIRAGMemory(...)
    }
    
    # 4. PHASE 0: CLASSIFICATION (Lines 410-505)
    classification_result = await classifier.classify_task(request)
    # Output: core_tasks, side_tasks, execution_order
    
    # Execute side tasks (connection validation, etc.)
    if not skip_side_tasks:
        await solver.solve_all_tasks(side_tasks)
    
    # 5. PHASE 1: DIVISION (Lines 508-608)
    division_result = await divider.divide_task(request)
    # Output: execution_plan.json with task breakdown
    
    # 6. PHASE 2: EXECUTION (Lines 610-733)
    orchestrator = BossWorkerOrchestrator(...)
    results = await orchestrator.execute_all_tasks()
    # Output: Task-specific outputs + file_catalog.json
```

---

## Phase 0: Task Classification

### Purpose
Understand the task, classify it, and validate prerequisites (connections, files, credentials).

### Workflow

```python
# File: control_plane_v2/phase_0/task_classifier.py

class TaskClassifier:
    async def classify_task(self, request: TaskAnalysisRequest) -> TaskClassification:
        """
        Collaborative classification using Claude, GPT-5, and Overseer
        """
        
        # STEP 1: Claude's Initial Analysis (Lines 47-88)
        # - Analyzes task description and manifest
        # - Identifies core tasks (actual work)
        # - Identifies side tasks (prerequisites)
        # - Checks transformation_config.skip_side_tasks
        
        claude_result = await self._get_claude_analysis(request)
        
        # STEP 2: GPT-5 Review (Lines 90-131)
        # - Reviews Claude's analysis
        # - Refines task breakdown
        # - Checks for missing prerequisites
        
        gpt5_result = await self._get_gpt5_review(request, claude_result)
        
        # STEP 3: Negotiation if Disagreement (Lines 133-180)
        # - If Claude and GPT-5 disagree significantly
        # - Negotiator agent resolves conflicts
        # - Up to 3 negotiation rounds
        
        if self._significant_disagreement(claude_result, gpt5_result):
            negotiated_result = await self._negotiate(...)
        
        # STEP 4: Overseer Quality Control (Lines 182-230)
        # - Final validation of classification
        # - Ensures all prerequisites identified
        # - Up to 5 overseer iterations
        
        final_result = await self._overseer_review(negotiated_result)
        
        return final_result
```

### Claude's Classification Logic

```python
# File: control_plane_v2/phase_0/task_understanders/claude_understander.py

# System Prompt (Lines 30-142)
"""
SIDE TASKS = PREREQUISITES (System checks only):
- Can we connect to database X?
- Does file Y exist?
- Is library W installed?

ABSOLUTELY FORBIDDEN IN SIDE TASKS:
- Checking specific columns exist
- Validating schemas
- Checking permissions
- Any analysis of data content

CORE TASKS = THE ACTUAL WORK:
- Migrate data
- Transform files
- Train model
- Whatever the user asked for

SKIP_SIDE_TASKS HANDLING:
- If transformation_config.skip_side_tasks == true: Return "side_tasks": []
"""

# Example Output:
{
  "core_tasks": [
    {
      "id": "core_1",
      "description": "Analyze genomics tar.gz file structure and data",
      "subtasks": ["Extract files", "Profile data", "Generate report"],
      "can_be_divided": true
    }
  ],
  "side_tasks": [],  # Empty if skip_side_tasks=true
  "execution_order": ["core_1"]
}
```

### Side Task Execution

```python
# File: control_plane_v2/phase_0/side_task_solver.py

class SideTaskSolver:
    async def solve_all_tasks(self, side_tasks: List[SideTask]):
        """
        Execute all side tasks using dynamically generated agents
        """
        
        for task in side_tasks:
            # 1. Generate specialized agent for this task
            agent_request = AgentGenerationRequest(
                task_description=task.description,
                task_type="validation",
                credentials=task.credentials
            )
            
            agent_result = await self.agent_factory.generate_agent(agent_request)
            
            # 2. Execute the agent
            exec_result = await self.agent_factory.execute_agent(
                agent_id=agent_result.agent_id,
                workspace_path=task_workspace
            )
            
            # 3. Store result
            task.result = exec_result
```

---

## Phase 1: Task Division

### Purpose
Break down classified tasks into executable subtasks with dependencies.

### Workflow

```python
# File: control_plane_v2/phase_1/collaborative_divider_v2.py

class CollaborativeTaskDivider:
    async def divide_task(self, request: TaskDivisionRequest) -> TaskDivisionResult:
        """
        Collaborative task division using Claude and GPT-5
        """
        
        # STEP 1: Structure Analysis (Lines 300-400)
        # - Claude analyzes input files/data
        # - Generates structure_analysis.json
        # - Understands data schema, size, complexity
        
        structure_analysis = await self._analyze_structure(request)
        
        # STEP 2: Claude Proposes Division (Lines 450-550)
        # - Reads structure_analysis.json
        # - Creates task breakdown:
        #   - sequential_tasks: Must run first, in order
        #   - parallel_tasks: Can run simultaneously
        #   - merge_tasks: Combine parallel results
        #   - final_tasks: Validation, reporting
        
        claude_proposal = await self._get_claude_proposal(
            request, 
            structure_analysis
        )
        
        # STEP 3: GPT-5 Reviews (Lines 600-700)
        # - Reviews Claude's proposal
        # - Checks for logical errors
        # - Validates dependencies
        # - Suggests improvements
        
        gpt5_review = await self._get_gpt5_review(
            request,
            claude_proposal,
            structure_analysis
        )
        
        # STEP 4: Negotiation if Needed (Lines 750-850)
        # - If GPT-5 rejects or suggests major changes
        # - Up to 15 negotiation rounds
        
        if gpt5_review.status == "reject":
            final_plan = await self._negotiate(...)
        else:
            final_plan = claude_proposal
        
        # STEP 5: Overseer Validation (Lines 900-1000)
        # - Final quality check
        # - Ensures plan is executable
        
        validated_plan = await self._overseer_validate(final_plan)
        
        # STEP 6: Save Execution Plan (Lines 1050-1100)
        # - Write to phase1/execution_plan.json
        
        self._save_execution_plan(validated_plan)
        
        return validated_plan
```

### Task Breakdown Structure

```python
# Example execution_plan.json

{
  "metadata": {
    "created_at": "2025-10-20T00:06:13",
    "task_description": "Deep genomics analysis"
  },
  "task_breakdown": {
    "sequential_tasks": [
      {
        "task_id": "init_extract_catalog",
        "description": "Extract tar.gz and catalog files",
        "work_scope": {
          "inputs": ["user_uploads/brca_tcga.tar.gz"],
          "outputs": ["outputs/file_manifest.json"]
        },
        "dependencies": [],
        "expected_output_files": ["outputs/file_manifest.json"]
      }
    ],
    "parallel_tasks": [
      {
        "task_id": "profile_clinical_data",
        "description": "Profile clinical data files",
        "dependencies": ["init_extract_catalog"],
        "expected_output_files": ["outputs/clinical_profile.json"]
      },
      {
        "task_id": "profile_mutations",
        "description": "Profile mutation data",
        "dependencies": ["init_extract_catalog"],
        "expected_output_files": ["outputs/mutation_profile.json"]
      }
    ],
    "merge_tasks": [
      {
        "task_id": "consolidate_analysis",
        "description": "Merge all profiles",
        "dependencies": ["profile_clinical_data", "profile_mutations"],
        "expected_output_files": ["outputs/analysis_catalog.json"]
      }
    ],
    "final_tasks": [
      {
        "task_id": "report_and_visualizations",
        "description": "Generate final report with plots",
        "dependencies": ["consolidate_analysis"],
        "expected_output_files": [
          "outputs/brca_tcga_report.md",
          "outputs/figures/coverage_heatmap.png"
        ]
      }
    ]
  }
}
```

### Claude's Division Prompt (Key Points)

```python
# File: control_plane_v2/phase_1/collaborative_divider_v2.py (Lines 100-220)

"""
EACH TASK WILL BE EXECUTED BY AN INDEPENDENT AI AGENT.

This means:
- Each task description must be SELF-CONTAINED and COMPLETE
- Each agent will read ONLY their task
- Each agent needs ALL context and instructions
- Dependencies must be EXPLICIT
- File references must be CLEAR

COST EFFICIENCY:
- Aim for 5-10 tasks for most projects
- Combine related work into single tasks
- Use parallel tasks ONLY when truly independent
- Don't create 20+ tasks unless required

GUIDANCE ON INSTRUCTION FILES:
- DO NOT try to parse or summarize instructions
- INSTEAD: Tell the agent HOW to extract the relevant part
- Example: "Read <file>, extract <section>, apply those"

GUIDANCE ON FILE PATHS:
- Use RELATIVE paths (e.g., 'outputs/result.json')
- File catalog will resolve to absolute paths
- Makes tasks portable and easier to understand
"""
```

---

## Phase 2: Task Execution

### Purpose
Execute subtasks using autonomous Boss-Worker agent pairs.

### Orchestrator Workflow

```python
# File: control_plane_v2/phase_2/orchestrator_boss_worker.py

class BossWorkerOrchestrator:
    async def execute_all_tasks(self):
        """
        Execute all tasks from execution plan
        """
        
        # Load execution plan (Lines 116-134)
        with open(self.execution_plan_path, 'r') as f:
            execution_plan = json.load(f)
        
        # Extract tasks in order (Lines 119-132)
        tasks = (
            execution_plan['task_breakdown']['sequential_tasks'] +
            execution_plan['task_breakdown']['parallel_tasks'] +
            execution_plan['task_breakdown']['merge_tasks'] +
            execution_plan['task_breakdown']['final_tasks']
        )
        
        # Execute each task sequentially (Lines 136-189)
        for task in tasks:
            result = await self.execute_task(task)
            self.task_results[task_id] = result
    
    async def execute_task(self, task: Dict[str, Any]):
        """
        Execute single task using Boss-Worker pair
        """
        
        # 1. Prepare workspace (Lines 214-216)
        task_workspace = self.phase2_dir / task_id
        task_workspace.mkdir(parents=True, exist_ok=True)
        
        # 2. Extract input files (Lines 218-234)
        input_file_names = []
        for file_item in task['input_files']:
            input_file_names.append(file_item)
        
        # 3. Create Boss-Worker pair (Lines 236-246)
        boss_topic, worker_topic = await self.factory.create_boss_worker_pair(
            run_id=task_id,
            workspace_path=task_workspace,
            knowledge_systems=self.knowledge_systems,
            gpt5_client=self.gpt5_client,
            claude_client=self.claude_client
        )
        
        # 4. Send TaskMessage to Boss (Lines 260-290)
        task_message = TaskMessage(
            task_id=task_id,
            task_description=task['description'],
            input_files=input_file_names,
            expected_outputs=task['expected_output_files'],
            context={
                "work_scope": task.get('work_scope', {}),
                "dependencies": task.get('dependencies', []),
                "metadata": execution_plan.get('metadata', {})
            }
        )
        
        await self.runtime.publish_message(task_message, topic_id=boss_topic)
        
        # 5. Wait for completion (Lines 300-350)
        # Boss will work with Worker and eventually send TaskCompletionMessage
        
        completion_event = asyncio.Event()
        # ... wait for completion ...
        
        # 6. Update catalog (Lines 360-400)
        for file_info in result['files_created']:
            self.knowledge_systems['catalog'].register_file(
                file_id=file_info['filename'],
                task_id=task_id,
                absolute_path=file_info['absolute_path']
            )
        
        return result
```

---

## Boss-Worker Communication Protocol

### Boss Agent (GPT-5) Workflow

```python
# File: control_plane_v2/phase_2/boss_agent_autonomous.py

class BossAgent(RoutedAgent):
    """
    Autonomous Boss powered by GPT-5
    Plans, delegates, verifies, adjusts
    """
    
    @message_handler
    async def handle_task(self, message: TaskMessage, ctx: MessageContext):
        """
        Main task handling workflow
        """
        
        # STEP 1: PLANNING (Lines 400-500)
        # Boss generates subtask breakdown
        
        subtasks = await self._plan_subtasks(message)
        
        # Example subtasks:
        # [
        #   {
        #     "id": "subtask_1_extract_data",
        #     "description": "Extract and catalog files",
        #     "instructions": "1. Extract tar.gz\n2. Catalog all files...",
        #     "input_files": ["user_uploads/data.tar.gz"],
        #     "expected_outputs": ["outputs/file_manifest.json"]
        #   },
        #   {
        #     "id": "subtask_2_profile_data",
        #     "description": "Profile extracted data",
        #     "instructions": "1. Read file_manifest.json\n2. Profile each file...",
        #     "input_files": ["outputs/file_manifest.json"],
        #     "expected_outputs": ["outputs/data_profile.json"]
        #   }
        # ]
        
        # STEP 2: DELEGATION (Lines 550-600)
        # For each subtask, send SubtaskMessage to Worker
        
        for subtask in subtasks:
            subtask_message = SubtaskMessage(
                subtask_id=subtask['id'],
                subtask_description=subtask['description'],
                input_files=subtask['input_files'],
                instructions=subtask['instructions'],
                parent_task_id=message.task_id,
                expected_outputs=subtask['expected_outputs']  # CRITICAL
            )
            
            await self.publish_message(
                subtask_message,
                topic_id=TopicId(self.worker_topic_type, self.agent_id)
            )
        
        # STEP 3: WAIT FOR WORKER COMPLETION (Lines 650-700)
        # Worker sends SubtaskCompletionMessage
        
        @message_handler
        async def handle_completion(
            self, 
            message: SubtaskCompletionMessage, 
            ctx: MessageContext
        ):
            """
            Worker reported completion
            """
            
            if message.gave_up:
                # Worker gave up - re-plan or fail
                await self._handle_worker_gave_up(message)
                return
            
            # STEP 4: VERIFICATION (Lines 750-850)
            # Boss generates verification code
            
            verification_passed = await self._verify_worker_output(message)
            
            if not verification_passed:
                # STEP 5: ADJUSTMENT (Lines 900-950)
                # Boss re-delegates or adjusts plan
                await self._adjust_plan(message)
            else:
                # Success - move to next subtask
                await self._proceed_to_next_subtask()
    
    async def _verify_worker_output(self, message: SubtaskCompletionMessage):
        """
        Generate and run verification code
        """
        
        # STEP 4A: Generate Verification Code (Lines 600-650)
        # Boss asks GPT-5 to generate Python code to verify outputs
        
        verification_prompt = f"""
        Worker completed: {message.subtask_id}
        Worker created: {message.files_created}
        Expected outputs: {self.current_subtask['expected_outputs']}
        
        Generate Python code to verify:
        1. All expected files exist
        2. Files are non-empty
        3. For JSON: valid and contains data
        4. For reports: check for placeholders, empty sections
        
        CRITICAL - DEEP VALIDATION FOR REPORTS:
        - Check file contains ACTUAL DATA, not placeholders
        - Verify key metrics are populated (not "N/A", "TODO", etc.)
        - For HTML reports: check overview sections have real values
        - Reject if critical metrics are zero or null
        
        Return only Python code.
        """
        
        verification_code = await self.model_client.create([
            SystemMessage(content="Generate verification code"),
            UserMessage(content=verification_prompt)
        ])
        
        # STEP 4B: Execute Verification Code (Lines 700-750)
        exec_result = await self.tools.execute_code(verification_code)
        
        # STEP 4C: Analyze Results (Lines 800-850)
        if exec_result['exit_code'] != 0:
            # Verification failed
            logger.warning(f"Verification failed: {exec_result['output']}")
            return False
        
        # Check for specific failure indicators
        if "REJECT" in exec_result['output']:
            return False
        
        if "INCOMPLETE" in exec_result['output']:
            return False
        
        return True
```

### Worker Agent (Claude 4.5) Workflow

```python
# File: control_plane_v2/phase_2/worker_agent_autonomous.py

class WorkerAgent(RoutedAgent):
    """
    Autonomous Worker powered by Claude 4.5
    Executes subtasks with retry loop
    """
    
    @message_handler
    async def handle_subtask(self, message: SubtaskMessage, ctx: MessageContext):
        """
        Handle subtask with autonomous retry loop
        """
        
        # Extract expected outputs from Boss
        expected_outputs = message.expected_outputs or []
        logger.info(f"Boss expects Worker to create: {expected_outputs}")
        
        # RETRY LOOP (Lines 273-450)
        attempt = 0
        conversation_history = [self.system_prompt]
        all_attempts = []
        
        while True:
            attempt += 1
            logger.info(f"ATTEMPT #{attempt}")
            
            # Get baseline files before this attempt
            baseline_files = self._get_baseline_files()
            
            # STEP 1: BUILD PROMPT (Lines 284-290)
            # Include subtask description, instructions, previous errors
            
            prompt = self._build_prompt(message, file_paths, all_attempts)
            conversation_history.append(UserMessage(content=prompt))
            
            # STEP 2: GET CLAUDE'S RESPONSE (Lines 288-298)
            response = await self.model_client.create(
                messages=conversation_history,
                cancellation_token=ctx.cancellation_token
            )
            
            parsed = self._parse_response(response.content)
            conversation_history.append(UserMessage(content=response.content))
            
            # STEP 3: CHECK IF GIVING UP (Lines 301-323)
            if parsed.get("gave_up", False):
                # Enforce minimum 8 attempts before allowing give-up
                if attempt < 8:
                    logger.warning("Worker tried to give up too early - FORCING RETRY")
                    retry_feedback = """
                    You tried to give up after only {attempt} attempts.
                    
                    Review the error:
                    - TypeError/KeyError/IndexError: YOUR CODE BUG - fix it
                    - Data structure mismatch: ADAPT your code
                    - Path error: Use file search
                    
                    You have {15 - attempt} attempts remaining. DEBUG AND FIX.
                    """
                    conversation_history.append(UserMessage(content=retry_feedback))
                    continue
                
                # Give up allowed after 8+ attempts
                await self._report_gave_up(message, all_attempts, parsed, ctx)
                return
            
            # STEP 4: EXECUTE CODE (Lines 325-341)
            code = parsed.get("code", "")
            exec_result = await self._execute_code_with_proxy(code, ctx.cancellation_token)
            
            logger.info(f"Exit code: {exec_result['exit_code']}")
            logger.info(f"Output: {exec_result['output'][:500]}...")
            
            # STEP 5: STORE ATTEMPT (Lines 343-351)
            all_attempts.append({
                "attempt": attempt,
                "code": code,
                "stdout": exec_result["output"],
                "exit_code": exec_result["exit_code"]
            })
            
            # STEP 6: CHECK SUCCESS (Lines 353-400)
            if exec_result["exit_code"] == 0:
                # Code ran successfully
                
                # Get new files created
                new_files = self._get_new_files(baseline_files)
                
                if new_files:
                    logger.info(f"NEW files created: {new_files}")
                    
                    # STEP 7: SELF-VERIFICATION (Lines 380-420)
                    # Check if expected_outputs are satisfied
                    
                    verification_passed = self._verify_created_files(
                        new_files, 
                        expected_outputs
                    )
                    
                    if verification_passed:
                        # SUCCESS - Report to Boss
                        await self._send_completion(
                            message,
                            new_files,
                            all_attempts,
                            ctx
                        )
                        return
                    else:
                        # Missing expected files - retry
                        logger.warning(f"Missing expected files: {expected_outputs}")
                        feedback = f"""
                        Code ran successfully but missing expected files.
                        
                        Expected: {expected_outputs}
                        Created: {new_files}
                        
                        Please create ALL expected files.
                        """
                        conversation_history.append(UserMessage(content=feedback))
                        continue
                else:
                    # No new files - retry
                    logger.warning("No new files created")
                    continue
            else:
                # Code failed - retry with error feedback
                error_feedback = f"""
                Code execution failed with exit code {exec_result['exit_code']}.
                
                Error output:
                {exec_result['output']}
                
                Please fix the error and try again.
                """
                conversation_history.append(UserMessage(content=error_feedback))
                continue
            
            # STEP 8: CHECK MAX ATTEMPTS (Lines 450-460)
            if attempt >= 15:
                logger.error("Max attempts reached")
                await self._report_gave_up(message, all_attempts, {
                    "gave_up": True,
                    "gave_up_reason": "Max attempts (15) reached"
                }, ctx)
                return
    
    def _verify_created_files(self, created_files, expected_outputs):
        """
        Verify all expected files were created
        """
        
        # Convert created files to set of filenames
        created_set = set()
        for file_path in created_files:
            # Extract relative path (e.g., "outputs/file.json")
            rel_path = str(Path(file_path).relative_to(self.workspace_path))
            created_set.add(rel_path)
        
        # Check each expected output
        for expected_file in expected_outputs:
            if expected_file not in created_set:
                logger.warning(f"Missing expected file: {expected_file}")
                return False
            
            # Additional validation for specific file types
            file_path = self.workspace_path / expected_file
            
            # Check file is non-empty
            if file_path.stat().st_size == 0:
                logger.warning(f"File is empty: {expected_file}")
                return False
            
            # For JSON files, validate structure
            if expected_file.endswith('.json'):
                try:
                    with open(file_path, 'r') as f:
                        data = json.load(f)
                    
                    if not data:
                        logger.warning(f"JSON file is empty: {expected_file}")
                        return False
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON: {expected_file}")
                    return False
        
        return True
```

---

## Boss-Worker Communication Protocol

### Message Flow

```
Orchestrator                Boss (GPT-5)              Worker (Claude 4.5)
     |                           |                            |
     |-- TaskMessage ----------->|                            |
     |                           |                            |
     |                           |-- SubtaskMessage --------->|
     |                           |                            |
     |                           |                            |-- (Attempt 1) Execute code
     |                           |                            |-- (Attempt 2) Fix error, retry
     |                           |                            |-- (Attempt N) Success!
     |                           |                            |
     |                           |<-- SubtaskCompletionMessage|
     |                           |                            |
     |                           |-- (Generate verification code)
     |                           |-- (Execute verification)
     |                           |                            |
     |                           |-- Decision: ACCEPT/REJECT  |
     |                           |                            |
     |                           |   If REJECT:               |
     |                           |-- SubtaskMessage --------->|
     |                           |   (with feedback)          |
     |                           |                            |
     |                           |   If ACCEPT:               |
     |                           |-- (Move to next subtask)   |
     |                           |                            |
     |<-- TaskCompletionMessage--|                            |
     |                           |                            |
```

### Message Definitions

```python
# File: control_plane_v2/phase_2/task_agent_messages.py

class TaskMessage(BaseModel):
    """Orchestrator -> Boss"""
    task_id: str
    task_description: str
    input_files: List[str]
    expected_outputs: List[str]
    context: Optional[Dict[str, Any]] = None

class SubtaskMessage(BaseModel):
    """Boss -> Worker"""
    subtask_id: str
    subtask_description: str
    input_files: List[str]
    instructions: str
    parent_task_id: str
    expected_outputs: Optional[List[str]] = None  # CRITICAL

class SubtaskCompletionMessage(BaseModel):
    """Worker -> Boss"""
    subtask_id: str
    status: str  # "success" or "gave_up"
    files_created: List[Union[str, Dict[str, str]]]
    summary: str
    gave_up: bool = False
    gave_up_reason: Optional[str] = None
    attempts_made: int = 1

class TaskCompletionMessage(BaseModel):
    """Boss -> Orchestrator"""
    task_id: str
    status: str  # "completed", "failed", "partial"
    summary: str
    task_files_json_path: str
    files_created: List[str]
```

---

## Knowledge & Memory System

### Data Catalog

```python
# File: control_plane_v2/data_catalog.py

class DataCatalog:
    """
    Structured catalog of all data artifacts
    """
    
    def __init__(self, catalog_path: str):
        self.catalog = {
            "version": "1.0",
            "files": {},  # file_id -> metadata
            "tasks": {},  # task_id -> file list
            "lineage": {},  # file_id -> source task
            "task_summaries": {}  # task_id -> summary
        }
    
    def register_file(
        self, 
        file_id: str, 
        task_id: str, 
        absolute_path: str,
        metadata: Dict[str, Any] = None
    ):
        """
        Register a file in the catalog
        """
        
        file_path = Path(absolute_path)
        
        # Store file metadata
        self.catalog["files"][file_id] = {
            "file_id": file_id,
            "absolute_path": str(file_path),
            "size_bytes": file_path.stat().st_size if file_path.exists() else 0,
            "created_at": datetime.now().isoformat(),
            "task_id": task_id,
            "metadata": metadata or {}
        }
        
        # Update task -> files mapping
        if task_id not in self.catalog["tasks"]:
            self.catalog["tasks"][task_id] = []
        self.catalog["tasks"][task_id].append(file_id)
        
        # Update lineage
        self.catalog["lineage"][file_id] = task_id
        
        self._save()
    
    def get_file_by_id(self, file_id: str) -> Optional[Dict]:
        """
        Retrieve file metadata by ID
        """
        return self.catalog["files"].get(file_id)
    
    def get_files_by_task(self, task_id: str) -> List[Dict]:
        """
        Get all files created by a task
        """
        file_ids = self.catalog["tasks"].get(task_id, [])
        return [self.catalog["files"][fid] for fid in file_ids if fid in self.catalog["files"]]
```

### RAG Memory System

```python
# File: control_plane_v2/azure_openai_rag_memory.py

class AzureOpenAIRAGMemory:
    """
    RAG system using Azure OpenAI embeddings + ChromaDB
    """
    
    def __init__(
        self,
        persist_directory: str,
        azure_endpoint: str,
        azure_api_key: str
    ):
        # Initialize ChromaDB
        self.client = chromadb.PersistentClient(path=persist_directory)
        self.collection = self.client.get_or_create_collection("task_outputs")
        
        # Initialize Azure OpenAI
        self.openai_client = AzureOpenAI(
            azure_endpoint=azure_endpoint,
            api_key=azure_api_key
        )
    
    def add_task_output(
        self, 
        task_id: str, 
        output_data: Dict[str, Any],
        task_description: str = ""
    ):
        """
        Add task output to vector store
        """
        
        # Create text representation
        text = f"Task: {task_description}\n\n"
        text += f"Output: {json.dumps(output_data, indent=2)}"
        
        # Generate embedding
        embedding = self._generate_embedding(text)
        
        # Store in ChromaDB
        self.collection.add(
            ids=[task_id],
            embeddings=[embedding],
            documents=[text],
            metadatas=[{
                "task_id": task_id,
                "task_description": task_description,
                "timestamp": datetime.now().isoformat()
            }]
        )
    
    def query(self, query_text: str, n_results: int = 5) -> List[Dict]:
        """
        Semantic search over task outputs
        """
        
        # Generate query embedding
        query_embedding = self._generate_embedding(query_text)
        
        # Search ChromaDB
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results
        )
        
        return results
    
    def _generate_embedding(self, text: str) -> List[float]:
        """
        Generate embedding using Azure OpenAI
        """
        response = self.openai_client.embeddings.create(
            input=text,
            model="text-embedding-ada-002"
        )
        return response.data[0].embedding
```

### RAG Injector

```python
# File: control_plane_v2/phase_2/rag_injector.py

class RAGInjector:
    """
    Injects task outputs into RAG system
    """
    
    def inject_task_outputs(
        self, 
        task_id: str, 
        output_files: List[Dict[str, str]],
        task_description: str = ""
    ) -> int:
        """
        Inject task output files into RAG system
        """
        injected_count = 0
        
        for file_info in output_files:
            filename = file_info.get('filename', '')
            absolute_path = file_info.get('absolute_path', '')
            
            # Only inject JSON files (structured data)
            if filename.endswith('.json'):
                try:
                    with open(absolute_path, 'r') as f:
                        data = json.load(f)
                    
                    # Add to RAG memory
                    self.vector_store.add_task_output(
                        task_id=f"{task_id}_{filename}",
                        output_data=data,
                        task_description=f"{task_description} - {filename}"
                    )
                    
                    injected_count += 1
                except Exception as e:
                    logger.warning(f"Failed to inject {filename}: {e}")
        
        return injected_count
```

---

## Code Execution Mechanism

### Worker's Code Execution

```python
# File: control_plane_v2/phase_2/worker_agent_autonomous.py

class WorkerAgent(RoutedAgent):
    def __init__(self, ...):
        # Initialize CodeExecutorAgent for reliable code execution
        code_executor = LocalCommandLineCodeExecutor(
            work_dir=str(workspace_path),
            timeout=1800  # 30 minutes
        )
        
        self.code_executor_agent = CodeExecutorAgent(
            name="code_executor",
            code_executor=code_executor
        )
    
    async def _execute_code_with_proxy(
        self, 
        code: str, 
        cancellation_token
    ) -> Dict[str, Any]:
        """
        Execute code using CodeExecutorAgent
        """
        
        # Create code block
        code_block = CodeBlock(code=code, language="python")
        
        # Execute via CodeExecutorAgent
        result = await self.code_executor_agent.run(
            task=code_block,
            cancellation_token=cancellation_token
        )
        
        # Parse result
        return {
            "exit_code": result.exit_code,
            "output": result.output,
            "success": result.exit_code == 0
        }
```

### Boss's Verification Code Execution

```python
# File: control_plane_v2/phase_2/boss_agent_autonomous.py

class BossAgent(RoutedAgent):
    async def _verify_worker_output(self, message: SubtaskCompletionMessage):
        """
        Generate and execute verification code
        """
        
        # Step 1: Generate verification code using GPT-5
        verification_prompt = f"""
        Generate Python code to verify Worker's output.
        
        Worker created: {message.files_created}
        Expected: {self.current_subtask['expected_outputs']}
        
        Verification requirements:
        1. Check all expected files exist
        2. Check files are non-empty
        3. For JSON: validate structure and content
        4. For reports: check for placeholders, empty data
        
        CRITICAL - ONLY verify files in expected_outputs list.
        DO NOT check for other files.
        
        Return Python code that prints "ACCEPT" or "REJECT".
        """
        
        response = await self.model_client.create([
            SystemMessage(content="Generate verification code"),
            UserMessage(content=verification_prompt)
        ])
        
        verification_code = response.content
        
        # Step 2: Execute verification code
        exec_result = await self.tools.execute_code(verification_code)
        
        # Step 3: Parse result
        if exec_result['exit_code'] != 0:
            return False
        
        if "REJECT" in exec_result['output']:
            return False
        
        if "ACCEPT" in exec_result['output']:
            return True
        
        return False
```

---

## Retry and Recovery Logic

### Worker's Retry Strategy

```python
# Worker retry loop (Lines 273-460 in worker_agent_autonomous.py)

MAX_ATTEMPTS = 15
MIN_ATTEMPTS_BEFORE_GIVEUP = 8

while True:
    attempt += 1
    
    # 1. Generate code
    response = await self.model_client.create(conversation_history)
    parsed = self._parse_response(response.content)
    
    # 2. Check if giving up
    if parsed.get("gave_up", False):
        if attempt < MIN_ATTEMPTS_BEFORE_GIVEUP:
            # Force retry - too early to give up
            conversation_history.append(UserMessage(
                content="You tried to give up too early. Debug and fix your code."
            ))
            continue
        else:
            # Allow give up after 8+ attempts
            await self._report_gave_up(...)
            return
    
    # 3. Execute code
    exec_result = await self._execute_code(code)
    
    # 4. Store attempt for learning
    all_attempts.append({
        "attempt": attempt,
        "code": code,
        "stdout": exec_result["output"],
        "exit_code": exec_result["exit_code"]
    })
    
    # 5. Check success
    if exec_result["exit_code"] == 0:
        new_files = self._get_new_files(baseline_files)
        
        if new_files and self._verify_created_files(new_files, expected_outputs):
            # SUCCESS
            await self._send_completion(...)
            return
        else:
            # Missing files - provide feedback and retry
            feedback = f"Missing expected files: {expected_outputs}"
            conversation_history.append(UserMessage(content=feedback))
            continue
    else:
        # Execution failed - provide error feedback and retry
        error_feedback = f"Error: {exec_result['output']}"
        conversation_history.append(UserMessage(content=error_feedback))
        continue
    
    # 6. Check max attempts
    if attempt >= MAX_ATTEMPTS:
        await self._report_gave_up(...)
        return
```

### Boss's Re-delegation Strategy

```python
# Boss re-delegation (Lines 900-950 in boss_agent_autonomous.py)

async def _adjust_plan(self, failed_subtask: SubtaskCompletionMessage):
    """
    Adjust plan when Worker fails or Boss rejects output
    """
    
    # Option 1: Re-delegate same subtask with more specific instructions
    if failed_subtask.attempts_made < 3:
        # Extract failure reason from verification
        failure_reason = self._analyze_failure(failed_subtask)
        
        # Create new subtask message with refined instructions
        refined_message = SubtaskMessage(
            subtask_id=f"{failed_subtask.subtask_id}_retry_{failed_subtask.attempts_made}",
            subtask_description=failed_subtask.subtask_description,
            input_files=failed_subtask.input_files,
            instructions=f"""
            Previous attempt failed: {failure_reason}
            
            Please address the following:
            {self._generate_specific_feedback(failure_reason)}
            
            Original instructions:
            {original_instructions}
            """,
            expected_outputs=original_expected_outputs
        )
        
        await self.publish_message(refined_message, worker_topic)
    
    # Option 2: Break subtask into smaller pieces
    elif failed_subtask.attempts_made >= 3:
        # Subtask is too complex - break it down
        smaller_subtasks = await self._break_down_subtask(failed_subtask)
        
        for subtask in smaller_subtasks:
            await self.publish_message(subtask, worker_topic)
    
    # Option 3: Change approach entirely
    else:
        # Re-plan from scratch
        new_plan = await self._replan_task()
        await self._execute_new_plan(new_plan)
```

---

## File Catalog and Path Resolution

### How Files Are Tracked

```python
# File registration flow:

# 1. Worker creates file
worker_code = """
import json
data = {"result": "success"}
with open("outputs/result.json", "w") as f:
    json.dump(data, f)
"""

# 2. Worker reports to Boss
completion_message = SubtaskCompletionMessage(
    subtask_id="subtask_1",
    status="success",
    files_created=[{
        "filename": "outputs/result.json",
        "absolute_path": "/path/to/run/phase2/task_1/outputs/result.json"
    }]
)

# 3. Boss verifies and registers in catalog
catalog.register_file(
    file_id="outputs/result.json",
    task_id="task_1",
    absolute_path="/path/to/run/phase2/task_1/outputs/result.json",
    metadata={"created_by": "subtask_1"}
)

# 4. Next task references file by relative path
next_task_input_files = ["outputs/result.json"]

# 5. Boss resolves path using catalog
resolved_path = catalog.get_file_by_id("outputs/result.json")
# Returns: "/path/to/run/phase2/task_1/outputs/result.json"
```

### Path Resolution in Worker

```python
# File: control_plane_v2/phase_2/worker_agent_autonomous.py

async def _get_file_paths(self, input_files: List[str]) -> Dict[str, str]:
    """
    Resolve file paths using catalog
    """
    
    file_paths = {}
    
    for file_id in input_files:
        # Query catalog
        file_info = self.knowledge_systems['catalog'].get_file_by_id(file_id)
        
        if file_info:
            # Found in catalog
            file_paths[file_id] = file_info['absolute_path']
        else:
            # Not in catalog - check workspace
            workspace_file = self.workspace_path / file_id
            if workspace_file.exists():
                file_paths[file_id] = str(workspace_file)
            else:
                # Check user_uploads
                uploads_file = self.workspace_path.parent.parent / "user_uploads" / file_id
                if uploads_file.exists():
                    file_paths[file_id] = str(uploads_file)
    
    return file_paths
```

---

## Example Walkthrough

### Genomics Analysis Task

Let's walk through a real example: analyzing a genomics tar.gz file.

#### 1. User Manifest

```json
{
  "task_name": "Deep genomics analysis",
  "task_description": "Analyze TCGA BRCA genomics data",
  "input_data": {
    "primary_file": "brca_tcga.tar.gz"
  },
  "transformation_config": {
    "skip_side_tasks": true
  },
  "user_uploads": [
    {
      "source": "New folder/brca_tcga.tar.gz",
      "filename": "brca_tcga.tar.gz"
    }
  ],
  "output_requirements": {
    "format": "markdown",
    "quality_level": "high",
    "include_visualizations": true
  }
}
```

#### 2. Phase 0: Classification

**Claude's Analysis:**
```json
{
  "core_tasks": [
    {
      "id": "core_1",
      "description": "Deep structure and data analysis of genomics tar.gz",
      "subtasks": [
        "Extract and catalog files",
        "Profile data types",
        "Analyze metadata",
        "Generate comprehensive report"
      ],
      "can_be_divided": true
    }
  ],
  "side_tasks": [],  // skip_side_tasks=true
  "execution_order": ["core_1"]
}
```

#### 3. Phase 1: Division

**Claude's Proposal:**
```json
{
  "task_breakdown": {
    "sequential_tasks": [
      {
        "task_id": "init_extract_catalog",
        "description": "Extract tar.gz and create file manifest",
        "expected_output_files": ["outputs/file_manifest.json"]
      }
    ],
    "parallel_tasks": [
      {
        "task_id": "profile_clinical_data",
        "description": "Profile clinical data files",
        "dependencies": ["init_extract_catalog"],
        "expected_output_files": ["outputs/clinical_profile.json"]
      },
      {
        "task_id": "profile_mutations",
        "description": "Profile mutation data",
        "dependencies": ["init_extract_catalog"],
        "expected_output_files": ["outputs/mutation_profile.json"]
      }
    ],
    "merge_tasks": [
      {
        "task_id": "consolidate_analysis",
        "description": "Merge all profiles",
        "dependencies": ["profile_clinical_data", "profile_mutations"],
        "expected_output_files": ["outputs/analysis_catalog.json"]
      }
    ],
    "final_tasks": [
      {
        "task_id": "report_and_visualizations",
        "description": "Generate markdown report with plots",
        "dependencies": ["consolidate_analysis"],
        "expected_output_files": [
          "outputs/brca_tcga_report.md",
          "outputs/figures/coverage_heatmap.png"
        ]
      }
    ]
  }
}
```

#### 4. Phase 2: Execution - Task 1

**Orchestrator -> Boss:**
```python
TaskMessage(
    task_id="init_extract_catalog",
    task_description="Extract tar.gz and create file manifest",
    input_files=["user_uploads/brca_tcga.tar.gz"],
    expected_outputs=["outputs/file_manifest.json"]
)
```

**Boss -> Worker:**
```python
SubtaskMessage(
    subtask_id="subtask_1_extract",
    subtask_description="Extract tar.gz and catalog files",
    input_files=["user_uploads/brca_tcga.tar.gz"],
    instructions="""
    1. Extract brca_tcga.tar.gz
    2. Catalog all extracted files
    3. Identify file types
    4. Save manifest to outputs/file_manifest.json
    """,
    expected_outputs=["outputs/file_manifest.json"]
)
```

**Worker Execution (Attempt 1):**
```python
# Worker generates code:
import tarfile
import json
from pathlib import Path

# Extract tar.gz
tar_path = Path("user_uploads/brca_tcga.tar.gz")
extract_dir = Path("extracted")
extract_dir.mkdir(exist_ok=True)

with tarfile.open(tar_path, "r:gz") as tar:
    tar.extractall(extract_dir)

# Catalog files
manifest = {"files": []}
for file_path in extract_dir.rglob("*"):
    if file_path.is_file():
        manifest["files"].append({
            "path": str(file_path),
            "size": file_path.stat().st_size,
            "type": file_path.suffix
        })

# Save manifest
output_dir = Path("outputs")
output_dir.mkdir(exist_ok=True)
with open("outputs/file_manifest.json", "w") as f:
    json.dump(manifest, f, indent=2)

print(f"Extracted {len(manifest['files'])} files")
```

**Worker Self-Verification:**
```python
# Check expected outputs
expected = ["outputs/file_manifest.json"]
created = ["outputs/file_manifest.json"]

# Verify file exists and is valid JSON
manifest_path = Path("outputs/file_manifest.json")
assert manifest_path.exists()
assert manifest_path.stat().st_size > 0

with open(manifest_path) as f:
    data = json.load(f)
assert len(data["files"]) > 0

# SUCCESS - report to Boss
```

**Worker -> Boss:**
```python
SubtaskCompletionMessage(
    subtask_id="subtask_1_extract",
    status="success",
    files_created=[{
        "filename": "outputs/file_manifest.json",
        "absolute_path": "/path/to/run/phase2/init_extract_catalog/outputs/file_manifest.json"
    }],
    summary="Extracted 57 files and created manifest",
    attempts_made=1
)
```

**Boss Verification:**
```python
# Boss generates verification code:
import json
from pathlib import Path

manifest_path = Path("outputs/file_manifest.json")

# Check file exists
assert manifest_path.exists(), "Manifest file missing"

# Check non-empty
assert manifest_path.stat().st_size > 0, "Manifest file empty"

# Check valid JSON
with open(manifest_path) as f:
    data = json.load(f)

# Check has files
assert "files" in data, "Missing 'files' key"
assert len(data["files"]) > 0, "No files in manifest"

# Check each file entry has required fields
for file_entry in data["files"]:
    assert "path" in file_entry
    assert "size" in file_entry
    assert "type" in file_entry

print("ACCEPT")
```

**Boss -> Orchestrator:**
```python
TaskCompletionMessage(
    task_id="init_extract_catalog",
    status="completed",
    summary="Successfully extracted and cataloged 57 files",
    task_files_json_path="/path/to/task_files.json",
    files_created=["outputs/file_manifest.json"]
)
```

#### 5. Catalog Update

```python
# Orchestrator registers file in catalog
catalog.register_file(
    file_id="outputs/file_manifest.json",
    task_id="init_extract_catalog",
    absolute_path="/path/to/run/phase2/init_extract_catalog/outputs/file_manifest.json"
)

# RAG injection
rag_injector.inject_task_outputs(
    task_id="init_extract_catalog",
    output_files=[{
        "filename": "outputs/file_manifest.json",
        "absolute_path": "/path/to/run/phase2/init_extract_catalog/outputs/file_manifest.json"
    }],
    task_description="Extract tar.gz and create file manifest"
)
```

#### 6. Next Task Uses Catalog

**Task 2: profile_clinical_data**

```python
# Orchestrator -> Boss
TaskMessage(
    task_id="profile_clinical_data",
    input_files=["outputs/file_manifest.json"],  # Relative path
    expected_outputs=["outputs/clinical_profile.json"]
)

# Boss resolves path using catalog
file_info = catalog.get_file_by_id("outputs/file_manifest.json")
# Returns: {
#   "absolute_path": "/path/to/run/phase2/init_extract_catalog/outputs/file_manifest.json",
#   "task_id": "init_extract_catalog",
#   ...
# }

# Boss -> Worker with resolved path
SubtaskMessage(
    input_files=["outputs/file_manifest.json"],  # Worker will resolve via catalog
    ...
)
```

---

## Key Takeaways

### 1. Collaborative Intelligence
- **Phase 0**: Claude analyzes, GPT-5 reviews, Negotiator resolves, Overseer validates
- **Phase 1**: Claude proposes, GPT-5 reviews, Negotiator refines, Overseer approves
- **Phase 2**: GPT-5 plans (Boss), Claude executes (Worker)

### 2. Explicit Contracts
- Boss specifies `expected_outputs` for every subtask
- Worker verifies it created ALL expected files
- Boss generates custom verification code
- No assumptions - everything is explicit

### 3. Autonomous Retry
- Worker: Up to 15 attempts with learning from failures
- Boss: Can re-delegate indefinitely with refined instructions
- System learns from errors and adapts

### 4. Deep Validation
- Boss checks for placeholders, empty data, invalid structure
- Reports must have real data, not "N/A" or "TODO"
- Quality gates prevent low-quality outputs

### 5. Knowledge Accumulation
- All outputs indexed in DataCatalog
- Task results embedded in RAG memory
- Future tasks query for relevant context
- System gets smarter over time

---

**End of Documentation**

