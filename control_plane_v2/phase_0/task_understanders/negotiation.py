"""
Task Negotiation Protocol

Sequential collaborative negotiation where Claude (lead) proposes classification
and GPT-5 (reviewer) provides feedback until satisfied.

Flow:
1. Claude generates initial proposal
2. GPT-5 reviews and suggests changes
3. Claude reviews suggestions, merges/modifies, explains decisions
4. GPT-5 reviews again (satisfied or more changes needed)
5. Loop until GPT-5 approves or max iterations
"""

import json
import logging
import re
from typing import Dict, List, Optional, Tuple

from autogen_core.models import ChatCompletionClient, SystemMessage, UserMessage, AssistantMessage, LLMMessage

from ..messages import (
    TaskClassificationProposal,
    NegotiationMessage,
    NegotiationResult,
    CoreTask,
    SideTask
)

logger = logging.getLogger(__name__)


class TaskNegotiator:
    """
    Facilitates sequential collaborative negotiation:
    - Claude is the lead analyst who generates and refines proposals
    - GPT-5 is the reviewer who validates and suggests improvements
    """
    
    def __init__(
        self,
        claude_client: ChatCompletionClient,
        gpt5_client: ChatCompletionClient,
        max_iterations: int = 3
    ):
        self._claude_client = claude_client
        self._gpt5_client = gpt5_client
        self._max_iterations = max_iterations
        
        # Chat histories for maintaining context
        self._claude_history: List[LLMMessage] = []
        self._gpt5_history: List[LLMMessage] = []
        
        logger.info(f"TaskNegotiator initialized with max_iterations={max_iterations} (sequential mode)")
    
    async def negotiate(
        self,
        claude_proposal: TaskClassificationProposal,
        gpt5_proposal: TaskClassificationProposal,  # We'll ignore this now, GPT-5 is reviewer only
        original_request = None  # The original TaskAnalysisRequest with manifest/connections
    ) -> NegotiationResult:
        # Store original_request for use in helper methods
        self._original_request = original_request
        """
        Sequential collaborative negotiation:
        1. Claude proposes (already done)
        2. GPT-5 reviews and suggests changes
        3. Claude refines based on feedback
        4. Loop until GPT-5 approves or max iterations
        
        Returns:
            NegotiationResult with final agreed classification
        """
        self._original_request = original_request  # Store for use in reviews
        logger.info("Starting sequential negotiation (Claude lead, GPT-5 reviewer)")
        
        # Initialize chat histories
        self._claude_history = [
            SystemMessage(content="""You are the lead technical analyst.
You have created a task classification. A senior reviewer (GPT-5) will now review it and suggest improvements.
Your job is to:
1. Listen to the reviewer's feedback
2. Decide which changes to accept, modify, or reject
3. Explain your reasoning for each decision
4. Provide an updated proposal

Be open to good suggestions but defend your technical analysis when warranted.""")
        ]
        
        self._gpt5_history = [
            SystemMessage(content="""You are a senior reviewer validating a task classification.
Your job is to:
1. Review the proposed classification for completeness and correctness
2. Suggest specific improvements (be constructive, not just critical)
3. After reviewing revisions, decide if you approve or need more changes
4. Be thorough but reasonable - don't be pedantic about minor details

Respond with JSON format:
{
  "status": "approved" or "changes_needed",
  "confidence": 0.0-1.0,
  "suggestions": [
    {"issue": "description", "suggestion": "specific change", "priority": "high/medium/low"}
  ],
  "reasoning": "your overall assessment",
  "approved_aspects": ["what's good about the proposal"]
}""")
        ]
        
        current_proposal = claude_proposal
        iteration = 0
        
        while iteration < self._max_iterations:
            iteration += 1
            logger.info(f"Negotiation iteration {iteration}/{self._max_iterations}")
            
            # GPT-5 reviews current proposal
            logger.info(f"  [Step 1] GPT-5 reviewing Claude's proposal...")
            review = await self._get_gpt5_review(current_proposal, iteration)
            
            if review["status"] == "approved":
                logger.info(f"  [APPROVED] GPT-5 satisfied with proposal after {iteration} iteration(s)")
                return NegotiationResult(
                    reached_agreement=True,
                    iterations=iteration,
                    final_proposal=current_proposal,
                    disagreements=[],
                    confidence=review.get("confidence", 0.9)
                )
            
            # GPT-5 wants changes
            issues_found = review.get("issues_found", [])
            logger.info(f"  [Step 2] GPT-5 requesting changes ({len(issues_found)} issues)")
            for idx, issue in enumerate(issues_found[:3], 1):  # Log first 3
                logger.info(f"    {idx}. {issue[:80]}...")
            
            if iteration >= self._max_iterations:
                logger.warning(f"Max iterations reached. GPT-5 not fully satisfied.")
                break
            
            # If GPT-5 provided corrected side tasks, apply them directly (unless skip_side_tasks is set)
            if "corrected_side_tasks" in review and review["corrected_side_tasks"]:
                # Check if skip_side_tasks is set
                skip_side_tasks = False
                if self._original_request:
                    additional_context = getattr(self._original_request, 'additional_context', {})
                    if additional_context:
                        transformation_config = additional_context.get('transformation_config', {})
                        skip_side_tasks = transformation_config.get('skip_side_tasks', False)
                
                if skip_side_tasks:
                    logger.info(f"  [Step 3] GPT-5 suggested side task corrections, but skip_side_tasks=true - ignoring corrections")
                else:
                    logger.info(f"  [Step 3] Applying GPT-5's direct corrections to side tasks...")
                
                current_proposal = self._apply_gpt5_corrections(current_proposal, review["corrected_side_tasks"])
                logger.info(f"  [Step 4] Proposal updated, ready for next review")
            else:
                # Fallback: Claude refines based on GPT-5's feedback
                logger.info(f"  [Step 3] Claude refining proposal based on feedback...")
                refined_proposal = await self._get_claude_refinement(current_proposal, review)
                
                if refined_proposal is None:
                    logger.warning("Claude failed to refine proposal, using current")
                    break
                
                current_proposal = refined_proposal
                logger.info(f"  [Step 4] Refined proposal ready for next review")
        
        # Max iterations or refinement failed
        logger.warning(f"Negotiation completed after {iteration} iterations without full approval")
        
        # Convert suggestion dicts to strings for disagreements field
        disagreement_strings = []
        for sug in review.get("suggestions", []):
            if isinstance(sug, dict):
                priority = sug.get('priority', 'unknown')
                issue = sug.get('issue', str(sug))
                disagreement_strings.append(f"[{priority}] {issue}")
            else:
                disagreement_strings.append(str(sug))
        
        return NegotiationResult(
            reached_agreement=False,
            iterations=iteration,
            final_proposal=current_proposal,
            disagreements=disagreement_strings,
            confidence=0.75  # Decent confidence, but not fully validated
        )
    
    def _apply_gpt5_corrections(
        self,
        proposal: TaskClassificationProposal,
        corrected_tasks: List[Dict]
    ) -> TaskClassificationProposal:
        """Apply GPT-5's direct corrections to side tasks"""
        from ..messages import SideTask
        
        # Check if skip_side_tasks is set via original_request
        skip_side_tasks = False
        if self._original_request:
            # _original_request is a Pydantic object, access attributes directly
            additional_context = getattr(self._original_request, 'additional_context', {})
            if additional_context:
                transformation_config = additional_context.get('transformation_config', {})
                skip_side_tasks = transformation_config.get('skip_side_tasks', False)
        
        # If skip_side_tasks is true, don't apply corrections (keep empty list)
        if skip_side_tasks:
            updated_side_tasks = []
        else:
            # Convert corrected tasks to SideTask objects
            updated_side_tasks = []
            for task in corrected_tasks:
                updated_side_tasks.append(SideTask(
                    id=task.get("id", "side_" + str(len(updated_side_tasks) + 1)),
                    description=task["description"],
                    priority=task.get("priority", "high"),
                    blocking=task.get("blocking", True),
                    estimated_duration=task.get("estimated_duration", "30 seconds"),
                    verification_needed=task.get("verification_needed", True),
                    dependencies=task.get("dependencies", [])
                ))
        
        # Create new proposal with updated side tasks
        return TaskClassificationProposal(
            agent_id=proposal.agent_id,
            agent_type=proposal.agent_type,
            core_tasks=proposal.core_tasks,  # Keep original core tasks
            side_tasks=updated_side_tasks,    # Use GPT-5's corrected side tasks (or empty if skip)
            execution_order=proposal.execution_order,
            reasoning=f"{proposal.reasoning}\n\n[GPT-5 Corrections Applied] Fixed placeholder references and incomplete descriptions." if not skip_side_tasks else proposal.reasoning,
            confidence=proposal.confidence,
            concerns=proposal.concerns
        )
    
    async def _get_gpt5_review(
        self,
        proposal: TaskClassificationProposal,
        iteration: int
    ) -> Dict:
        """
        GPT-5 reviews Claude's proposal and provides feedback
        
        Returns dict with:
        - status: "approved" or "changes_needed"
        - confidence: 0.0-1.0
        - suggestions: list of {issue, suggestion, priority}
        - reasoning: overall assessment
        """
        # Build review prompt with available context
        proposal_json = json.dumps(proposal.model_dump(), indent=2)
        
        # Include context about what information is ACTUALLY available
        context_info = ""
        if self._original_request:
            context_info = f"""
IMPORTANT - AVAILABLE INFORMATION:
This is ALL the information we have available:

TASK DESCRIPTION:
{self._original_request.task_description}

"""
            # Include FILES with content (especially manifest)
            if self._original_request.files:
                context_info += f"FILES ({len(self._original_request.files)} available):\n"
                for f in self._original_request.files:
                    size_info = f" ({f.size_mb}MB)" if f.size_mb else ""
                    context_info += f"- {f.path}{size_info}\n"
                    if f.description:
                        context_info += f"  Purpose: {f.description}\n"
                    
                    # Include manifest content for GPT-5 to review
                    if f.path and (f.path.endswith('.json') or 'manifest' in f.path.lower()):
                        try:
                            import os
                            if os.path.exists(f.path):
                                with open(f.path, 'r', encoding='utf-8') as file:
                                    manifest_content = file.read()
                                    context_info += f"  MANIFEST CONTENT:\n{manifest_content[:3000]}\n"  # First 3000 chars
                        except Exception as e:
                            logger.debug(f"Could not read manifest {f.path}: {e}")
            
            # Include CONNECTIONS details
            if self._original_request.connections:
                context_info += f"\nCONNECTIONS ({len(self._original_request.connections)} available):\n"
                for conn in self._original_request.connections:
                    context_info += f"- {conn.id} (Type: {conn.type})\n"
                    if conn.host:
                        context_info += f"  Host: {conn.host}\n"
                    if conn.database:
                        context_info += f"  Database: {conn.database}\n"
            
            # Include ADDITIONAL CONTEXT
            if self._original_request.additional_context:
                context_info += f"\nADDITIONAL CONTEXT:\n"
                for key, value in self._original_request.additional_context.items():
                    context_info += f"- {key}: {str(value)[:200]}\n"
            
            # Check if skip_side_tasks is set
            skip_side_tasks_flag = False
            if self._original_request:
                additional_context = getattr(self._original_request, 'additional_context', {})
                if additional_context:
                    transformation_config = additional_context.get('transformation_config', {})
                    skip_side_tasks_flag = transformation_config.get('skip_side_tasks', False)
            
            if skip_side_tasks_flag:
                context_info += """
CRITICAL CONSTRAINTS:
- **skip_side_tasks=true** - DO NOT provide "corrected_side_tasks" in your response
- Side tasks are being skipped per user request
- Focus ONLY on reviewing core tasks
- If you find issues with core task descriptions, note them in "issues_found"
"""
            else:
                context_info += """
CRITICAL CONSTRAINTS:
- Side tasks = SYSTEM checks ONLY (connections work, files exist, libraries importable)
- Side tasks are NOT for data validation, business logic, or permission checking beyond basic connectivity
- Downstream agents will handle HOW to verify - we just need WHAT to verify + credentials
- Keep descriptions GOAL-oriented (what to check), not SCRIPT-like (step-by-step how)
- Don't ask for information that doesn't exist in the available context above
"""
        
        review_prompt = f"""Review this task classification proposal:

{proposal_json}

{context_info}

Check for placeholder/template issues:
1. **Placeholders** - Are there phrases like "from context", "specified in", "{{variable}}", "configured connection"?
2. **Missing targets** - Are connection targets specified (host, database, table names)?
3. **File references** - Are file names/paths clear? (Use relative paths like 'data/input.csv' - the catalog will resolve absolute paths during execution)

NOTE: 
- Credentials are in the manifest and automatically provided to agents. Task descriptions should reference "using provided credentials" not list passwords.
- File paths should be relative (e.g., 'outputs/result.json') - the file catalog will resolve absolute paths at runtime
- Agents will use the catalog to find files from previous tasks automatically

If you find ANY placeholders or template language:
- Set status="changes_needed"
- Provide "corrected_side_tasks" array with FIXED descriptions
- Replace ALL placeholder references with actual values from the manifest

If everything is specific and complete, set status="approved".

Iteration {iteration}: {"This is the initial proposal" if iteration == 1 else "Reviewing refined proposal"}

Response JSON format:
{{
  "status": "approved" or "changes_needed",
  "confidence": 0.0-1.0,
  "issues_found": ["list of specific issues"],
  "corrected_side_tasks": [  // ONLY if status="changes_needed"
    {{
      "id": "side_1",
      "description": "FIXED description with actual values, not placeholders",
      "priority": "critical/high/medium/low",
      "blocking": true/false,
      "estimated_duration": "30 seconds"
    }}
  ],
  "reasoning": "why changes needed or why approved"
}}
"""
        
        # Add to GPT-5's chat history
        self._gpt5_history.append(UserMessage(content=review_prompt, source="user"))
        
        # Get review
        response = await self._gpt5_client.create(self._gpt5_history)
        
        # Add response to history
        response_text = str(response.content)
        self._gpt5_history.append(AssistantMessage(content=response_text, source="assistant"))
        
        # Parse JSON review
        review = self._parse_json_response(response_text)
        
        if not review:
            logger.warning("Failed to parse GPT-5 review, defaulting to changes_needed")
            return {
                "status": "changes_needed",
                "confidence": 0.5,
                "suggestions": [{"issue": "Parse error", "suggestion": "Could not parse review", "priority": "high"}],
                "reasoning": "Failed to parse review response"
            }
        
        return review
    
    async def _get_claude_refinement(
        self,
        current_proposal: TaskClassificationProposal,
        gpt5_review: Dict
    ) -> Optional[TaskClassificationProposal]:
        """
        Claude reviews GPT-5's suggestions and refines the proposal
        
        Returns updated TaskClassificationProposal or None if failed
        """
        # Build refinement prompt
        current_json = json.dumps(current_proposal.model_dump(), indent=2)
        review_json = json.dumps(gpt5_review, indent=2)
        
        refinement_prompt = f"""The reviewer has provided feedback on your proposal.

YOUR CURRENT PROPOSAL:
{current_json}

REVIEWER'S FEEDBACK:
{review_json}

Please review the suggestions and update your proposal accordingly.
Focus on high-priority suggestions first.

Respond with:
{{
  "changes_made": "Brief summary of key changes (2-3 sentences)",
  "updated_proposal": {{
    "core_tasks": [...],
    "side_tasks": [...],
    "execution_order": [...],
    "reasoning": "...",
    "confidence": 0.0-1.0,
    "concerns": [...]
  }}
}}

Keep it concise - just make the improvements and summarize what changed.
"""
        
        # Add to Claude's chat history
        self._claude_history.append(UserMessage(content=refinement_prompt, source="user"))
        
        # Get refinement
        response = await self._claude_client.create(self._claude_history)
        
        # Add response to history
        response_text = str(response.content)
        self._claude_history.append(AssistantMessage(content=response_text, source="assistant"))
        
        # Parse refinement
        refinement = self._parse_json_response(response_text)
        
        if not refinement or "updated_proposal" not in refinement:
            logger.error("Failed to parse Claude's refinement")
            return None
        
        try:
            updated_data = refinement["updated_proposal"]
            
            # Log Claude's changes summary
            changes_summary = refinement.get("changes_made", "No summary provided")
            logger.info(f"    Claude's changes: {changes_summary[:120]}...")
            
            # Flatten execution_order if Claude returned nested lists
            raw_exec_order = updated_data.get("execution_order", [])
            execution_order = []
            for item in raw_exec_order:
                if isinstance(item, list):
                    execution_order.extend(item)
                else:
                    execution_order.append(item)
            
            # Reconstruct proposal
            refined_proposal = TaskClassificationProposal(
                agent_id=current_proposal.agent_id,
                agent_type=current_proposal.agent_type,
                core_tasks=[CoreTask(**task) for task in updated_data.get("core_tasks", [])],
                side_tasks=[SideTask(**task) for task in updated_data.get("side_tasks", [])],
                execution_order=execution_order,
                reasoning=updated_data.get("reasoning", current_proposal.reasoning),
                confidence=updated_data.get("confidence", current_proposal.confidence),
                concerns=updated_data.get("concerns", [])
            )
            
            return refined_proposal
            
        except Exception as e:
            logger.error(f"Error reconstructing refined proposal: {e}")
            return None
    
    def _parse_json_response(self, text: str) -> Optional[Dict]:
        """Extract and parse JSON from LLM response"""
        try:
            # Try direct parse first
            return json.loads(text)
        except:
            pass
        
        # Try to find JSON block
        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(0))
            except:
                pass
        
        return None

