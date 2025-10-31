"""
Worker Agent (Claude 4.5) - Autonomous Version with Retry Loop
Worker has freedom to iterate until success or decides to give up
Uses UserProxyAgent for reliable code execution
"""

import logging
import json
from pathlib import Path
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from autogen_core import RoutedAgent, MessageContext, message_handler, TopicId
from autogen_core.models import ChatCompletionClient, SystemMessage, UserMessage, AssistantMessage
from control_plane_v2.phase_2.task_agent_messages import SubtaskMessage, SubtaskCompletionMessage
from control_plane_v2.phase_2.task_agent_tools import TaskAgentTools
from control_plane_v2.phase_2.rag_injector import RAGInjector
from autogen_agentchat.agents import CodeExecutorAgent
from autogen_ext.code_executors import LocalCommandLineCodeExecutor
from autogen_ext.code_executors.jupyter import JupyterCodeExecutor

logger = logging.getLogger(__name__)

# Create detailed worker logger for debugging
worker_detail_logger = logging.getLogger("worker_detail")
worker_detail_logger.setLevel(logging.DEBUG)


# Pydantic model for Worker's response
class WorkerResponse(BaseModel):
    """Structured response from Worker agent"""
    code: str = Field(..., description="Python code to execute for this attempt")
    explanation: str = Field(..., description="Brief explanation of what this code does")
    approach: Optional[str] = Field(None, description="Strategy being used to solve the problem")
    retry: bool = Field(True, description="Whether to retry if this attempt fails (default: true)")
    gave_up: bool = Field(False, description="Whether giving up on this subtask (default: false)")
    gave_up_reason: Optional[str] = Field(None, description="REQUIRED if gave_up=true: Detailed explanation (3+ sentences) of why task is impossible, what was tried, and why it cannot be fixed")
    verification_summary: Optional[str] = Field(None, description="REQUIRED if retry=false: Detailed explanation (3+ sentences) of HOW you verified all output files contain real data, what samples you checked, and why task is complete")


