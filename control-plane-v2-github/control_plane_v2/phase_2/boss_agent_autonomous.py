"""
Boss Agent (GPT-5) - Fully Autonomous Version
Boss has complete flexibility to plan, verify, and adjust strategy
"""

import logging
import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from pydantic import BaseModel
from autogen_core import RoutedAgent, MessageContext, message_handler, TopicId, DefaultTopicId
from autogen_core.models import ChatCompletionClient, SystemMessage, UserMessage
from control_plane_v2.phase_2.task_agent_messages import (
    TaskMessage, SubtaskMessage, SubtaskCompletionMessage, TaskCompletionMessage
)
from control_plane_v2.phase_2.task_agent_tools import TaskAgentTools
from control_plane_v2.phase_2.rag_injector import RAGInjector

logger = logging.getLogger(__name__)


# Pydantic model for verification code generation
class VerificationCodeResponse(BaseModel):
    """Response model for GPT-5's verification code generation"""
    verification_code: str


class BossAgent(RoutedAgent):
    """
    Fully Autonomous Boss Agent powered by GPT-5
    Plans, delegates, verifies, and adjusts strategy dynamically
    """
    
    def __init__(
        self,
        agent_id: str,
        workspace_path: Path,
        knowledge_systems: Dict[str, Any],
        model_client: ChatCompletionClient,
        worker_topic_type: str,
        orchestrator_topic_type: str
    ):
        super().__init__(f"Boss agent: {agent_id}")
        self.agent_id = agent_id
        self.workspace_path = workspace_path
        self.model_client = model_client
        self.worker_topic_type = worker_topic_type
        self.orchestrator_topic_type = orchestrator_topic_type
        
        # Initialize tools
        self.tools = TaskAgentTools(
            workspace_path=workspace_path,
            catalog=knowledge_systems["catalog"],
            vector_store=knowledge_systems["vector_store"]
        )
        
        # Initialize RAG injector for task artifacts
        self.rag_injector = RAGInjector(vector_store=knowledge_systems["vector_store"])
        
        # Task state
        self.current_task = None
        self.subtasks = []  # Dynamic list - Boss can modify
        self.current_subtask_idx = 0
        self.subtask_attempts = {}  # Track re-delegation attempts
        self.completed_subtasks = []
        self.subtask_results = {}
        self.subtask_messages = {}  # Store delegated subtask messages for verification context
        self.task_finalized = False  # Prevent duplicate finalization
        
        # System prompt emphasizing autonomy and verification
        self.system_prompt = SystemMessage(
            content="""You are GPT-5, an expert problem solver with FULL AUTONOMY to complete any task.

YOUR ROLE:
- Plan how to break down tasks (you can change plans anytime)
- Delegate work to Worker (Claude 4.5)
- Verify Worker's output yourself
- Decide when to accept/reject work
- Decide when task is complete

YOUR WORKFLOW:
1. Receive task description
2. Plan subtasks (check file catalog first - don't recreate existing files)
3. For each subtask:
   - Delegate to Worker with clear instructions
   - Verify output (scan files, run code to check)
   - Accept, reject with feedback, or adjust plan
4. When complete: Write final reports, update knowledge base, report completion

KEY CONSTRAINTS:
- Each subtask runs independently - Worker doesn't remember previous subtasks
- Tell Worker where to find files from previous subtasks
- Pass credentials to Worker in SubtaskMessage (not environment variables)
- Check file catalog before planning - don't recreate existing files
- You can clean up duplicate/intermediate files after subtasks complete

AVAILABLE TOOLS:
- File catalog: Query to check what files exist from previous tasks
- RAG system: Query previous task outputs with natural language
- Code execution: Run Python to verify files or analyze data
- Directory scanner: See what files exist in workspace

FOCUS ON RESULTS:
- Goal is to COMPLETE THE TASK, not write perfect code
- Only reject if outputs are MISSING, EMPTY, or clearly WRONG
- Don't reject for code quality/style issues
- Verify based on YOUR instructions to Worker, not assumptions

CRITICAL - DEEP VALIDATION FOR DATA OUTPUTS:
[MANDATORY] When verifying data transformation, processing, or report outputs, perform DEEP DATA QUALITY validation
[MANDATORY] For ANY data file (parquet, csv, JSON with data, reports), you MUST verify ACTUAL DATA, not just file format
[MANDATORY] For data verification, you MUST:
  1. Check file exists and is non-empty (size > 0 bytes)
  2. Load and parse the file (parquet with pandas, JSON with json.load(), etc.)
  3. Verify the data contains ACTUAL VALUES, not 100% None/NaN/null/empty
  4. For transformation tasks: Check that transformed columns have non-null values
  5. For tabular data: Verify row count > 0 and key columns are populated
  6. For reports with metrics/summary sections: verify values are NOT zero or null when data was analyzed
  7. If the task was to transform/process specific fields, CHECK THOSE FIELDS contain real data
  8. Spot-check sample values to ensure they look reasonable (not all empty strings, not all zeros unless expected)
[MANDATORY] REJECT outputs that have:
  - Columns that should have data but are 100% None/NaN/null (transformation failed silently)
  - Missing data where input files had data (transformation logic broken)
  - Placeholder values like "TODO", "N/A", "None", empty strings for processed fields
  - Zero row count when source data exists
  - Evidence that transformations/processing didn't actually run
[MANDATORY] When rejecting, provide specific feedback:
  - Point out which columns/fields have no data
  - Tell Worker to verify their transformation logic actually executed
  - Remind Worker to check intermediate steps and debug why values are None
  - Be specific about what's wrong with the data quality
[REASON] Data quality is critical - files that exist but contain no meaningful data are useless

CRITICAL - EXPECTED_OUTPUTS:
For EVERY subtask, you MUST specify "expected_outputs" with EXACT filenames Worker must create.
- Use specific paths with appropriate file extensions, not vague descriptions
- Worker verifies it created exactly these files before claiming success
- Include subdirectory paths if needed

RESPONSE FORMATS:

When planning subtasks:
{
    "subtasks": [
        {
            "id": "subtask_X",
            "description": "what to do",
            "instructions": "detailed steps",
            "input_files": ["input_file.ext"],
            "expected_outputs": ["output_file.ext"]
        }
    ]
}

When verifying Worker's output:
{
    "verification_code": "python code to check files",
    "expected_files": ["file1.ext", "file2.ext"]
}

When deciding after verification:
{
    "decision": "accept" | "reject" | "adjust_plan",
    "feedback": "specific feedback for Worker if rejecting",
    "reasoning": "your analysis"
}

Make intelligent decisions to ensure high-quality results.
"""
        )
        
        logger.info(f"Autonomous boss agent {agent_id} initialized")
    
    @message_handler
    async def handle_task(self, message: TaskMessage, ctx: MessageContext) -> None:
        """
        Receive main task and start autonomous execution
        """
        logger.info(f"[BOSS] {self.agent_id} received task: {message.task_id}")
        logger.info(f"[TASK] {message.task_description}")
        
        self.current_task = message
        self.current_subtask_idx = 0
        self.subtasks = []
        self.subtask_attempts = {}
        self.completed_subtasks = []
        self.subtask_results = {}
        self.subtask_messages = {}  # Reset for new task
        self.task_finalized = False  # Reset finalization flag
        
        try:
            # Plan subtasks using GPT-5
            logger.info("[PLAN] Boss planning subtasks...")
            self.subtasks = await self._plan_subtasks(message)
            logger.info(f"[PLAN] Boss created {len(self.subtasks)} initial subtasks")
            
            # CRITICAL: Validate subtasks list is not empty
            if not self.subtasks:
                logger.error("[PLAN] GPT-5 generated NO subtasks!")
                logger.error(f"  Task: {message.task_description}")
                logger.error(f"  This indicates a planning failure - cannot proceed")
                await self._report_completion(ctx, "failed", "Boss generated no subtasks - task planning failed", [])
                return
            
            # Start with first subtask
            if self.subtasks:
                await self._delegate_current_subtask(ctx)
        
        except Exception as e:
            logger.error(f"Boss error in handle_task: {e}", exc_info=True)
            await self._report_completion(ctx, "failed", f"Error: {str(e)}", [])
    
    @message_handler
    async def handle_subtask_completion(self, message: SubtaskCompletionMessage, ctx: MessageContext) -> None:
        """
        Worker reported completion - Boss verifies and decides next action
        """
        logger.info(f"[COMPLETION] Boss received completion for: {message.subtask_id}")
        logger.info(f"   Status: {message.status}")
        logger.info(f"   Files ({len(message.files_created)}):")
        for file_info in message.files_created:
            if isinstance(file_info, dict):
                logger.info(f"      - {file_info.get('filename', 'unknown')}")
                logger.info(f"        Path: {file_info.get('absolute_path', 'unknown')}")
            else:
                logger.info(f"      - {file_info}")
        logger.info(f"   Summary: {message.summary}")
        
        # CRITICAL: Validate this is a known subtask before processing
        valid_subtask_ids = [s['id'] for s in self.subtasks]
        if message.subtask_id not in valid_subtask_ids:
            logger.error(f"[INVALID_SUBTASK] Received completion for unknown subtask: {message.subtask_id}")
            logger.error(f"  Known subtasks: {valid_subtask_ids}")
            logger.error(f"  Ignoring this completion message")
            return
        
        # Check if already completed
        if message.subtask_id in self.completed_subtasks:
            logger.warning(f"[DUPLICATE] Already completed {message.subtask_id}, ignoring duplicate completion")
            return
        
        self.subtask_results[message.subtask_id] = message
        
        try:
            if message.gave_up:
                # Worker gave up - Boss decides how to handle
                logger.warning(f"[WARNING] Worker gave up on {message.subtask_id}: {message.gave_up_reason}")
                await self._handle_worker_gave_up(message, ctx)
                return
            
            # Worker claims success - Boss verifies
            logger.info(f"[VERIFY] Boss verifying {message.subtask_id}...")
            logger.info(f"[VERIFY] Worker summary length: {len(message.summary or '')} chars")
            logger.info(f"[VERIFY] Files reported: {len(message.files_created)}")
            
            # CRITICAL: Wrap verification in timeout and ultra-defensive error handling
            try:
                import asyncio
                verification_result = await asyncio.wait_for(
                    self._verify_worker_output(message, ctx),
                    timeout=600  # 10 minutes max for entire verification
                )
                logger.info(f"[VERIFY] Verification completed successfully")
            except asyncio.TimeoutError:
                logger.error(f"[VERIFY_TIMEOUT] Verification timed out after 10 minutes")
                logger.error(f"  This likely means GPT-5 verification code generation hung")
                logger.error(f"  FALLBACK: Trusting Worker's detailed verification")
                verification_result = {
                    "scan": {},
                    "verification_output": f"[TIMEOUT] Verification hung. Trusting Worker's verification:\n{message.summary}",
                    "verification_success": True  # Trust Worker
                }
            except Exception as verify_error:
                logger.error(f"[VERIFY_CRASH] Verification crashed: {verify_error}", exc_info=True)
                logger.error(f"  FALLBACK: Trusting Worker's detailed verification")
                verification_result = {
                    "scan": {},
                    "verification_output": f"[CRASH] Verification failed: {verify_error}\nTrusting Worker's verification:\n{message.summary}",
                    "verification_success": True  # Trust Worker
                }
            
            # SANITY CHECK: Detect verification conflicts and trigger recovery
            # CRITICAL: Validate summary is not None before using .lower()
            summary = message.summary or ""
            worker_claims_success = "verification_summary" in summary.lower() or message.status == "success"
            boss_verification_failed = not verification_result['verification_success']
            
            if worker_claims_success and boss_verification_failed:
                # Check if Worker provided detailed verification
                if 'verification' in summary.lower() or 'verified' in summary.lower():
                    logger.warning("="*80)
                    logger.warning("[SANITY_CHECK] VERIFICATION CONFLICT DETECTED!")
                    logger.warning(f"  Worker claims: SUCCESS with detailed verification")
                    logger.warning(f"  Boss verification: FAILED")
                    logger.warning(f"  Worker summary: {message.summary[:200]}...")
                    logger.warning(f"  Boss output: {verification_result['verification_output'][:500]}...")
                    logger.warning("  This indicates Boss's verification code has a bug!")
                    logger.warning("="*80)
                    
                    # RECOVERY: Trust Worker's detailed verification
                    if len(summary) > 100 and any(keyword in summary.lower() for keyword in ['loaded', 'verified', 'checked', 'confirmed', 'sample']):
                        logger.warning("[RECOVERY] Worker provided detailed verification (>100 chars with verification keywords)")
                        logger.warning("  TRUSTING WORKER'S VERIFICATION - Overriding Boss's failed verification")
                        verification_result['verification_success'] = True
                        verification_result['verification_output'] = f"[RECOVERED] Trusted Worker's verification:\n{message.summary}\n\n[ORIGINAL BOSS OUTPUT]:\n{verification_result['verification_output']}"
            
            # Boss decides based on verification
            decision = await self._make_decision(message, verification_result, ctx)
            
            # CRITICAL: Validate decision has action field
            action = decision.get("action", "reject")  # Safe default if missing
            if not action:
                logger.error("[DECISION] Decision missing 'action' field, defaulting to reject")
                action = "reject"
            
            if action == "accept":
                # [ACCEPT] Accept and move forward
                logger.info(f"[ACCEPT] Boss accepted {message.subtask_id}")
                self.completed_subtasks.append(message.subtask_id)
                
                # Add files to catalog
                for file_info in message.files_created:
                    # Handle new format (dict with filename and absolute_path)
                    if isinstance(file_info, dict):
                        abs_path = file_info.get("absolute_path")
                    else:
                        # Fallback for old format (just filename)
                        file_name_str = str(file_info).strip()
                        if not file_name_str:
                            logger.warning("[CATALOG] Skipping empty filename")
                            continue
                        abs_path = str(self.workspace_path / file_name_str)
                    
                    # Verify file exists before adding to catalog
                    if not abs_path or not Path(abs_path).exists():
                        logger.warning(f"[CATALOG] Skipping non-existent file: {abs_path}")
                        continue
                    
                    try:
                        # Extract just the basename for catalog key (e.g., "data.parquet" not "outputs/data.parquet")
                        catalog_key = Path(abs_path).name
                        
                        # Create meaningful description with task context and summary
                        description = f"Output from {message.subtask_id}"
                        if message.summary:
                            description += f": {message.summary[:200]}"
                        
                        await self.tools.access_catalog(
                            "add",
                            file_name=catalog_key,
                            absolute_path=abs_path,
                            description=description
                        )
                        logger.info(f"[CATALOG] Added {catalog_key} -> {abs_path}")
                    except Exception as catalog_error:
                        logger.warning(f"[CATALOG] Failed to add {catalog_key}: {catalog_error}")
                        # Continue anyway - file exists, catalog update is non-critical
                
                # Update knowledge base (non-critical operation)
                try:
                    await self.tools.access_knowledge_base(
                        "add",
                        content=f"Subtask {message.subtask_id}: {message.summary}",
                        metadata={"task_id": self.current_task.task_id, "subtask_id": message.subtask_id}
                    )
                except Exception as kb_error:
                    logger.warning(f"Failed to add subtask to knowledge base (non-critical): {kb_error}")
                
                # Inject task outputs into RAG for semantic retrieval
                try:
                    injected_count = self.rag_injector.inject_task_outputs(
                        task_id=message.subtask_id,
                        output_files=message.files_created,
                        task_description=message.summary
                    )
                    logger.info(f"[RAG] Injected {injected_count} documents from {message.subtask_id} into RAG")
                except Exception as e:
                    logger.warning(f"[RAG] Failed to inject task outputs into RAG: {e}")
                
                # Also add task summary directly to vector store for better semantic search
                try:
                    if message.summary and hasattr(self, 'vector_store') and self.vector_store:
                        # Create comprehensive summary text for embedding
                        summary_text = f"""Task: {message.subtask_id}
Parent Task: {self.current_task.task_id if self.current_task else 'unknown'}
Status: success
Summary: {message.summary}
Files Created: {', '.join([f.get('filename', '') if isinstance(f, dict) else str(f) for f in message.files_created])}
Verification: Worker verified and completed successfully."""
                        
                        # Use access_knowledge_base tool to add (it handles embedding generation)
                        await self.tools.access_knowledge_base(
                            "add",
                            content=summary_text,
                            metadata={
                                "task_id": self.current_task.task_id if self.current_task else 'unknown',
                                "subtask_id": message.subtask_id,
                                "type": "task_summary",
                                "status": "success",
                                "files_count": len(message.files_created)
                            }
                        )
                        logger.info(f"[VECTOR_STORE] Indexed summary for {message.subtask_id}")
                except Exception as vs_error:
                    logger.warning(f"[VECTOR_STORE] Failed to index summary: {vs_error}")
                
                # Clean up completed subtask message to prevent memory leak
                if message.subtask_id in self.subtask_messages:
                    del self.subtask_messages[message.subtask_id]
                    logger.info(f"[CLEANUP] Removed {message.subtask_id} from subtask_messages cache")
                
                # Move to next subtask
                self.current_subtask_idx += 1
                if self.current_subtask_idx < len(self.subtasks):
                    await self._delegate_current_subtask(ctx)
                else:
                    # All done!
                    await self._finalize_task(ctx)
            
            elif action == "reject":
                # [REJECT] Reject and re-delegate (no limit - Boss decides)
                attempts = self.subtask_attempts.get(message.subtask_id, 0)
                logger.warning(f"[REJECT] Boss rejected {message.subtask_id} (attempt {attempts + 1})")
                logger.warning(f"   Feedback: {decision.get('feedback', 'No feedback provided')}")
                self.subtask_attempts[message.subtask_id] = attempts + 1
                await self._redelegate_with_feedback(message.subtask_id, decision.get('feedback', 'Please verify outputs and retry'), ctx)
            
            elif action == "skip":
                # [SKIP] Boss decided to skip this subtask and move on
                logger.warning(f"[SKIP] Boss skipping {message.subtask_id}")
                logger.warning(f"   Reason: {decision.get('reasoning', 'No reason provided')}")
                self.completed_subtasks.append(message.subtask_id)
                
                # Clean up subtask message to prevent memory leak
                if message.subtask_id in self.subtask_messages:
                    del self.subtask_messages[message.subtask_id]
                    logger.info(f"[CLEANUP] Removed {message.subtask_id} from subtask_messages cache")
                
                self.current_subtask_idx += 1
                if self.current_subtask_idx < len(self.subtasks):
                    await self._delegate_current_subtask(ctx)
                else:
                    await self._finalize_task(ctx)
            
            elif action == "adjust_plan":
                # [ADJUST] Adjust plan
                logger.info(f"[ADJUST] Boss adjusting plan based on {message.subtask_id}")
                await self._adjust_plan(decision, ctx)
            
            else:
                # UNKNOWN ACTION - Invalid decision from GPT-5
                logger.error(f"[DECISION_ERROR] Unknown action: {decision.get('action', 'None')}")
                logger.error(f"  Valid actions: accept, reject, skip, adjust_plan")
                logger.error(f"  Decision content: {decision}")
                logger.error(f"  Defaulting to REJECT to prevent blocking")
                
                # Treat as reject and redelegate
                attempts = self.subtask_attempts.get(message.subtask_id, 0)
                logger.warning(f"[REJECT] Boss rejected {message.subtask_id} (attempt {attempts + 1}) due to invalid decision")
                self.subtask_attempts[message.subtask_id] = attempts + 1
                await self._redelegate_with_feedback(
                    message.subtask_id, 
                    "Invalid decision action. Please verify outputs and report success with detailed verification_summary.",
                    ctx
                )
        
        except Exception as e:
            logger.error(f"[ERROR] Boss error handling completion for {message.subtask_id}: {e}", exc_info=True)
            
            # Mark subtask as completed (failed) and clean up to prevent state corruption
            logger.error(f"[ERROR] Marking {message.subtask_id} as completed (with errors) and moving on")
            if message.subtask_id not in self.completed_subtasks:
                self.completed_subtasks.append(message.subtask_id)
            if message.subtask_id in self.subtask_messages:
                del self.subtask_messages[message.subtask_id]
            
            self.current_subtask_idx += 1
            if self.current_subtask_idx < len(self.subtasks):
                await self._delegate_current_subtask(ctx)
            else:
                await self._finalize_task(ctx)
    
    async def _plan_subtasks(self, task_message: TaskMessage) -> List[Dict]:
        """Use GPT-5 to plan subtasks"""
        
        # CRITICAL: Check file catalog first to see what files are available from previous tasks
        catalog_info = "No files in catalog yet."
        try:
            # Query catalog for all available files using async tool method
            catalog_result = await self.tools.access_catalog("list")
            all_files_dict = catalog_result.get("files", {})
            
            if all_files_dict:
                catalog_info = "FILES AVAILABLE IN CATALOG (from previous tasks):\n"
                for filename, file_info in all_files_dict.items():
                    abs_path = file_info.get('absolute_path', 'unknown path')
                    description = file_info.get('description', 'No description')
                    catalog_info += f"  - {filename}\n"
                    catalog_info += f"    Path: {abs_path}\n"
                    catalog_info += f"    Description: {description}\n\n"
                logger.info(f"[CATALOG] Found {len(all_files_dict)} files in catalog for planning")
            else:
                logger.info("[CATALOG] No files in catalog yet")
        except Exception as e:
            logger.warning(f"[CATALOG] Could not query catalog: {e}")
        
        # CRITICAL: Extract work_scope from Phase 1 execution plan
        work_scope_info = ""
        if task_message.context and 'work_scope' in task_message.context:
            work_scope = task_message.context['work_scope']
            if work_scope:
                work_scope_info = "\n\nCRITICAL - PHASE 1 EXECUTION PLAN (USE THESE STEPS):\n"
                work_scope_info += "Phase 1 analyzed the task and provided these detailed steps. USE THEM as your guide:\n\n"
                
                # Add inputs
                if 'inputs' in work_scope:
                    work_scope_info += f"Inputs: {work_scope['inputs']}\n\n"
                
                # Add steps
                if 'steps' in work_scope:
                    work_scope_info += "Steps to follow:\n"
                    steps = work_scope['steps']
                    if isinstance(steps, list):
                        for i, step in enumerate(steps, 1):
                            work_scope_info += f"  {i}. {step}\n"
                    else:
                        work_scope_info += f"  {steps}\n"
                    work_scope_info += "\n"
                
                # Add outputs description
                if 'outputs_description' in work_scope:
                    work_scope_info += f"Expected Outputs: {work_scope['outputs_description']}\n\n"
                
                work_scope_info += "IMPORTANT: Follow these Phase 1 steps closely. They contain specific details about:\n"
                work_scope_info += "- Data structure locations (exact keys, field names from structure analysis)\n"
                work_scope_info += "- File formats and expected content\n"
                work_scope_info += "- Transformation logic and mapping rules\n"
                work_scope_info += "- Validation requirements\n"
                work_scope_info += "DO NOT create generic fallback logic - use the EXACT instructions from Phase 1.\n"
        
        # Extract additional_instructions from context (general-purpose instructions from manifest)
        additional_instructions_info = ""
        if task_message.context and 'additional_instructions' in task_message.context:
            additional_instr = task_message.context['additional_instructions']
            if additional_instr:
                additional_instructions_info = f"\n\nADDITIONAL INSTRUCTIONS (from manifest):\n{additional_instr}\n"
        
        prompt = f"""Task: {task_message.task_description}

Input Files REQUESTED: {task_message.input_files}
Expected Outputs: {task_message.expected_outputs}
{work_scope_info}{additional_instructions_info}
CRITICAL - CHECK FILE CATALOG FIRST:
{catalog_info}

IMPORTANT - FILE RESOLUTION STRATEGY:
1. Check if the input files already exist in the catalog (from previous tasks)
2. If files exist in catalog:
   - USE the ABSOLUTE PATH from the catalog in your subtask instructions
   - Tell Worker to use the absolute path directly (Worker can read from other task workspaces)
   - Example: "Use file at C:\\path\\to\\previous_task\\outputs\\data.parquet"
3. If files are missing from catalog:
   - Create subtasks to generate/fetch them
   - Worker will create them in its own workspace
4. DO NOT recreate files that already exist - this wastes time and resources
5. When instructing Worker, provide ABSOLUTE PATHS for cross-task file access

Example:
- If 'config/settings.json' is in the catalog, just use it in your subtasks
- If 'config/settings.json' is NOT in the catalog, create a subtask to generate it

Break this task into subtasks for your worker to execute. Return JSON with subtasks array."""
        
        response = await self.model_client.create(
            messages=[self.system_prompt, UserMessage(content=prompt, source="orchestrator")]
        )
        
        # Parse response
        try:
            content = response.content
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            
            plan = json.loads(content)
            return plan.get("subtasks", [])
        except Exception as e:
            # Fallback - create simple single-subtask plan
            logger.warning(f"[PLAN] Failed to parse GPT-5 plan, using fallback: {e}")
            fallback_outputs = task_message.expected_outputs if task_message.expected_outputs else ["outputs/result.json"]
            return [{
                "id": "subtask_1",
                "description": task_message.task_description,
                "instructions": "Complete the task as described",
                "input_files": task_message.input_files,
                "expected_outputs": fallback_outputs
            }]
    
    async def _delegate_current_subtask(self, ctx: MessageContext):
        """Delegate current subtask to Worker"""
        # CRITICAL: Validate current_task exists
        if not self.current_task:
            logger.error("[DELEGATE] No current task set - cannot delegate!")
            return
        
        # CRITICAL: Validate subtasks list and index
        if not self.subtasks:
            logger.error("[DELEGATE] No subtasks available to delegate!")
            return
        
        if self.current_subtask_idx >= len(self.subtasks):
            logger.warning(f"[DELEGATE] Index {self.current_subtask_idx} >= {len(self.subtasks)}, all subtasks completed")
            return
        
        if self.current_subtask_idx < 0:
            logger.error(f"[DELEGATE] Invalid negative index: {self.current_subtask_idx}")
            self.current_subtask_idx = 0
        
        subtask = self.subtasks[self.current_subtask_idx]
        logger.info(f"[DELEGATE] Boss delegating: {subtask.get('id', 'unknown_id')}")
        
        # CRITICAL: Validate expected_outputs before delegating
        expected_outputs = subtask.get("expected_outputs", [])
        if not expected_outputs:
            logger.error(f"[BUG] Subtask {subtask['id']} has NO expected_outputs!")
            logger.error("  Boss must specify exact files Worker should create")
            logger.error("  Adding generic expected_outputs based on task description")
            # Add generic output as fallback
            expected_outputs = [f"outputs/{subtask['id']}_output.json"]
            subtask["expected_outputs"] = expected_outputs
        
        # Append additional_instructions from manifest/execution plan if available
        instructions = subtask["instructions"]
        if self.current_task.context and 'additional_instructions' in self.current_task.context:
            additional_instr = self.current_task.context.get('additional_instructions', '')
            if additional_instr:
                instructions += f"\n\nADDITIONAL INSTRUCTIONS (from manifest):\n{additional_instr}"
        
        # CRITICAL: Validate credentials to prevent Worker crashes
        credentials = self.current_task.credentials if self.current_task.credentials else {}
        if not credentials:
            logger.warning(f"[DELEGATE] No credentials available for {subtask['id']}")
        
        subtask_msg = SubtaskMessage(
            subtask_id=subtask["id"],
            subtask_description=subtask["description"],
            input_files=subtask["input_files"],
            instructions=instructions,  # Now includes additional_instructions if present
            parent_task_id=self.current_task.task_id,
            expected_outputs=subtask.get("expected_outputs", []),  # EXPLICIT list of files Boss expects
            credentials=credentials  # Pass credentials from task to subtasks (validated not None)
        )
        
        # Store subtask message for verification context
        self.subtask_messages[subtask["id"]] = subtask_msg
        
        # CRITICAL: Wrap publish in try/except to prevent silent hangs
        try:
            source = ctx.topic_id.source if (ctx.topic_id and ctx.topic_id.source) else "default"
            await self.publish_message(
                subtask_msg,
                topic_id=TopicId(self.worker_topic_type, source=source)
            )
            logger.info(f"[DELEGATE] Message published successfully to {self.worker_topic_type}")
        except Exception as pub_error:
            logger.error(f"[DELEGATE] Failed to publish subtask message: {pub_error}", exc_info=True)
            logger.error(f"  Worker topic: {self.worker_topic_type}")
            logger.error(f"  Subtask: {subtask_msg.subtask_id}")
            logger.error(f"  Source: {ctx.topic_id.source if ctx.topic_id else 'None'}")
            
            # Mark as completed (failed) and move to next
            self.completed_subtasks.append(subtask["id"])
            if subtask["id"] in self.subtask_messages:
                del self.subtask_messages[subtask["id"]]
            
            self.current_subtask_idx += 1
            if self.current_subtask_idx < len(self.subtasks):
                await self._delegate_current_subtask(ctx)
            else:
                await self._finalize_task(ctx)
    
    async def _verify_worker_output(self, completion_msg: SubtaskCompletionMessage, ctx: MessageContext) -> Dict:
        """
        Generate and execute verification code to check Worker's files
        """
        # Initialize variables at start to prevent NameError in exception handler
        expected_outputs = []
        original_instructions = ""
        verification_code = ""
        
        # Scan directory (including subdirectories to find all created files)
        logger.info(f"[VERIFY_STEP_1] Starting directory scan for {completion_msg.subtask_id}")
        try:
            scan_result = await self.tools.scan_dir(
                base_path=str(self.workspace_path),
                max_depth=10,  # Deep scan to find files in any subdirectory structure
                include_files=True
            )
            logger.info(f"[VERIFY_STEP_1] Directory scan completed")
        except Exception as scan_error:
            logger.error(f"[VERIFY_STEP_1] Directory scan crashed: {scan_error}", exc_info=True)
            return {
                "scan": {},
                "verification_output": f"[SCAN_CRASH] Directory scan crashed: {scan_error}",
                "verification_success": False
            }
        
        # CRITICAL: Validate scan_result format before using
        if not scan_result.get('success', True):
            logger.error(f"[VERIFY] Directory scan failed: {scan_result.get('error', 'Unknown error')}")
            return {
                "scan": scan_result,
                "verification_output": f"[ERROR] Cannot verify - directory scan failed: {scan_result.get('error', 'Unknown')}",
                "verification_success": False
            }
        
        # Get original subtask message for context
        logger.info(f"[VERIFY_STEP_2] Retrieving original subtask context")
        original_subtask = self.subtask_messages.get(completion_msg.subtask_id)
        
        # CRITICAL: Validate original_subtask exists
        if not original_subtask:
            logger.error(f"[VERIFY] No stored subtask message for {completion_msg.subtask_id}")
            logger.error(f"  Cannot generate proper verification - missing context!")
            logger.error(f"  Available subtask messages: {list(self.subtask_messages.keys())}")
            
            # Fallback: Trust Worker's verification since we have no context
            summary_text = completion_msg.summary or ""
            if len(summary_text) > 50 and any(kw in summary_text.lower() for kw in ['verified', 'loaded', 'checked']):
                logger.warning("[VERIFY] Trusting Worker's detailed summary due to missing context")
                return {
                    "scan": scan_result,
                    "verification_output": f"[NO_CONTEXT] No subtask message stored. Trusting Worker's verification:\n{summary_text}",
                    "verification_success": True
                }
            else:
                return {
                    "scan": scan_result,
                    "verification_output": "[ERROR] No context to verify and Worker provided minimal summary",
                    "verification_success": False
                }
        
        expected_outputs = original_subtask.expected_outputs if original_subtask else []
        original_instructions = original_subtask.instructions if original_subtask else "No instructions available"
        
        # Validate expected_outputs is not empty
        if not expected_outputs:
            logger.warning(f"[VERIFY] No expected_outputs for {completion_msg.subtask_id}!")
            logger.warning("  Attempting to infer from Worker's files_created...")
            # Use what Worker created as expected outputs
            expected_outputs = [
                f.get('filename') if isinstance(f, dict) else str(f) 
                for f in (completion_msg.files_created or [])
            ]
            if not expected_outputs:
                logger.warning("[VERIFY] No files created either - using generic output")
                expected_outputs = ["outputs/result.json"]
        
        # Validate scan_result has files list
        files_list = scan_result.get('files', [])
        if not isinstance(files_list, list):
            logger.error(f"[VERIFY] Scan result malformed - 'files' is not a list: {type(files_list)}")
            files_list = []
        
        # Prepare directory info for verification prompt
        if scan_result.get('success'):
            directory_info = f"Directory scan shows these files exist in the workspace:\n{json.dumps([f['name'] for f in files_list], indent=2)}"
        else:
            directory_info = f"Directory scan FAILED: {scan_result.get('error', 'Unknown error')}\nYou MUST use recursive file search (Path.rglob) to find expected_outputs."
        
        # CRITICAL: Limit prompt size to prevent memory crashes
        summary_truncated = (completion_msg.summary or "")[:2000]
        instructions_truncated = original_instructions[:1000]
        
        # Simplify directory_info if too large
        if len(directory_info) > 1000:
            files_count = len(files_list)
            directory_info = f"Directory scan found {files_count} files in workspace (list truncated for brevity)"
        
        # Generate verification code using GPT-5
        verify_prompt = f"""Worker completed: {completion_msg.subtask_id}
Worker's summary: {summary_truncated}
Files Worker claims created: {len(completion_msg.files_created)} file(s)

EXPECTED OUTPUTS (files YOU asked Worker to create):
{json.dumps(expected_outputs, indent=2)}

ORIGINAL INSTRUCTIONS (truncated):
{instructions_truncated}

{directory_info}

CRITICAL INSTRUCTIONS FOR VERIFICATION CODE:

1. RECURSIVE FILENAME SEARCH (NOT EXACT PATHS):
   - For each expected_output, extract ONLY the base filename (e.g., "batch_1_raw.parquet" from "outputs/intermediate/batch_1_raw.parquet")
   - Use os.walk() or Path.rglob() to RECURSIVELY search the entire WORKING_DIR for files matching that filename
   - Verify by FILENAME ONLY - do NOT check exact paths or subdirectory locations
   - Worker might create files in subdirectories - that's OK as long as the filename matches
   - Example: If expected_output is "outputs/data.json", search recursively for any file named "data.json" anywhere in the workspace

2. VERIFY ONLY EXPECTED_OUTPUTS:
   - ONLY verify the files listed in "expected_outputs" that you specified when delegating the subtask
   - DO NOT verify "discovered" files from directory scans - those are informational only
   - IGNORE any files that Worker created but weren't in your expected_outputs list
   - The directory scan is provided for context, but ONLY check expected_outputs files

3. FILE EXISTENCE AND SIZE:
   - For each filename in expected_outputs, search recursively and verify at least one matching file exists
   - Check file size is greater than 0 bytes
   - Report missing or empty files clearly
   - If multiple files with same name exist, verify the first one found

4. CONTENT VALIDATION - CRITICAL (CHECK ACTUAL DATA QUALITY):
   - For JSON files: Load with json.load() and verify structure is not empty ({{}}, [], or null)
   - For JSON files: If YOUR INSTRUCTIONS specified specific keys/fields, CHECK THOSE EXIST and contain real values (not null/"")
   - For Parquet/CSV files containing TRANSFORMED/PROCESSED data: MANDATORY DEEP CHECK:
     * Install pandas/pyarrow if needed: subprocess.run([sys.executable, '-m', 'pip', 'install', 'pandas', 'pyarrow'], capture_output=True)
     * Load the data: df = pd.read_parquet(file_path) or df = pd.read_csv(file_path)
     * Check shape: print(f"Shape: {{len(df)}} rows, {{len(df.columns)}} columns")
     * CRITICAL COLUMN COUNT CHECK: If task was to transform/process data, output should have MORE than just the ID column
       - If only 1 column exists (likely just the ID), print "[FAIL] Only 1 column found - transformation did not produce any output columns"
       - Transformation outputs should have ID column PLUS transformed columns (minimum 2 columns, usually more)
     * For EVERY column, check for ACTUAL MEANINGFUL VALUES (not just .notna()):
       - Calculate non-null: non_null_pct = (df[col].notna().sum() / len(df)) * 100
       - For string columns, also calculate meaningful values: meaningful = df[col].apply(lambda x: str(x).strip() not in ['', 'None', 'N/A', 'TODO'] and pd.notna(x)).sum()
       - Print: "[DATA_QUALITY] column_name: X/Y non-null (Z%), Y/Y meaningful (W%)"
       - Print first 3 unique values: unique_vals = df[col].unique()[:3]; print(f"[SAMPLE] column_name values: {{unique_vals}}")
     * CRITICAL: If verification shows "18/18 non-null" but sample values are ["", "", ""] or ["None", "None", "None"], this is FAILED DATA - the transformation produced empty results
     * If ANY column that should have transformed data shows all empty strings or string "None": Print "[FAIL] column_name has NO MEANINGFUL DATA - all values are empty/placeholder"
     * Identify which columns were supposed to be populated based on the task and check those specifically
   - For Parquet/CSV files that are RAW EXTRACTS (not transformed): Just check rows > 0
   - For text/HTML reports: Read content and check for actual values, not placeholders like "TODO", "N/A", "0 rows processed"
   - For binary files: Read first few bytes to confirm not empty

5. INSTRUCTION-BASED VALIDATION:
   - Review the instructions YOU gave to Worker for this subtask
   - Identify what specific data/fields/sections you requested
   - Verify those specific requirements are present in the files
   - DO NOT check for fields you didn't explicitly request
   - DO NOT assume generic templates - check what YOU asked for

6. REPORT RESULTS CLEARLY:
   - Print [OK] for files that exist (anywhere in workspace), are non-empty, and contain expected content
   - Print [MISSING] for filenames that don't exist anywhere in the workspace
   - Print [EMPTY] for files with 0 bytes or empty content
   - Print [INCOMPLETE] for files missing required fields/sections you requested

7. CODE STRUCTURE:
   - Handle both dict format {{'filename': ..., 'absolute_path': ...}} and string format
   - Extract base filename using os.path.basename() or Path().name
   - Use Path(WORKING_DIR).rglob(filename) to search recursively
   - Use try/except blocks to handle file read errors gracefully
   - Return clear verification results for each file
   - ONLY iterate over expected_outputs files, NOT discovered files

Return JSON with "verification_code" field containing Python code."""
        
        # Log prompt size before calling GPT-5
        prompt_size = len(verify_prompt)
        logger.info(f"[VERIFY_STEP_3] Preparing to call GPT-5 for verification code generation")
        logger.info(f"[VERIFY_STEP_3] Verification prompt size: {prompt_size} chars")
        if prompt_size > 10000:
            logger.warning(f"[VERIFY_STEP_3] Large prompt detected ({prompt_size} chars) - may be slow")
        
        # CRITICAL: Timeout the GPT-5 call to prevent infinite hangs
        import asyncio
        try:
            logger.info(f"[VERIFY_STEP_3] Calling GPT-5 with timeout=180s...")
            verify_response = await asyncio.wait_for(
                self.model_client.create(
                    messages=[self.system_prompt, UserMessage(content=verify_prompt, source="system")],
                    json_output=VerificationCodeResponse
                ),
                timeout=180  # 3 minutes max for GPT-5 to generate verification code
            )
            logger.info(f"[VERIFY_STEP_3] GPT-5 responded successfully")
        except asyncio.TimeoutError:
            logger.error("[VERIFY_STEP_3] GPT-5 verification code generation timed out after 3 minutes")
            logger.error("  FALLBACK: Skipping verification, trusting Worker's detailed summary")
            return {
                "scan": scan_result,
                "verification_output": f"[GPT5_TIMEOUT] Verification code generation timed out. Trusting Worker:\n{completion_msg.summary[:500]}",
                "verification_success": True  # Trust Worker
            }
        except Exception as gpt5_error:
            logger.error(f"[VERIFY_STEP_3] GPT-5 call crashed: {gpt5_error}", exc_info=True)
            return {
                "scan": scan_result,
                "verification_output": f"[GPT5_CRASH] GPT-5 crashed: {gpt5_error}\nTrusting Worker:\n{completion_msg.summary[:500]}",
                "verification_success": True  # Trust Worker
            }
        
        # Parse and execute verification code
        try:
            # With Pydantic structured output, we get clean JSON
            content = verify_response.content
            
            # Try to parse as JSON first (Pydantic should give us valid JSON)
            try:
                verify_data = json.loads(content)
            except json.JSONDecodeError:
                # Fallback: extract from markdown code blocks if needed
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                    verify_data = json.loads(content)
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0].strip()
                    verify_data = json.loads(content)
                else:
                    raise
            
            verification_code = verify_data.get("verification_code") or "print('No verification code generated')"
            
            # Validate verification_code is a non-empty string
            if not verification_code or not isinstance(verification_code, str):
                logger.error(f"[VERIFICATION] Invalid verification_code: {type(verification_code)}")
                return {
                    "scan": scan_result,
                    "verification_output": "[ERROR] No valid verification code generated",
                    "verification_success": False
                }
            
            # CRITICAL: Validate verification code before execution
            try:
                compile(verification_code, '<verification>', 'exec')
                logger.info("[VERIFICATION] Code syntax validation passed")
            except SyntaxError as syntax_err:
                logger.error(f"[VERIFICATION] Generated code has syntax error: {syntax_err}")
                logger.error(f"  Buggy code: {verification_code[:500]}...")
                return {
                    "scan": scan_result,
                    "verification_output": f"[SYNTAX_ERROR] Generated verification code is invalid: {syntax_err}",
                    "verification_success": False
                }
            
            # Check if code references expected files (with safety checks)
            if expected_outputs and isinstance(verification_code, str):
                try:
                    references_files = any(
                        str(filename).replace('outputs/', '').replace('\\', '/') in verification_code 
                        for filename in expected_outputs
                        if filename  # Skip None/empty
                    )
                    if not references_files:
                        logger.warning("[VERIFICATION] Code doesn't reference any expected_outputs!")
                except Exception as ref_check_err:
                    logger.warning(f"[VERIFICATION] Error checking file references: {ref_check_err}")
            
            # Execute verification with timeout
            import asyncio
            try:
                logger.info(f"[VERIFY_STEP_4] Executing verification code (timeout=300s)...")
                logger.info(f"[VERIFY_STEP_4] Code size: {len(verification_code)} chars")
                
                exec_result = await asyncio.wait_for(
                    self.tools.execute_python_code(verification_code, ctx.cancellation_token),
                    timeout=300  # 5 minutes max
                )
                
                logger.info(f"[VERIFY_STEP_4] Code execution completed")
                
                # Validate exec_result format
                if not isinstance(exec_result, dict):
                    logger.error(f"[VERIFICATION] exec_result is not a dict: {type(exec_result)}")
                    exec_result = {"success": False, "output": str(exec_result), "error": "Invalid result format"}
                
                logger.info(f"[VERIFY_STEP_5] Verification complete - success={exec_result.get('success', False)}")
                return {
                    "scan": scan_result,
                    "verification_output": exec_result.get("output", exec_result.get("error", "")),
                    "verification_success": exec_result.get("success", False)
                }
            except asyncio.TimeoutError:
                logger.error("[VERIFY_STEP_4] Code execution timed out after 5 minutes")
                logger.error("  FALLBACK: Trusting Worker's verification")
                return {
                    "scan": scan_result,
                    "verification_output": f"[TIMEOUT] Verification code took too long. Trusting Worker:\n{completion_msg.summary[:500]}",
                    "verification_success": True  # Trust Worker
                }
            except Exception as exec_error:
                logger.error(f"[VERIFY_STEP_4] Code execution crashed: {exec_error}", exc_info=True)
                return {
                    "scan": scan_result,
                    "verification_output": f"[EXEC_CRASH] Execution failed: {exec_error}\nTrusting Worker:\n{completion_msg.summary[:500]}",
                    "verification_success": True  # Trust Worker
                }
        except Exception as e:
            logger.error(f"[VERIFICATION] Error generating/executing verification: {e}", exc_info=True)
            logger.error(f"  Subtask: {completion_msg.subtask_id}")
            logger.error(f"  Expected outputs: {expected_outputs}")
            if verification_code:
                logger.error(f"  Verification code (first 500 chars): {str(verification_code)[:500]}")
            else:
                logger.error("  Verification code: Not generated")
            return {
                "scan": scan_result,
                "verification_output": f"[ERROR] Verification failed: {str(e)}",
                "verification_success": False
            }
    
    async def _make_decision(self, completion_msg: SubtaskCompletionMessage, verification: Dict, ctx: MessageContext) -> Dict:
        """
        Ask GPT-5 to review verification results and decide next action
        """
        verification_status = "SUCCESS" if verification['verification_success'] else "FAILED"
        
        # CRITICAL: Include Worker's own verification in decision
        worker_verification_section = ""
        worker_summary = completion_msg.summary or ""
        
        # Check if Worker provided explicit verification
        if ("verified" in worker_summary.lower() or "verification" in worker_summary.lower()) and len(worker_summary) > 50:
            worker_verification_section = f"""
WORKER'S OWN VERIFICATION (Worker loaded files and verified them):
{worker_summary}

IMPORTANT: Worker provided detailed verification above. If Worker's verification is thorough and shows 
real data/values, but YOUR verification failed, YOUR verification code may have bugs. Consider:
- Worker says "103/103 outputs found" but you found "0/103" → Your code has parsing bug
- Worker shows sample values but you don't → Your code didn't load files correctly
- Worker verified file structure but you got errors → Your code has wrong path/logic
In such cases, TRUST WORKER'S VERIFICATION over your potentially buggy verification code.
"""
        
        decision_prompt = f"""You are reviewing Worker's completion of: {completion_msg.subtask_id}

Worker's Report:
- Files created: {completion_msg.files_created}
- Summary: {completion_msg.summary}
- Attempts: {completion_msg.attempts_made}
{worker_verification_section}
Your Verification Code Execution: {verification_status}
{verification['verification_output'][:10000]}

IMPORTANT - STRICT DATA QUALITY VALIDATION:
- Always verify primary output files contain REAL DATA, not just valid file formats
- For transformation/processing tasks: Check that output columns/fields actually have values (not 100% None/NaN/null/empty strings)
- CRITICAL COLUMN COUNT: If task was transformation/processing, output must have ID column PLUS transformed columns
  * If verification shows "1 column" for transformation output, transformation FAILED - REJECT immediately
  * Example: Output should have ID + multiple transformed columns, not just ID alone
  * If you see "Shape: N rows, 1 columns" for transformation task, this means no transformations were applied - REJECT
- CRITICAL PANDAS TRAP: .notna() treats empty strings "" as non-null! Your verification code must check for ACTUAL MEANINGFUL VALUES:
  * Empty string "" is NOT valid data - it's a failed transformation
  * String literal "None" is NOT valid data - it's a failed transformation  
  * String "N/A" or "TODO" is NOT valid data - it's a placeholder
  * When verification prints "[DATA_QUALITY] col: 18/18 non-null (100%)", you MUST also check sample values!
  * If sample values shown are ["", "", ""] or ["None", "None", "None"] or all identical single character, the transformation FAILED
- MANDATORY: Review the "[SAMPLE]" output lines from verification - do they show real addresses, dates, formatted text? Or empty/placeholder values?
- If verification output has "[DATA_QUALITY]" but NO "[SAMPLE]" lines showing actual values, the verification is INCOMPLETE - you must check actual data
- For string/text columns in transformed data: Distinct_count should be > 1 (if all 18 rows have same value "", something is wrong)
- Quality metrics showing "distinct_count: 1" for transformed columns is a RED FLAG - all rows have identical (likely empty) value
- For config/metadata files: Can be lenient if structure is correct
- For data files (parquet/csv/processed outputs): Be STRICT - must contain actual transformed values with meaningful content
- Only ACCEPT when verification confirms meaningful data exists (not just file exists with non-null counts)
- BEFORE accepting, ask yourself: "Did I see actual sample data values in the verification output, or only counts?"

DECIDE what to do next. Return JSON:
{{
    "action": "accept" | "reject" | "skip" | "adjust_plan",
    "feedback": "specific feedback if rejecting (only for Worker's issues, not your verification code issues)",
    "reasoning": "your analysis"
}}

Actions:
- "accept": Worker did good work, move to next subtask
- "reject": Re-delegate to Worker with feedback (you can retry as many times as you want)
- "skip": Move on without completing this subtask (if it's not critical or too difficult)
- "adjust_plan": Change your overall plan
"""
        
        decision_response = await self.model_client.create(
            messages=[self.system_prompt, UserMessage(content=decision_prompt, source="system")]
        )
        
        try:
            content = decision_response.content
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            
            return json.loads(content)
        except Exception as e:
            # SAFE DEFAULT: Reject when decision parsing fails
            logger.error(f"[DECISION] Failed to parse decision: {e}")
            logger.error(f"  Content: {content[:500]}...")
            return {
                "action": "reject",
                "feedback": f"Boss's decision-making failed to parse response. Please verify your outputs are complete and correct, then report success with detailed verification_summary.",
                "reasoning": f"Decision parsing error: {str(e)}. Defaulting to safe rejection."
            }
    
    async def _redelegate_with_feedback(self, subtask_id: str, feedback: str, ctx: MessageContext):
        """Re-delegate same subtask with feedback"""
        # CRITICAL: Validate current_task exists
        if not self.current_task:
            logger.error("[REDELEGATE] No current task set - cannot redelegate!")
            return
        
        subtask = next((s for s in self.subtasks if s["id"] == subtask_id), None)
        if not subtask:
            logger.error(f"[REDELEGATE_ERROR] Cannot redelegate unknown subtask: {subtask_id}")
            logger.error(f"  Known subtasks: {[s['id'] for s in self.subtasks]}")
            logger.error(f"  This indicates state corruption or invalid subtask_id")
            return
        
        # CRITICAL: Scan directory to list existing files
        existing_files_info = ""
        try:
            scan_result = await self.tools.scan_dir(
                base_path=str(self.workspace_path),
                max_depth=3,  # Scan subdirectories too
                include_files=True
            )
            
            files_list = scan_result.get('files', [])
            if files_list:
                existing_files_info = "\n\nEXISTING FILES IN WORKSPACE (DO NOT DELETE OR OVERWRITE THESE):\n"
                for file_info in files_list:
                    file_path = file_info.get('path', file_info.get('name', 'unknown'))
                    file_size = file_info.get('size', 0)
                    existing_files_info += f"  - {file_path} ({file_size} bytes)\n"
                existing_files_info += "\nIMPORTANT: Check for these files before executing. Preserve them unless explicitly told to replace them.\n"
                logger.info(f"[REDELEGATE] Found {len(files_list)} existing files in workspace")
        except Exception as e:
            logger.warning(f"[REDELEGATE] Could not scan directory: {e}")
        
        # Add feedback to instructions with existing files list
        enhanced_instructions = f"""{subtask['instructions']}

FEEDBACK FROM PREVIOUS ATTEMPT:
{feedback}
{existing_files_info}

Please address this feedback in your implementation."""
        
        # Append additional_instructions from manifest if available
        if self.current_task.context and 'additional_instructions' in self.current_task.context:
            additional_instr = self.current_task.context.get('additional_instructions', '')
            if additional_instr:
                enhanced_instructions += f"\n\nADDITIONAL INSTRUCTIONS (from manifest):\n{additional_instr}"
        
        # CRITICAL: Validate credentials to prevent Worker crashes
        credentials = self.current_task.credentials if self.current_task.credentials else {}
        
        subtask_msg = SubtaskMessage(
            subtask_id=subtask_id,
            subtask_description=subtask["description"],
            input_files=subtask["input_files"],
            instructions=enhanced_instructions,
            parent_task_id=self.current_task.task_id,
            expected_outputs=subtask.get("expected_outputs", []),  # EXPLICIT list of files Boss expects
            credentials=credentials  # Pass credentials from task to subtasks (validated not None)
        )
        
        # Update stored subtask message with feedback
        self.subtask_messages[subtask_id] = subtask_msg
        
        logger.info(f"[REDELEGATE] Boss re-delegating {subtask_id} with feedback")
        
        # CRITICAL: Wrap publish in try/except
        try:
            source = ctx.topic_id.source if (ctx.topic_id and ctx.topic_id.source) else "default"
            await self.publish_message(
                subtask_msg,
                topic_id=TopicId(self.worker_topic_type, source=source)
            )
            logger.info(f"[REDELEGATE] Message published successfully")
        except Exception as pub_error:
            logger.error(f"[REDELEGATE] Failed to publish redelegate message: {pub_error}", exc_info=True)
            logger.error(f"  Subtask: {subtask_id}")
            # Skip this subtask since we can't communicate with Worker
            self.completed_subtasks.append(subtask_id)
            if subtask_id in self.subtask_messages:
                del self.subtask_messages[subtask_id]
            self.current_subtask_idx += 1
            if self.current_subtask_idx < len(self.subtasks):
                await self._delegate_current_subtask(ctx)
            else:
                await self._finalize_task(ctx)
    
    async def _handle_worker_gave_up(self, completion_msg: SubtaskCompletionMessage, ctx: MessageContext):
        """Handle case where Worker gave up - Boss analyzes and decides whether to redelegate"""
        logger.warning(f"[GAVE_UP] Boss analyzing why Worker gave up on {completion_msg.subtask_id}")
        
        # Ask GPT-5 to analyze the give-up reason and decide what to do
        analysis_prompt = f"""Worker gave up on subtask: {completion_msg.subtask_id}

Worker's Give-Up Reason:
{completion_msg.gave_up_reason}

Worker's Attempts: {completion_msg.attempts_made}

Subtask Description:
{next((s['description'] for s in self.subtasks if s['id'] == completion_msg.subtask_id), 'Unknown')}

Analyze WHY the Worker gave up and decide what to do:

1. If Worker gave up due to a SIMPLE CODE BUG (like TypeError, data structure mismatch, path error):
   - This is fixable! Worker should have debugged it but didn't.
   - ACTION: "redelegate" with specific debugging guidance
   
2. If Worker gave up due to MISSING INPUT FILES or IMPOSSIBLE TASK:
   - Check if the issue is legitimate (truly missing files, truly impossible)
   - If legitimate: ACTION: "skip" 
   - If not legitimate (files exist, task is possible): ACTION: "redelegate" with clarification

3. If Worker only tried 1-2 attempts before giving up:
   - Worker didn't use all 25 attempts properly
   - ACTION: "redelegate" with encouragement to debug thoroughly

Return JSON:
{{
    "action": "redelegate" | "skip",
    "analysis": "your analysis of why Worker gave up",
    "feedback": "specific guidance for Worker if redelegating (e.g., 'The error shows column_types is a dict with a columns key containing a list. Adapt your code to handle this structure: column_types[\"columns\"] is the list you need to iterate over.')",
    "reasoning": "why you chose this action"
}}"""
        
        try:
            decision_response = await self.model_client.create(
                messages=[self.system_prompt, UserMessage(content=analysis_prompt, source="system")]
            )
            
            content = decision_response.content
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            
            decision = json.loads(content)
            logger.info(f"[GAVE_UP] Boss decision: {decision.get('action', 'unknown')}")
            logger.info(f"[GAVE_UP] Analysis: {decision.get('analysis', 'No analysis provided')}")
            
            if decision.get("action") == "redelegate":
                # Redelegate with specific feedback
                feedback = decision.get('feedback', 'Please retry - you may have given up too early')
                logger.info(f"[GAVE_UP] Boss redelegating with feedback: {feedback}")
                await self._redelegate_with_feedback(
                    completion_msg.subtask_id,
                    feedback,
                    ctx
                )
                return
            else:
                # Skip this subtask
                logger.warning(f"[GAVE_UP] Boss skipping subtask: {decision.get('reasoning', 'No reasoning provided')}")
                self.completed_subtasks.append(completion_msg.subtask_id)
                
                # Clean up subtask message
                if completion_msg.subtask_id in self.subtask_messages:
                    del self.subtask_messages[completion_msg.subtask_id]
                
                self.current_subtask_idx += 1
                
                if self.current_subtask_idx < len(self.subtasks):
                    await self._delegate_current_subtask(ctx)
                else:
                    await self._finalize_task(ctx)
        
        except Exception as e:
            logger.error(f"[GAVE_UP] Error analyzing give-up: {e}")
            # Default: skip and move on
            logger.warning(f"[GAVE_UP] Defaulting to skip due to analysis error")
            self.completed_subtasks.append(completion_msg.subtask_id)
            
            # Clean up subtask message
            if completion_msg.subtask_id in self.subtask_messages:
                del self.subtask_messages[completion_msg.subtask_id]
            
            self.current_subtask_idx += 1
            
            if self.current_subtask_idx < len(self.subtasks):
                await self._delegate_current_subtask(ctx)
            else:
                await self._finalize_task(ctx)
    
    async def _adjust_plan(self, decision: Dict, ctx: MessageContext):
        """Adjust subtask plan based on Boss's decision"""
        # CRITICAL FIX: When Boss chooses "adjust_plan", it usually means verification failed
        # (e.g., Boss's verification code had a syntax error), so we should NOT accept the output.
        # Treat this as a REJECT and redelegate to Worker with feedback.
        logger.warning("[ADJUST] Boss's verification failed - treating as REJECT and redelegating")
        logger.warning(f"   Reasoning: {decision.get('reasoning', 'No reasoning provided')}")
        
        # Get current subtask ID
        if self.subtask_results:
            last_subtask_id = list(self.subtask_results.keys())[-1]
            
            # Redelegate with feedback explaining the issue
            feedback = decision.get('feedback', '') or decision.get('reasoning', '')
            if not feedback:
                feedback = "Verification could not complete. Please ensure output files contain actual transformed data with multiple columns (not just ID column)."
            
            logger.info(f"[ADJUST] Redelegating {last_subtask_id} with feedback: {feedback}")
            attempts = self.subtask_attempts.get(last_subtask_id, 0)
            self.subtask_attempts[last_subtask_id] = attempts + 1
            await self._redelegate_with_feedback(last_subtask_id, feedback, ctx)
        else:
            # No subtasks yet - continue with current plan
            logger.warning("[ADJUST] No subtasks to redelegate - continuing")
            self.current_subtask_idx += 1
            if self.current_subtask_idx < len(self.subtasks):
                await self._delegate_current_subtask(ctx)
            else:
                await self._finalize_task(ctx)
    
    async def _finalize_task(self, ctx: MessageContext):
        """Finalize task and report to orchestrator"""
        # CRITICAL: Validate current_task exists
        if not self.current_task:
            logger.error("[FINALIZE] No current task set - cannot finalize!")
            return
        
        # CRITICAL: Prevent duplicate finalization
        if self.task_finalized:
            logger.warning("[FINALIZE] Task already finalized, skipping duplicate call")
            return
        
        self.task_finalized = True
        logger.info(f"[FINALIZE] Boss finalizing task {self.current_task.task_id}")
        
        # Log completion summary
        logger.info(f"[FINALIZE] Task completion summary:")
        logger.info(f"  Total subtasks planned: {len(self.subtasks)}")
        logger.info(f"  Completed: {len(self.completed_subtasks)}")
        logger.info(f"  Results recorded: {len(self.subtask_results)}")
        
        # Check for incomplete subtasks
        incomplete = [s['id'] for s in self.subtasks if s['id'] not in self.completed_subtasks]
        if incomplete:
            logger.warning(f"[FINALIZE] {len(incomplete)} subtasks incomplete: {incomplete}")
        
        try:
            # Create task_files.json
            task_files_data = {
                "task_id": self.current_task.task_id,
                "subtasks": self.subtasks,
                "results": {
                    subtask_id: {
                        "status": result.status,
                        "files_created": result.files_created,
                        "summary": result.summary
                    }
                    for subtask_id, result in self.subtask_results.items()
                }
            }
            
            task_files_path = self.workspace_path / "task_files.json"
            with open(task_files_path, 'w') as f:
                json.dump(task_files_data, f, indent=2)
            
            logger.info(f"[FILES] Created task_files.json at {task_files_path}")
            
            # Update knowledge base with final summary
            all_files = []
            for result in self.subtask_results.values():
                for file_info in result.files_created:
                    if isinstance(file_info, dict):
                        all_files.append({
                            "filename": file_info.get("filename", "unknown_file"),
                            "absolute_path": file_info.get("absolute_path", "unknown_path")
                        })
                    else:
                        all_files.append(file_info)
            
            # Truncate results for summary to prevent huge strings
            results_truncated = {}
            for k, v in task_files_data['results'].items():
                summary_text = v.get("summary", "") or ""
                results_truncated[k] = {
                    "status": v.get("status", "unknown"),
                    "files_count": len(v.get("files_created", [])),
                    "summary": summary_text[:200] + ("..." if len(summary_text) > 200 else "")
                }
            
            summary = f"""Task {self.current_task.task_id} completed.
Subtasks: {len(self.subtasks)}
Files created: {len(all_files)} files
Results: {json.dumps(results_truncated, indent=2)}"""
            
            # Try to add to knowledge base, but don't block completion if it fails
            try:
                await self.tools.access_knowledge_base(
                    "add",
                    content=summary,
                    metadata={"task_id": self.current_task.task_id, "type": "task_summary"}
                )
            except Exception as kb_error:
                logger.warning(f"Failed to add task summary to knowledge base (non-critical): {kb_error}")
            
            # Extract just filenames (TaskCompletionMessage expects List[str], not List[Dict])
            filenames_only = []
            for file_info in all_files:
                if isinstance(file_info, dict):
                    filenames_only.append(file_info.get("filename", str(file_info)))
                else:
                    filenames_only.append(str(file_info))
            
            # Report completion to orchestrator
            await self._report_completion(ctx, "completed", summary, filenames_only)
        
        except Exception as e:
            logger.error(f"Error finalizing task: {e}", exc_info=True)
            await self._report_completion(ctx, "failed", f"Error: {str(e)}", [])
    
    async def _report_completion(self, ctx: MessageContext, status: str, summary: str, files_created: List[str]):
        """Report completion to orchestrator"""
        completion_msg = TaskCompletionMessage(
            task_id=self.current_task.task_id,
            status=status,
            summary=summary,
            task_files_json_path=str(self.workspace_path / "task_files.json"),
            files_created=files_created
        )
        
        logger.info(f"[REPORT] Boss reporting to orchestrator: {status}")
        await self.publish_message(
            completion_msg,
            topic_id=TopicId(self.orchestrator_topic_type, source=ctx.topic_id.source)
        )