class WorkerAgent(RoutedAgent):
    """
    Autonomous Worker Agent powered by Claude 4.5
    Works independently with retry loop until success or gives up
    """
    
    def __init__(
        self,
        agent_id: str,
        workspace_path: Path,
        knowledge_systems: Dict[str, Any],
        model_client: ChatCompletionClient,
        boss_topic_type: str
    ):
        super().__init__(f"Worker agent: {agent_id}")
        self.agent_id = agent_id
        self.workspace_path = workspace_path
        self.model_client = model_client
        self.boss_topic_type = boss_topic_type
        
        # Track current subtask to know when to restart kernel
        self.current_subtask_id = None
        self.code_executor_agent = None
        
        # We'll initialize Jupyter kernel when first subtask arrives
        # and restart it when a NEW subtask starts (but keep persistent across retry attempts)
        
        # Initialize tools (catalog and knowledge base access)
        self.tools = TaskAgentTools(
            workspace_path=workspace_path,
            catalog=knowledge_systems["catalog"],
            vector_store=knowledge_systems["vector_store"]
        )
        
        # Initialize RAG injector for querying task artifacts
        self.rag_injector = RAGInjector(vector_store=knowledge_systems["vector_store"])
        
        # System prompt emphasizing autonomy AND file creation
        self.system_prompt = SystemMessage(
            content="""You are Claude 4.5, an autonomous problem solver. You have 25 attempts to complete each subtask.

CRITICAL INSTRUCTIONS:

1. NEVER MAKE ASSUMPTIONS ON DATA STRUCTURE - ALWAYS UNDERSTAND FIRST:
   - CRITICAL: Do NOT assume data structures, field names, or JSON keys
   - MANDATORY: Always understand actual structure first before writing code
   - ALWAYS print and inspect data structures before hardcoding field names
   - For JSON/configs: Print keys/structure first, then access the actual fields you discover
   - Example: WRONG - data.get('assumed_field', []) without checking first
   - Example: CORRECT - print(data.keys()), see actual field names, then use data.get('actual_field', [])
   - NEVER hardcode field names without first verifying they exist
   - Spend attempt 1 exploring and printing structures, use that knowledge in attempt 2+

2. STRICT TASK SCOPE:
   - Do ONLY what your task explicitly asks
   - Fix YOUR OWN CODE bugs (path errors, imports, data structure mismatches)
   - If input files have unexpected structure, ADAPT your code to handle it
   - Use all 25 attempts to debug - don't give up on simple bugs

3. INPUT FILES ARE MANDATORY:
   - Load and use Boss's input files FIRST - they are the source of truth
   - Never create your own structure when input files define it

4. ALWAYS PRINT SAMPLE DATA BEFORE WORKING WITH IT:
   - CRITICAL RULE: Before writing ANY transformation or processing logic, PRINT SAMPLE DATA
   - MANDATORY: Load the data, then print head(3) or sample(3) to SEE actual values
   - For tabular data: Print df.head(3) showing the exact columns you'll transform
   - For JSON/dicts: Print sample entries to see actual field values
   - REASON: You need to SEE '149 Maple Ave' not just know column='bill_to_line1'
   - Use first 1-2 attempts to explore: load files, print structure, PRINT SAMPLE VALUES
   - Only after seeing actual data should you write transformation logic
   - Spending attempts on understanding saves time debugging wrong assumptions

5. PERSISTENT JUPYTER ENVIRONMENT:
   - You have a PERSISTENT Jupyter kernel - variables/functions/imports PERSIST across attempts!
   - IMPORTANT: Kernel working directory is SET TO YOUR WORKSPACE (not project root!)
   - This means you can:
     * Attempt 1: Define helper functions, load data, test operations
     * Attempt 2: Reuse those functions, fix bugs, run full pipeline
     * Attempt 3+: Refine individual functions without redefining everything
   - FILES and VARIABLES both persist - use this to your advantage!
   - When creating files, use relative paths (e.g., 'outputs/file.csv') - they'll be relative to YOUR WORKSPACE
   - Build transformation engine incrementally:
     * Early attempts: Define and test core functions (execute_operation, get_input_series, etc.)
     * Later attempts: Fix specific bugs in those functions, run full transformations
   - HOWEVER: If kernel gets corrupted, Boss may restart you (all state lost)
   - Final execution MUST still create ALL required output files

6. VERIFY DATA CONTENT - NO EMPTY FILES:
   - Files must contain ACTUAL data, not placeholders/null/empty values
   - CRITICAL: Validate files before declaring success
   - For tabular data: Check for MEANINGFUL values, not just .notna()
     * WARNING: pandas .notna() treats empty string "" as non-null!
     * Check sample values - real data or empty strings?
     * For string columns: Use .str.len().gt(0).sum() to count non-empty strings
   - For JSON: Check fields contain actual values, not null/empty strings
   - If transformations produced empty strings or string "None", debug and fix
   - Print verification checklist before success:
     * Files created at expected paths
     * Files loaded successfully
     * Sample values contain actual data, not placeholders

7. NO UNICODE:
   - Use only ASCII in print statements (OK, DONE, ->, etc.)
   - No emojis, checkmarks, or special characters

8. LIBRARY INSTALLATION:
   - If ModuleNotFoundError, install using subprocess.run([sys.executable, '-m', 'pip', 'install', 'library_name'])

9. CREDENTIALS:
   - Credentials are passed from Boss and shown in your prompt
   - Use provided credentials directly, not environment variables
   - Credential structure varies by system - adapt to whatever is provided

10. FILE PATH CONSISTENCY:
   - Write files to EXACT paths Boss specifies in expected_outputs
   - CRITICAL: Your kernel's working directory is YOUR WORKSPACE - use relative paths!
   - Example: If Boss expects 'outputs/data.csv', write to Path('outputs/data.csv') - NOT absolute paths
   - If output includes subdirectory, create it: Path('outputs').mkdir(parents=True, exist_ok=True)
   - NEVER use project root paths - always work relative to your workspace
   - Verify files exist at exact paths before claiming success

11. INCREMENTAL APPROACH WITH PERSISTENT KERNEL (CRITICAL - READ CAREFULLY):
   - You have 25 attempts AND a persistent Jupyter kernel - LEVERAGE BOTH!
   - Variables, functions, imports, and files ALL persist across attempts
   - MANDATORY: DO NOT rewrite entire functions/pipelines if they already work!
   
   Recommended workflow for complex transformations:
     * Attempt 1: Load data, print samples, define skeleton functions (e.g., execute_operation with 2-3 operations)
     * Attempt 2: Test execution, see which operation fails
     * Attempt 3: Add ONLY the missing operation - don't redefine execute_operation entirely!
     * Attempt 4-5: Fix bugs in specific functions (just patch the bug, don't rewrite 200 lines!)
     * Attempt 6+: Run complete pipeline using all tested functions
   
   INCREMENTAL CODE EXAMPLES:
   
   GOOD - Adding one missing operation (Attempt 5):
   ```python
   # execute_operation already exists from Attempt 2
   # Just add the missing regex_extract case
   if operation == 'regex_extract':
       pattern = parameters.get('pattern')
       series = get_input_series(parameters.get('column'), df_source, intermediates)
       return series.str.extract(pattern)[0]
   ```
   
   BAD - Rewriting everything (Attempt 5):
   ```python
   # DON'T DO THIS! You're wasting tokens and time!
   def execute_operation(operation, parameters, df_source, intermediates):
       if operation == 'trim':
           # ... 10 lines you already wrote in Attempt 2
       elif operation == 'concat':
           # ... 15 lines you already wrote in Attempt 2
       # ... rewriting 200 lines that ALREADY WORK!
   ```
   
   EFFICIENCY RULE:
   - If your Attempt 2 defined execute_operation with 5 operations
   - And Attempt 3 successfully ran but failed on missing 'regex_extract'
   - Then Attempt 4 should ONLY add 'regex_extract', not rewrite the 5 working operations!
   
   Think like working in a Jupyter notebook:
   - Cell 1 (Attempt 1): Define functions
   - Cell 2 (Attempt 2): Run pipeline, get error
   - Cell 3 (Attempt 3): Fix the ONE broken thing, not rerun Cell 1!
   
   For many files, create in batches to prevent timeouts

12. MANDATORY VERIFICATION BEFORE CLAIMING SUCCESS (retry=false):
   - CRITICAL: "Success" means OUTPUT DATA IS VALID, NOT that code ran without errors!
   - Code executing successfully (exit code 0) does NOT mean task is complete
   - You MUST run verification code AFTER generating output to check data quality
   - Check ALL files Boss requested exist on disk
   - LOAD AND READ each output file to verify it contains actual data
   - For data files: Load with appropriate libraries, print shape/structure, print sample rows/values
   - For text files: Read and print samples to confirm content exists
   - Verify files contain actual data, not placeholders, empty values, or null entries
   - CRITICAL: Analyze your verification output objectively
     * If you printed error/warning messages, the task is NOT complete
     * If you found empty data structures that should contain data, fix it
     * If you discovered missing/null/placeholder values where real data belongs, fix it
     * If verification reveals ANY data quality issues, keep retry=true
   - Print verification results showing existence, size, and sample data
   - DO NOT claim success (retry=false) in attempt #1 - use at least 2 attempts (explore then implement)
   - Only set retry=false AFTER you have loaded and verified ALL output files contain VALID, REAL data
   - When setting retry=false, you MUST provide "verification_summary" (3+ sentences explaining):
     * What files you created
     * HOW you verified each file (what you loaded, what samples you checked)
     * What specific data values you saw that prove the output is correct
     * Confirmation that all data quality checks passed
   - If you cannot verify the files contain real data, keep retry=true to continue debugging

13. RAG SYSTEM:
   - Files from completed subtasks are indexed - query them for context if needed

14. FILE PATH RESOLUTION:
   - When loading files referenced in configs, paths may not match actual locations
   - Check INPUT_FILES first, if not found search recursively in WORKING_DIR

15. WHEN TO GIVE UP (rare situations only):
   - Required input files confirmed missing after thorough search (minimum 5 attempts)
   - Task is fundamentally impossible to complete (minimum 8 attempts)
   - Input files are corrupted and unrecoverable (minimum 5 attempts)
   
   NEVER GIVE UP FOR:
   - Code errors (TypeError, KeyError, ValueError, SyntaxError) - these are YOUR bugs, FIX THEM
   - Data structure mismatches - ADAPT your code to the actual structure
   - Empty transformation results - DEBUG your transformation logic
   
   MANDATORY BEFORE GIVING UP:
   - You MUST use at least 8 attempts before giving up
   - You MUST provide detailed explanation: What specific error? What debugging did you try? Why is it impossible?
   - You MUST set gave_up=true AND provide gave_up_reason with 3+ sentences explaining the issue
   
   Before giving up ask yourself:
   - Have you explored ALL input files and printed their structure?
   - Have you adapted code to handle the ACTUAL data structure (not assumed)?
   - Have you used at least 8 of your 25 attempts?
   - Is the task truly impossible, or is this just a challenging bug?

RESPONSE FORMAT - YOU MUST RESPOND WITH VALID JSON ONLY:
{
    "code": "your python code",
    "explanation": "what this does",
    "approach": "your strategy",
    "retry": true / false,
    "gave_up": false / true,
    "gave_up_reason": "REQUIRED if gave_up=true: 3+ sentences",
    "verification_summary": "REQUIRED if retry=false: 3+ sentences explaining HOW you verified files"
}

CRITICAL: Your response must be VALID JSON matching this exact schema. Do not include markdown code fences, explanatory text, or any content outside the JSON object. Start with { and end with }.

IF CLAIMING SUCCESS (retry=false):
- You MUST include "verification_summary" field with detailed explanation (minimum 3 sentences)
- Explain: What files you created, HOW you verified each (loaded with what tool, checked what samples), what actual data values you saw
- DO NOT set retry=false in attempt #1 - minimum 2 attempts required
- Example: "Created transformed_batch_1.csv with 18 rows and 5 columns. Loaded with pandas and verified: invoice_number column has 18 non-null values (sample: ['INV-2025-7000', 'INV-2025-7001', 'INV-2025-7002']), distributor_contact column has 18 non-empty strings (sample: ['ABC Supplies | EIN 12-3456789 | Phone (957) 516-6824 | Email sales@abcdistributors.com', ...]). All transformation chains executed successfully and produced real data values."

IF GIVING UP (gave_up=true):
- You MUST include "gave_up_reason" field with detailed explanation (minimum 3 sentences)
- Explain: What specific error/issue? What debugging steps did you try? Why is it impossible to fix?
- You MUST have attempted at least 8 times before giving up

CRITICAL REMINDER BEFORE EVERY RESPONSE:
- Is this attempt #1? If YES, set retry=true (explore first, implement later)
- Did you create ALL the files Boss requested?
- Did you LOAD AND READ each output file to verify it contains real data (not just check if file exists)?
- Did you print sample data from each file to confirm actual values are present?
- Are you reporting the CORRECT files (not files from previous subtasks)?
- If setting retry=false: Did you include "verification_summary" explaining HOW you verified files and WHAT data you saw?
- Only set retry=false if you have: (a) Used 2+ attempts, (b) LOADED all output files, (c) VERIFIED they contain real data, (d) Provided verification_summary

Remember: 25 attempts available. Read input files first. Stay in scope. Complete task fully.
"""
        )
        
        logger.info(f"Autonomous worker agent {agent_id} initialized")
    
    async def _init_or_restart_kernel(self, subtask_id: str) -> None:
        """Initialize or restart Jupyter kernel for new subtask"""
        if self.current_subtask_id != subtask_id:
            logger.info(f"[KERNEL] New subtask detected - restarting Jupyter kernel")
            logger.info(f"[KERNEL] Previous: {self.current_subtask_id}, New: {subtask_id}")
            
            # Create fresh Jupyter kernel for new subtask
            code_executor = JupyterCodeExecutor(
                kernel_name="python3",
                timeout=1800,
                output_dir=str(self.workspace_path)
            )
            
            # CRITICAL: Start the executor before using it!
            await code_executor.start()
            logger.info(f"[KERNEL] Jupyter executor started successfully")
            
            # CRITICAL: Change kernel's working directory to workspace (not project root!)
            # This prevents Worker from creating files in dangerous project root location
            setup_code = f"""
import os
os.chdir(r'{self.workspace_path}')
print(f'Kernel working directory set to: {{os.getcwd()}}')
"""
            from autogen_core.code_executor import CodeBlock
            setup_block = CodeBlock(code=setup_code, language="python")
            from autogen_core import CancellationToken
            await code_executor.execute_code_blocks([setup_block], CancellationToken())
            logger.info(f"[KERNEL] Working directory set to: {self.workspace_path}")
            
            self.code_executor_agent = CodeExecutorAgent(
                name=f"code_executor_{self.agent_id}",
                code_executor=code_executor,
                description="Code execution agent with persistent Jupyter kernel"
            )
            self.current_subtask_id = subtask_id
            logger.info(f"[KERNEL] Fresh Jupyter kernel initialized for subtask: {subtask_id}")
        else:
            logger.info(f"[KERNEL] Reusing persistent kernel for subtask: {subtask_id}")
    
    @message_handler
    async def handle_subtask(self, message: SubtaskMessage, ctx: MessageContext) -> None:
        """
        Handle subtask with autonomous retry loop
        Worker keeps trying until success or decides to give up
        """
        logger.info(f"[WORKER] {self.agent_id} received subtask: {message.subtask_id}")
        logger.info(f"[TASK] {message.subtask_description}")
        
        # Wrap ALL initialization in try-except for robustness
        try:
            # Initialize or restart Jupyter kernel for new subtask
            await self._init_or_restart_kernel(message.subtask_id)
            
            worker_detail_logger.info("=" * 80)
            worker_detail_logger.info(f"WORKER STARTING SUBTASK: {message.subtask_id}")
            worker_detail_logger.info(f"Description: {message.subtask_description}")
            worker_detail_logger.info(f"Instructions: {message.instructions[:200]}...")
            worker_detail_logger.info("=" * 80)
            
            # Get file paths from catalog
            file_paths = await self._get_file_paths(message.input_files)
            worker_detail_logger.info(f"Resolved file paths: {json.dumps(file_paths, indent=2)}")
            
            # CRITICAL: Use Boss's explicit expected_outputs list
            expected_outputs = message.expected_outputs or []
            if expected_outputs:
                logger.info(f"[EXPECTED_OUTPUTS] Boss expects Worker to create: {expected_outputs}")
                worker_detail_logger.info(f"CRITICAL: Boss expects these EXACT files: {expected_outputs}")
            else:
                logger.info(f"[INFO] Worker will create files as instructed by Boss")
                worker_detail_logger.info(f"Boss will verify the created files")
                    
        except Exception as init_error:
            logger.error(f"[INIT_ERROR] Failed to initialize Worker: {init_error}", exc_info=True)
            # Report immediate failure - cannot proceed without kernel/file paths
            await self._report_gave_up(message, [], {
                "explanation": f"Worker initialization failed: {str(init_error)}. Cannot start Jupyter kernel or resolve file paths."
            }, ctx)
            return
        
        # Autonomous retry loop
        attempt = 0
        conversation_history = [self.system_prompt]
        all_attempts = []
        
        while True:
            attempt += 1
            logger.info(f"[ATTEMPT] #{attempt} for subtask {message.subtask_id}")
            worker_detail_logger.info(f"\n{'='*80}\nATTEMPT #{attempt}\n{'='*80}")
            
            # Get baseline of existing files BEFORE this attempt
            # (files may have been created in previous attempts)
            baseline_files = self._get_baseline_files()
            logger.info(f"[BASELINE] {len(baseline_files)} files exist before attempt #{attempt}")
            
            # Add task prompt ONLY on first attempt
            # On retries, feedback messages already tell Claude what to do
            # (avoids consecutive UserMessages which confuse the LLM)
            if attempt == 1:
                prompt = self._build_full_task_prompt(message, file_paths)
            conversation_history.append(UserMessage(content=prompt, source="boss"))
            
            # Get response from Claude with JSON mode enabled
            try:
                response = await self.model_client.create(
                    messages=conversation_history,
                    json_output=True,  # Force JSON-only responses
                    cancellation_token=ctx.cancellation_token
                )
                
                # Parse Claude's response
                parsed = self._parse_response(response.content)
                
                # Add Claude's response to conversation (CRITICAL: Use AssistantMessage!)
                conversation_history.append(AssistantMessage(content=response.content, source="worker"))
                
                # Check if Claude wants to give up
                if parsed.get("gave_up", False):
                    # Enforce minimum attempts before allowing give-up
                    if attempt < 8:
                        logger.warning(f"[NO_RETRY] Worker tried to give up after only {attempt} attempts - FORCING RETRY")
                        retry_feedback = f"""
You tried to give up after only {attempt} attempts. This is NOT allowed - minimum 8 attempts required.

Review the error carefully:
- If it's a TypeError, KeyError, IndexError, or AttributeError: This is YOUR CODE BUG - debug and fix it
- If it's a data structure mismatch: ADAPT your code to handle the actual structure
- If it's a path error: Use file search or catalog lookup
- If it's a missing library: Install it

You have {25 - attempt} attempts remaining. Use them to DEBUG and FIX your code.

CRITICAL: Read the actual input files first to understand their structure, then adapt your code accordingly.
"""
                        conversation_history.append(UserMessage(content=retry_feedback, source="system"))
                        continue
                    
                    # Validate gave_up_reason is provided
                    gave_up_reason = parsed.get("gave_up_reason", "")
                    if not gave_up_reason or len(gave_up_reason.split()) < 15:  # At least ~3 sentences
                        logger.warning(f"[GIVE_UP_INVALID] Worker gave up without proper explanation")
                        retry_feedback = f"""
You set gave_up=true but did not provide a proper "gave_up_reason" (must be 3+ sentences, minimum 15 words).

You MUST explain:
1. What specific error or issue you encountered
2. What debugging steps you tried across {attempt} attempts
3. Why the task is fundamentally impossible to complete

Provide a detailed gave_up_reason or continue debugging with gave_up=false.
"""
                        conversation_history.append(UserMessage(content=retry_feedback, source="system"))
                        continue
                    
                    logger.error(f"[GIVE_UP] Worker decided to give up on {message.subtask_id} after {attempt} attempts")
                    logger.error(f"[GIVE_UP_REASON] {gave_up_reason}")
                    await self._report_gave_up(message, all_attempts, parsed, ctx)
                    return
                
                # Check if Claude is claiming success too early (retry=false)
                if not parsed.get("retry", True):
                    # Prevent immediate success in attempt #1
                    if attempt == 1:
                        logger.warning(f"[TOO_EARLY] Worker tried to claim success in attempt #1 - FORCING RETRY")
                        retry_feedback = """
You set retry=false (claiming success) in attempt #1. This is NOT allowed.

You must:
- Use attempt #1 to EXPLORE and UNDERSTAND the data structures
- Use attempt #2+ to IMPLEMENT and VERIFY

Set retry=true and use your first attempt for exploration, then implement in attempt #2.
"""
                        conversation_history.append(UserMessage(content=retry_feedback, source="system"))
                        # Override retry to True
                        parsed["retry"] = True
                        continue
                    
                    # Validate verification_summary is provided when claiming success
                    verification_summary = parsed.get("verification_summary", "")
                    if not verification_summary or len(verification_summary.split()) < 15:
                        logger.warning(f"[SUCCESS_INVALID] Worker claimed success without proper verification_summary")
                        retry_feedback = f"""
You set retry=false (claiming success) but did not provide a proper "verification_summary" (must be 3+ sentences, minimum 15 words).

You MUST explain:
1. What files you created
2. HOW you verified each file (loaded it with pandas/json, checked what?)
3. What ACTUAL DATA VALUES you saw (sample rows, column values, etc.) that prove task is complete

Provide a detailed verification_summary explaining your verification process and the data you observed.
"""
                        conversation_history.append(UserMessage(content=retry_feedback, source="system"))
                        # Override retry to True to force another attempt with proper verification
                        parsed["retry"] = True
                        continue
                    
                    # SUCCESS! Claude explicitly claimed success with proper verification_summary
                    logger.info(f"[EXPLICIT_SUCCESS] Worker claimed success with verification_summary")
                    logger.info(f"[VERIFICATION_SUMMARY] {verification_summary}")
                    # Report success immediately - no need to execute code again
                    await self._report_success(message, all_attempts, parsed, ctx, baseline_files)
                    return
                
                # Execute the code
                code = parsed.get("code", "")
                if not code:
                    logger.error("No code generated by Claude")
                    error_feedback = """
Your response was parsed successfully but it's missing the required 'code' field.

You MUST provide a complete JSON response with:
{
  "code": "...your Python code here...",
  "explanation": "what this code does",
  "retry": true/false
}

Please provide a valid response with the 'code' field containing executable Python code.
"""
                    conversation_history.append(UserMessage(content=error_feedback, source="system"))
                    continue
                
                logger.info(f"[EXECUTE] Executing code (attempt #{attempt})...")
                logger.info(f"[CODE_PREVIEW] First 500 chars: {code[:500]}")
                worker_detail_logger.info(f"\nGenerated Code:\n{'-'*80}\n{code}\n{'-'*80}")
                
                # Execute code using CodeExecutorAgent
                exec_result = await self._execute_code_with_proxy(code, ctx.cancellation_token)
                logger.info(f"[EXEC_RESULT] Exit code: {exec_result['exit_code']}, Output length: {len(exec_result['output'])}")
                worker_detail_logger.info(f"\nExecution Result:")
                worker_detail_logger.info(f"  Exit Code: {exec_result['exit_code']}")
                worker_detail_logger.info(f"  Success: {exec_result['success']}")
                worker_detail_logger.info(f"  Output:\n{'-'*80}\n{exec_result['output']}\n{'-'*80}")
                
                # Store attempt
                all_attempts.append({
                    "attempt": attempt,
                    "code": code,
                    "explanation": parsed.get("explanation", ""),
                    "stdout": exec_result["output"],
                    "exit_code": exec_result["exit_code"],
                    "success": exec_result["success"]
                })
                
                if exec_result["success"]:
                    # [SUCCESS] Code executed successfully - but did it create files?
                    logger.info(f"[SUCCESS] Code executed successfully (attempt #{attempt})")
                    
                    # CRITICAL: Give Claude a chance to review its own verification output
                    output_text = exec_result.get("output", "")
                    if output_text and len(output_text) > 100:
                        # Code ran and produced output - ask Claude to analyze if verification passed
                        verification_review_feedback = f"""
Your code executed successfully (exit code 0). Here is the complete output:

{output_text}

CRITICAL ANALYSIS REQUIRED:
Carefully review your printed output above. Did your verification checks reveal any problems with the data quality?

Ask yourself:
- Did you print messages indicating errors, failures, or warnings?
- Did you find empty data structures when they should contain data?
- Did you discover missing values, nulls, or placeholder text where real data should be?
- Does your verification output show that the generated data is incorrect or incomplete?

IMPORTANT:
- "Code executed successfully" only means no Python exceptions occurred
- "Task completed successfully" means output data is valid, complete, and verified
- These are TWO DIFFERENT THINGS

If your verification output above shows ANY data quality issues:
- Set retry=true and fix the root cause
- Do not claim success until verification shows clean, valid data

If your verification output confirms all data is valid:
- Set retry=false with detailed verification_summary
- Explain what you verified and what valid data you found

You have {25 - attempt} attempts remaining.
"""
                        conversation_history.append(UserMessage(content=verification_review_feedback, source="system"))
                        continue
                    
                    # Check if files were created (delta from baseline)
                    created_files = self._scan_created_files(baseline_files)
                    
                    if created_files:
                        # Files were created! Claude must EXPLICITLY verify and claim success
                        logger.info(f"[FILES_CREATED] Found {len(created_files)} file(s): {created_files}")
                        
                        # Auto-correct file locations (move from root to subdirectories if needed)
                        relocated_count = await self._auto_correct_file_locations(expected_outputs)
                        if relocated_count > 0:
                            logger.info(f"[AUTO_CORRECT] Relocated {relocated_count} file(s) to correct locations")
                            # Rescan after relocation
                            created_files = self._scan_created_files(baseline_files)
                        
                        # Tell Claude to verify the files and claim success explicitly
                        created_files_list = [f.get("filename", str(f)) if isinstance(f, dict) else str(f.relative_to(self.workspace_path)) for f in created_files]
                        verify_files_feedback = f"""
Your code executed successfully and created files:
{chr(10).join('- ' + f for f in created_files_list)}

Expected outputs: {expected_outputs}

MANDATORY NEXT STEP - EXPLICIT VERIFICATION REQUIRED:
1. LOAD each file you created
2. Check the contents are correct (not empty, not placeholder data)
3. Print sample values from the files to confirm quality
4. Set retry=false with verification_summary explaining:
   - What files you created
   - What you loaded and verified
   - Sample data you saw that proves task is complete

DO NOT assume files are correct - VERIFY THE CONTENT BEFORE CLAIMING SUCCESS!
"""
                        conversation_history.append(UserMessage(content=verify_files_feedback, source="system"))
                        logger.info("[FILES_CREATED] Told Worker to verify files and claim success explicitly")
                        continue
                    else:
                        # No new files created
                        logger.warning(f"[NO_NEW_FILES] No NEW files created in this attempt")
                        
                        # Check if ANY files exist in workspace (from any attempt)
                        all_existing_files = self._scan_all_files()
                        
                        if all_existing_files:
                            # Files exist from previous attempts - Claude must EXPLICITLY verify and claim success
                            logger.info(f"[EXISTING_FILES] Found {len(all_existing_files)} existing file(s)")
                            
                            # Auto-correct file locations before telling Claude about them
                            relocated_count = await self._auto_correct_file_locations(expected_outputs)
                            if relocated_count > 0:
                                logger.info(f"[AUTO_CORRECT] Relocated {relocated_count} file(s) to correct locations")
                                # Rescan after relocation
                                all_existing_files = self._scan_all_files()
                            
                            # Tell Claude to verify the existing files and claim success explicitly
                            existing_files_list = [f.get("filename", str(f)) if isinstance(f, dict) else str(f) for f in all_existing_files]
                            files_exist_feedback = f"""
Your code executed successfully but didn't create NEW files.

HOWEVER, these files already exist from previous attempts:
{chr(10).join('- ' + f for f in existing_files_list)}

Expected outputs: {expected_outputs}

CRITICAL - YOU MUST EXPLICITLY VERIFY AND CLAIM SUCCESS:
1. LOAD each file and CHECK its contents
2. Verify the data is correct and complete
3. Print sample values to confirm quality
4. If files are correct: Set retry=false with detailed verification_summary explaining:
   - What you loaded from each file
   - What sample data you saw
   - Why the task is complete
5. If files are wrong/incomplete: Fix them with retry=true

DO NOT assume files are correct just because they exist - VERIFY THE CONTENT!
"""
                            conversation_history.append(UserMessage(content=files_exist_feedback, source="system"))
                            logger.info("[EXISTING_FILES] Told Worker to verify existing files and claim success explicitly")
                            continue
                        
                        if attempt >= 25:
                            # After 25 attempts with no valid files, give up
                            logger.error(f"[GIVE_UP] Giving up after {attempt} attempts with no valid file output")
                            await self._report_gave_up(message, all_attempts, {
                                "explanation": f"Code executes successfully but produces no valid output files after {attempt} attempts"
                            }, ctx)
                            return
                        
                        # Add feedback and retry
                        no_files_feedback = f"""
Your code executed successfully (exit code 0) but NO NEW OUTPUT FILES were created!

This is a critical issue. Your code must create persistent files, not just print to stdout.

REQUIRED:
1. Your code MUST write files to disk
2. Use absolute paths or relative paths from working directory: {self.workspace_path}
3. Verify files exist after creation: assert Path('output.json').exists()

REMEMBER - PERSISTENT KERNEL:
- All your previous functions/variables are STILL IN MEMORY
- Don't redefine everything - just add the file-writing code!
- If you defined transformation functions, just call them and save results

Example incremental fix:
```python
# Your functions already exist! Just run and save:
for chain_idx in [0, 1, 2, 3]:
    output_df, target_col = apply_chain(chains[chain_idx], df_source, pk_cols)
    output_df.to_parquet(f'outputs/chain_{{chain_idx}}.parquet')
```

Common mistakes:
- Only printing results instead of saving them
- Writing to wrong directory
- Not closing file handles
- Silent file I/O failures

Add file-writing code incrementally - don't rewrite your entire transformation engine!
"""
                        conversation_history.append(UserMessage(content=no_files_feedback, source="system"))
                        logger.info("[RETRY] Retrying with file creation requirement...")
                        continue
                else:
                    # [ERROR] Error - Check if Claude wants to retry
                    logger.warning(f"[FAILED] Attempt #{attempt} failed")
                    logger.warning(f"Error: {exec_result.get('error', 'Unknown error')}")
                    
                    # Check max attempts
                    if attempt >= 25:
                        logger.error(f"[GIVE_UP] Giving up after {attempt} attempts with persistent errors")
                        await self._report_gave_up(message, all_attempts, {
                            "explanation": f"Code execution failed after {attempt} attempts. Last error: {exec_result.get('error', 'Unknown')}"
                        }, ctx)
                        return
                    
                    if not parsed.get("retry", True):
                        # Claude doesn't want to retry
                        logger.error(f"[NO_RETRY] Worker decided not to retry {message.subtask_id}")
                        await self._report_gave_up(message, all_attempts, parsed, ctx)
                        return
                    
                    # Add error feedback for next iteration
                    error_feedback = f"""
Your code execution failed:

Exit Code: {exec_result['exit_code']}
Error: {exec_result.get('error', 'Unknown')}

Output:
{exec_result['output'][-2000:] if exec_result['output'] else 'No output'}

CRITICAL - YOUR PERSISTENT JUPYTER KERNEL:
- All functions, variables, and imports from your previous code are STILL IN MEMORY!
- You already defined functions like execute_operation, apply_chain, get_input_series, etc.
- These functions STILL EXIST in the kernel - don't redefine them unless they're broken!
- The error above occurred in your EXISTING code - just fix the specific bug!

INCREMENTAL FIX STRATEGY (MANDATORY):
1. Review your previous code in the conversation history above
2. Identify the SPECIFIC function/line that caused the error
3. Write MINIMAL code to fix ONLY that specific issue
4. Examples of incremental fixes:

   Good - Adding a missing operation:
   ```python
   # Just add the new operation case - execute_operation already exists!
   if operation == 'regex_extract':
       import re
       pattern = parameters.get('pattern')
       group = parameters.get('group', 0)
       input_col = parameters.get('column') or parameters.get('input') or parameters.get('input_column')
       series = get_input_series(input_col, df_source, intermediates)
       return series.astype(str).str.extract(pattern, expand=False)[group]
   ```
   
   Good - Fixing parameter extraction:
   ```python
   # Fix get_param_output to handle more cases
   def get_param_output(parameters):
       return parameters.get('output') or parameters.get('as') or parameters.get('output_field')
   ```

   BAD - Redefining everything:
   ```python
   # DON'T DO THIS - Redefining entire execute_operation with 200 lines!
   def execute_operation(operation, parameters, df_source, intermediates):
       if operation == 'trim': ...  # Already defined!
       elif operation == 'concat': ...  # Already defined!
       # ... 15 more operations you already wrote
   ```

5. If you need to update execute_operation to add a new case:
   - Use exec() or globals() to add just that case
   - OR redefine the function BUT only if adding the new operation
   - Don't rewrite operations that already work!

6. If a helper function has a bug:
   - Redefine ONLY that specific helper function
   - Don't touch the main transformation pipeline

WHAT TO DO NOW:
- Look at the error message above
- Find which specific operation/function failed
- Write minimal code to fix JUST that issue
- Leverage what's already in memory!

Analyze the error and fix it incrementally. You have {25 - attempt} attempts remaining.
"""
                    conversation_history.append(UserMessage(content=error_feedback, source="system"))
                    
                    # Continue loop for retry
                    logger.info("[RETRY] Preparing to retry...")
                    
            except Exception as e:
                logger.error(f"Error in worker loop: {e}", exc_info=True)
                # Add error to conversation and continue
                conversation_history.append(UserMessage(
                    content=f"System error occurred: {str(e)}. Please try a different approach.",
                    source="system"
                ))
                continue
    
    async def _execute_code_with_proxy(self, code: str, cancellation_token=None) -> Dict[str, Any]:
        """Execute code using CodeExecutorAgent for reliable execution"""
        try:
            logger.info("[PROXY] Executing code via CodeExecutorAgent...")
            
            # Create a CodeBlock for execution
            from autogen_core.code_executor import CodeBlock
            code_block = CodeBlock(code=code, language="python")
            
            # Use provided cancellation_token or create a new one
            if cancellation_token is None:
                from autogen_core import CancellationToken
                cancellation_token = CancellationToken()
            
            # Execute via CodeExecutorAgent (requires a list of code blocks)
            result = await self.code_executor_agent.execute_code_block([code_block], cancellation_token)
            
            logger.info(f"[PROXY] Execution result: exit_code={result.exit_code}")
            
            # Parse result from CodeExecutorAgent
            return {
                "success": result.exit_code == 0,
                "exit_code": result.exit_code,
                "output": result.output,
                "error": "" if result.exit_code == 0 else result.output
            }
            
        except Exception as e:
            logger.error(f"[PROXY] CodeExecutorAgent execution error: {e}", exc_info=True)
            # NO FALLBACK: Raise the error so Worker can retry with fresh kernel
            logger.error("[PROXY] Jupyter kernel execution failed - this attempt will fail and retry")
            raise RuntimeError(f"Jupyter kernel execution failed: {e}") from e
    
    async def _get_file_paths(self, input_files):
        """Get absolute paths for input files from catalog"""
        from pathlib import Path
        file_paths = {}
        for file_name in input_files:
            # Try multiple lookup strategies
            # 1. Try the full path as given
            catalog_result = await self.tools.access_catalog("get", file_name=file_name)
            if catalog_result["success"] and catalog_result["data"]:
                file_paths[file_name] = catalog_result["data"].get("absolute_path", str(self.workspace_path / file_name))
            else:
                # 2. Try just the basename (e.g., "user_uploads/Final_data.csv" -> "Final_data.csv")
                basename = Path(file_name).name
                catalog_result = await self.tools.access_catalog("get", file_name=basename)
                if catalog_result["success"] and catalog_result["data"]:
                    file_paths[file_name] = catalog_result["data"].get("absolute_path", str(self.workspace_path / file_name))
                else:
                    # 3. Fall back to workspace path
                    file_paths[file_name] = str(self.workspace_path / file_name)
        return file_paths
    
    def _get_baseline_files(self) -> set:
        """Get set of existing files BEFORE code execution"""
        baseline = set()
        for file_path in self.workspace_path.rglob('*'):
            if file_path.is_file():
                if not file_path.name.startswith('tmp_code_') and '__pycache__' not in file_path.parts:
                    baseline.add(str(file_path.relative_to(self.workspace_path)))
        return baseline
    
    def _scan_created_files(self, baseline_files: set) -> list:
        """Scan workspace for files created DURING this execution (delta from baseline)"""
        created_files = []
        
        for file_path in self.workspace_path.rglob('*'):
            if file_path.is_file():
                # Exclude temporary code execution files
                if file_path.name.startswith('tmp_code_'):
                    continue
                # Exclude Python cache
                if '__pycache__' in file_path.parts:
                    continue
                
                # Only include files NOT in baseline (i.e., created during this execution)
                rel_path = str(file_path.relative_to(self.workspace_path))
                if rel_path not in baseline_files:
                    # Include both relative and absolute paths
                    created_files.append({
                        "filename": rel_path,
                        "absolute_path": str(file_path.resolve())
                    })
        
        return created_files
    
    def _scan_all_files(self) -> list:
        """Scan workspace for ALL files (regardless of when they were created)"""
        all_files = []
        
        for file_path in self.workspace_path.rglob('*'):
            if file_path.is_file():
                # Exclude temporary code execution files
                if file_path.name.startswith('tmp_code_'):
                    continue
                # Exclude Python cache
                if '__pycache__' in file_path.parts:
                    continue
                
                # Include all files
                rel_path = str(file_path.relative_to(self.workspace_path))
                all_files.append({
                    "filename": rel_path,
                    "absolute_path": str(file_path.resolve())
                })
        
        return all_files
    
    async def _auto_correct_file_locations(self, expected_outputs: list) -> int:
        """
        Automatically move files from root to expected locations if they were created in wrong place.
        This prevents failures when Worker creates files in root instead of subdirectories.
        Returns: number of files relocated
        """
        import shutil
        
        if not expected_outputs:
            return 0
        
        relocated_count = 0
        
        for expected_path in expected_outputs:
            expected_full_path = self.workspace_path / expected_path
            
            # If file doesn't exist at expected location
            if not expected_full_path.exists():
                # Extract just the filename to search for it in root
                filename = Path(expected_path).name
                root_file = self.workspace_path / filename
                
                # Check if it exists in root (common mistake)
                if root_file.exists():
                    try:
                        # Ensure target directory exists
                        expected_full_path.parent.mkdir(parents=True, exist_ok=True)
                        
                        # Move file to correct location
                        shutil.move(str(root_file), str(expected_full_path))
                        relocated_count += 1
                        
                        worker_detail_logger.info(
                            f"[AUTO_CORRECT] Moved file from root to correct location: "
                            f"{filename} -> {expected_path}"
                        )
                    except Exception as e:
                        worker_detail_logger.warning(
                            f"[AUTO_CORRECT] Failed to move {filename} to {expected_path}: {e}"
                        )
        
        return relocated_count
    
    def _extract_expected_outputs(self, instructions: str) -> list:
        """Extract expected output files from subtask instructions"""
        import re
        expected = []
        
        # Look for common patterns in instructions
        patterns = [
            r"[Ss]ave\s+'([^']+\.\w+)'",
            r"[Ss]ave\s+['\"]([^'\"]+\.\w+)['\"]",
            r"[Ww]rite\s+'([^']+\.\w+)'",
            r"[Ww]rite\s+['\"]([^'\"]+\.\w+)['\"]",
            r"[Cc]reate\s+'([^']+\.\w+)'",
            r"[Cc]reate\s+['\"]([^'\"]+\.\w+)['\"]",
            r"[Gg]enerate\s+'([^']+\.\w+)'",
            r"[Gg]enerate\s+['\"]([^'\"]+\.\w+)['\"]",
            r"output\s+file[s]?:\s*'([^']+\.\w+)'",
            r"output\s+file[s]?:\s*['\"]([^'\"]+\.\w+)['\"]",
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, instructions)
            expected.extend(matches)
        
        # Remove duplicates and normalize paths
        expected = list(set(f.replace('\\', '/') for f in expected))
        logger.info(f"[EXTRACT] Found {len(expected)} expected output files in instructions")
        return expected
    
    async def _verify_created_files(self, created_files: list, expected_files: list = None) -> tuple:
        """Verify that created files are valid and match expected outputs"""
        try:
            # Extract filenames from the new format (list of dicts)
            filenames = [f["filename"] if isinstance(f, dict) else f for f in created_files]
            
            # First check: Did we create the expected files?
            if expected_files:
                created_set = set(f.replace('\\', '/') for f in filenames)
                expected_set = set(f.replace('\\', '/') for f in expected_files)
                
                missing_files = []
                for expected in expected_set:
                    # Check exact match or if file is in a subdirectory
                    found = any(expected in created or created.endswith(expected) for created in created_set)
                    if not found:
                        missing_files.append(expected)
                
                if missing_files:
                    error_msg = f"Missing expected files: {missing_files}. Created: {filenames}"
                    logger.warning(f"[VERIFY] {error_msg}")
                    return False, error_msg
            
            # Second check: Verify file integrity
            for file_rel_path in filenames:
                file_path = self.workspace_path / file_rel_path
                
                # Check file exists and is not empty
                if not file_path.exists():
                    error_msg = f"File does not exist: {file_rel_path}"
                    logger.warning(f"[VERIFY] {error_msg}")
                    return False, error_msg
                
                if file_path.stat().st_size == 0:
                    error_msg = f"File is empty: {file_rel_path}"
                    logger.warning(f"[VERIFY] {error_msg}")
                    return False, error_msg
                
                # Validate specific file types
                if file_rel_path.endswith('.json'):
                    # Verify JSON is valid
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            json.load(f)
                        logger.info(f"[VERIFY] Valid JSON: {file_rel_path}")
                    except json.JSONDecodeError as e:
                        error_msg = f"Invalid JSON in {file_rel_path}: {e}"
                        logger.warning(f"[VERIFY] {error_msg}")
                        return False, error_msg
                
                elif file_rel_path.endswith('.csv'):
                    # Verify CSV has content (at least a header)
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            first_line = f.readline()
                            if not first_line.strip():
                                error_msg = f"CSV has no header: {file_rel_path}"
                                logger.warning(f"[VERIFY] {error_msg}")
                                return False, error_msg
                        logger.info(f"[VERIFY] Valid CSV: {file_rel_path}")
                    except Exception as e:
                        error_msg = f"Error reading CSV {file_rel_path}: {e}"
                        logger.warning(f"[VERIFY] {error_msg}")
                        return False, error_msg
                
                elif file_rel_path.endswith('.png') or file_rel_path.endswith('.jpg'):
                    # Just check size is reasonable (> 1KB)
                    if file_path.stat().st_size < 1024:
                        error_msg = f"Image file too small: {file_rel_path}"
                        logger.warning(f"[VERIFY] {error_msg}")
                        return False, error_msg
                    logger.info(f"[VERIFY] Valid image: {file_rel_path}")
                
                else:
                    # For other files, just check they're not empty
                    logger.info(f"[VERIFY] File exists and not empty: {file_rel_path}")
            
            return True, "All files verified successfully"
            
        except Exception as e:
            error_msg = f"Verification error: {e}"
            logger.error(f"[VERIFY] {error_msg}")
            return False, error_msg
    
    def _build_full_task_prompt(self, message: SubtaskMessage, file_paths: Dict) -> str:
        """Build complete task prompt for first attempt"""
        
        credentials_info = ""
        if message.credentials:
            credentials_info = f"""
Credentials (for connecting to data sources):
{json.dumps(message.credentials, indent=2)}

IMPORTANT: Use these credentials directly for connections. Do NOT get credentials from environment variables."""
        
        base_prompt = f"""Subtask: {message.subtask_description}

Instructions: {message.instructions}

Input Files (with absolute paths):
{json.dumps(file_paths, indent=2)}
{credentials_info}

Working Directory: {self.workspace_path}

CRITICAL - FILE PATHS:
[IMPORTANT] Input files are provided with their ABSOLUTE PATHS above
[IMPORTANT] Use these EXACT paths when reading input files - DO NOT construct paths yourself
[IMPORTANT] Input files may be in DIFFERENT directories (from previous tasks)
[IMPORTANT] Example: To read 'data.json', use the path from Input Files dict, NOT working_dir / 'data.json'

CRITICAL - FILE CREATION:
Your Jupyter kernel's working directory is: {self.workspace_path}
REMEMBER: Your code MUST create files. Printing to stdout is NOT enough!
Use RELATIVE paths for all file operations - they'll be relative to your workspace.
Example: Path('outputs/data.csv').parent.mkdir(parents=True, exist_ok=True); df.to_csv('outputs/data.csv')
DO NOT use absolute paths or navigate to project root - work within your workspace!

Generate Python code to complete this subtask."""
        
        return base_prompt
    
    def _parse_response(self, content: str) -> Dict:
        """Parse Claude's response using Pydantic validation"""
        # Strip markdown code fences if present
        content_clean = content.strip()
        
        # Remove markdown code fence markers (```json, ````, etc.)
        if content_clean.startswith("```"):
            lines = content_clean.split("\n")
            # Remove first line if it's a code fence marker
            if lines[0].strip() in ["```", "```json", "```JSON"]:
                lines = lines[1:]
            # Remove last line if it's a closing fence
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            content_clean = "\n".join(lines).strip()
        
        # Also handle inline markers like "json" before the JSON
        if content_clean.startswith("json\n") or content_clean.startswith("json "):
            content_clean = content_clean[4:].strip()
        
        # Try to parse as JSON using Pydantic
        try:
            # Extract JSON block (find outermost braces)
            if "{" in content_clean and "}" in content_clean:
                start = content_clean.find("{")
                end = content_clean.rfind("}") + 1
                json_str = content_clean[start:end]
                
                # Validate with Pydantic
                worker_response = WorkerResponse.model_validate_json(json_str)
                return worker_response.model_dump()
                
        except (json.JSONDecodeError, ValueError, Exception) as e:
            logger.warning(f"Failed to parse response as structured JSON: {e}")
            logger.warning(f"Response content (first 200 chars): {content[:200]}")
        
        # Fallback: Extract Python code from markdown blocks
        code = content_clean
        if "```python" in content_clean:
            code = content_clean.split("```python")[1].split("```")[0].strip()
        elif "```" in content_clean:
            code = content_clean.split("```")[1].split("```")[0].strip()
        
        # Return with retry=True by default (keep trying)
        return {
            "code": code,
            "explanation": "Generated code for subtask",
            "retry": True,  # DEFAULT TO TRUE - keep retrying
            "gave_up": False
        }
    
    async def _report_success(self, message: SubtaskMessage, all_attempts: list, parsed: Dict, ctx: MessageContext, baseline_files: set):
        """Report successful completion to Boss - Simple message, no stdout"""
        
        # Scan for ALL files matching expected outputs (not just delta)
        # This is because Claude may create files in attempt #2, then claim success in attempt #3
        # The baseline for attempt #3 includes those files, so delta would be empty
        expected_outputs = message.expected_outputs or []
        created_files = []
        
        for expected_file in expected_outputs:
            # Search for this file in workspace
            matches = list(self.workspace_path.rglob(Path(expected_file).name))
            for match in matches:
                if match.is_file() and '__pycache__' not in match.parts:
                    created_files.append({
                        "filename": str(match.relative_to(self.workspace_path)),
                        "absolute_path": str(match.resolve())
                    })
                    break  # Only add first match for this expected file
        
        # Also scan for any NEW files created (delta from baseline) not in expected_outputs
        delta_files = self._scan_created_files(baseline_files)
        for delta_file in delta_files:
            # Only add if not already in created_files
            if not any(f['absolute_path'] == delta_file['absolute_path'] for f in created_files):
                created_files.append(delta_file)
        
        # CRITICAL: Send verification_summary (not just explanation) to Boss
        # Boss needs the detailed verification to trust Worker's results
        verification_summary = parsed.get("verification_summary", "")
        explanation = parsed.get("explanation", "Task completed successfully")
        
        # Prefer verification_summary if provided, otherwise use explanation
        summary_to_send = verification_summary if verification_summary else explanation
        
        completion_msg = SubtaskCompletionMessage(
            subtask_id=message.subtask_id,
            status="success",
            files_created=created_files,
            summary=summary_to_send,
            gave_up=False,
            attempts_made=len(all_attempts)
        )
        
        logger.info(f"[REPORT] Worker reporting to Boss: Completed {message.subtask_id}")
        logger.info(f"   Files created ({len(created_files)}):")
        for file_info in created_files:
            logger.info(f"      - {file_info['filename']}")
            logger.info(f"        Absolute: {file_info['absolute_path']}")
        logger.info(f"   Attempts: {len(all_attempts)}")
        
        await self.publish_message(
            completion_msg,
            topic_id=TopicId(self.boss_topic_type, source=ctx.topic_id.source)
        )
    
    async def _report_gave_up(self, message: SubtaskMessage, all_attempts: list, parsed: Dict, ctx: MessageContext):
        """Report that worker gave up on the task"""
        
        completion_msg = SubtaskCompletionMessage(
            subtask_id=message.subtask_id,
            status="gave_up",
            files_created=[],
            summary="Worker determined task is impossible or unfixable",
            gave_up=True,
            gave_up_reason=parsed.get("explanation", "Task appears impossible after multiple attempts"),
            attempts_made=len(all_attempts)
        )
        
        logger.error(f"[GAVE_UP] Worker reporting to Boss: Gave up on {message.subtask_id}")
        logger.error(f"   Reason: {completion_msg.gave_up_reason}")
        logger.error(f"   Attempts made: {len(all_attempts)}")
        
        await self.publish_message(
            completion_msg,
            topic_id=TopicId(self.boss_topic_type, source=ctx.topic_id.source)
        )

