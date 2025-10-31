"""
Task Classifier Coordinator

Orchestrates Agents 1a and 1b to analyze and classify tasks
"""

import logging
from typing import Dict

from autogen_core import SingleThreadedAgentRuntime, DefaultTopicId, CancellationToken
from autogen_core.models import ChatCompletionClient

from .messages import TaskAnalysisRequest, TaskClassification, NegotiationResult, TaskClassificationProposal
from .task_understanders import (
    ClaudeTaskUnderstander,
    GPT5TaskUnderstander,
    TaskNegotiator,
    OverseerAgent
)

logger = logging.getLogger(__name__)


class TaskClassifier:
    """
    Coordinates the task classification process using two collaborating agents
    """
    
    def __init__(
        self,
        claude_client: ChatCompletionClient,
        gpt5_client: ChatCompletionClient,
        runtime: SingleThreadedAgentRuntime,
        overseer_client: ChatCompletionClient = None,
        max_negotiation_iterations: int = 3,
        max_overseer_iterations: int = 2
    ):
        self._claude_client = claude_client
        self._gpt5_client = gpt5_client
        self._runtime = runtime
        self._overseer_client = overseer_client or claude_client  # Default to Claude if not provided
        self._max_negotiation_iterations = max_negotiation_iterations
        self._max_overseer_iterations = max_overseer_iterations
        
        logger.info("TaskClassifier initialized with overseer quality control")
    
    async def classify_task(self, request: TaskAnalysisRequest) -> TaskClassification:
        """
        Classify a task using sequential collaborative review
        
        Process:
        1. Claude (lead) analyzes and generates initial proposal
        2. GPT-5 (reviewer) reviews and suggests improvements
        3. Claude refines based on feedback (iterative)
        4. Loop until GPT-5 approves or max iterations
        5. Overseer performs final quality control
        """
        logger.info(f"Classifying task: {request.task_id}")
        
        logger.info("Starting analysis...")
        
        # Claude generates initial proposal (GPT-5 will review, not analyze independently)
        logger.info("[1/2] Claude generating initial proposal...")
        claude_proposal = await self._get_claude_analysis(request)
        
        # Sequential negotiation: GPT-5 reviews Claude's work
        logger.info("[2/2] Starting collaborative review (Claude + GPT-5)...")
        negotiator = TaskNegotiator(
            self._claude_client,
            self._gpt5_client,
            max_iterations=self._max_negotiation_iterations
        )
        
        # Pass same proposal twice (GPT-5's role is reviewer, not independent analyst)
        # Also pass original request so GPT-5 knows what information is available
        negotiation_result = await negotiator.negotiate(claude_proposal, claude_proposal, request)
        
        # Get initial proposal from negotiation
        if negotiation_result.final_proposal is None:
            # Fallback to Claude's proposal
            logger.warning("No final proposal from negotiation, using Claude's")
            final_proposal = claude_proposal
        else:
            final_proposal = negotiation_result.final_proposal
        
        # Overseer review loop
        logger.info("[4/4] Overseer quality control review...")
        overseer = OverseerAgent(self._overseer_client)
        
        overseer_iteration = 0
        approved = False
        while not approved and overseer_iteration < self._max_overseer_iterations:
            overseer_iteration += 1
            logger.info(f"Overseer review iteration {overseer_iteration}/{self._max_overseer_iterations}")
            
            approved, review_report = await overseer.review_classification(request, final_proposal)
            
            if approved:
                logger.info("Overseer approved the classification")
                break
            else:
                logger.warning(f"Overseer found {len(review_report.get('issues', []))} issues")
                logger.warning(f"Overseer feedback: {review_report.get('feedback_to_analysts', 'No feedback provided')}")
                for idx, issue in enumerate(review_report.get('issues', []), 1):
                    logger.warning(f"  Issue {idx}: [{issue.get('severity', 'unknown')}] {issue.get('description', 'No description')}")
                
                if overseer_iteration < self._max_overseer_iterations:
                    logger.info("Asking Claude to revise based on Overseer feedback...")
                    
                    # Get revised proposal from Claude with overseer feedback
                    claude_proposal = await self._get_claude_analysis_with_feedback(
                        request, 
                        final_proposal, 
                        review_report
                    )
                    
                    # Re-run collaborative review with GPT-5
                    negotiation_result = await negotiator.negotiate(claude_proposal, claude_proposal, request)
                    final_proposal = negotiation_result.final_proposal or claude_proposal
                else:
                    logger.error("Max overseer iterations reached without approval")
                    logger.error(f"CLASSIFICATION REJECTED - {len(review_report.get('issues', []))} unresolved issues")
                    raise ValueError(
                        f"Overseer rejected classification after {self._max_overseer_iterations} iterations. "
                        f"Unresolved issues: {review_report.get('issues', [])}"
                    )
        
        # If we exit the loop without approval, fail
        if not approved:
            logger.error("CLASSIFICATION FAILED - Overseer did not approve")
            raise ValueError("Classification was not approved by Overseer quality control")
        
        classification = TaskClassification(
            task_id=request.task_id,
            core_tasks=final_proposal.core_tasks,
            side_tasks=final_proposal.side_tasks,
            execution_order=final_proposal.execution_order,
            agreements=[
                f"Reached agreement after {negotiation_result.iterations} negotiation rounds",
                f"Confidence: {negotiation_result.confidence:.2f}"
            ] if negotiation_result.reached_agreement else [
                f"Could not reach full agreement after {negotiation_result.iterations} rounds",
                f"Using {final_proposal.agent_id}'s classification",
                f"Confidence: {negotiation_result.confidence:.2f} (reduced due to disagreement)"
            ],
            confidence=negotiation_result.confidence,
            negotiation_summary=self._create_summary(
                claude_proposal,
                negotiation_result
            )
        )
        
        logger.info(f"Classification complete: {len(classification.core_tasks)} core, {len(classification.side_tasks)} side tasks")
        
        return classification
    
    def _create_summary(self, claude_proposal, negotiation_result: NegotiationResult) -> str:
        """Create a summary of the sequential review process"""
        lines = []
        
        lines.append("TASK CLASSIFICATION SUMMARY")
        lines.append("="*60)
        
        lines.append(f"\nClaude's Initial Proposal:")
        lines.append(f"  Core Tasks: {len(claude_proposal.core_tasks)}")
        lines.append(f"  Side Tasks: {len(claude_proposal.side_tasks)}")
        lines.append(f"  Confidence: {claude_proposal.confidence:.2f}")
        
        lines.append(f"\nSequential Collaborative Review (Claude + GPT-5):")
        lines.append(f"  Review Iterations: {negotiation_result.iterations}")
        lines.append(f"  GPT-5 Approved: {negotiation_result.reached_agreement}")
        lines.append(f"  Final Confidence: {negotiation_result.confidence:.2f}")
        
        if negotiation_result.disagreements:
            lines.append(f"\nOutstanding Issues from GPT-5:")
            for d in negotiation_result.disagreements:
                if isinstance(d, dict):
                    issue = d.get('issue', str(d))
                    priority = d.get('priority', 'medium')
                    lines.append(f"  - [{priority.upper()}] {issue}")
                else:
                    lines.append(f"  - {d}")
        
        if negotiation_result.final_proposal:
            lines.append(f"\nFinal Classification:")
            lines.append(f"  Agent: {negotiation_result.final_proposal.agent_id}")
            lines.append(f"  Core Tasks: {len(negotiation_result.final_proposal.core_tasks)}")
            lines.append(f"  Side Tasks: {len(negotiation_result.final_proposal.side_tasks)}")
        
        return "\n".join(lines)
    
    async def _get_claude_analysis(self, request: TaskAnalysisRequest):
        """Get analysis from Claude 4.5"""
        agent = ClaudeTaskUnderstander(self._claude_client)
        return await agent._analyze(request)
    
    async def _get_gpt5_analysis(self, request: TaskAnalysisRequest):
        """Get analysis from GPT-5"""
        agent = GPT5TaskUnderstander(self._gpt5_client, reasoning_effort="medium")
        return await agent._analyze(request)
    
    async def _get_claude_analysis_with_feedback(
        self,
        request: TaskAnalysisRequest,
        previous_proposal: TaskClassificationProposal,
        overseer_feedback: Dict
    ):
        """Get revised analysis from Claude with overseer feedback"""
        # Build feedback message with context
        feedback_message = f"""
REVISION REQUEST - Your previous classification needs improvement.

PREVIOUS CLASSIFICATION:
- Core Tasks: {len(previous_proposal.core_tasks)} tasks
- Side Tasks: {len(previous_proposal.side_tasks)} tasks

OVERSEER FEEDBACK:
{overseer_feedback.get('feedback_to_analysts', 'Please address the issues below.')}

SPECIFIC ISSUES TO FIX:
"""
        for idx, issue in enumerate(overseer_feedback.get('issues', []), 1):
            feedback_message += f"\n{idx}. [{issue.get('severity', 'unknown').upper()}] {issue.get('description', 'No description')}"
            if issue.get('suggestion'):
                feedback_message += f"\n   Suggestion: {issue['suggestion']}"
        
        feedback_message += "\n\nPlease revise your classification to address ALL the issues above."
        
        # Create enhanced request with feedback context
        enhanced_request = TaskAnalysisRequest(
            task_id=request.task_id,
            task_description=request.task_description + f"\n\n{feedback_message}",
            connections=request.connections,
            files=request.files,
            constraints=request.constraints,
            additional_context=request.additional_context
        )
        
        agent = ClaudeTaskUnderstander(self._claude_client)
        return await agent._analyze(enhanced_request)
    
    async def _get_gpt5_analysis_with_feedback(
        self,
        request: TaskAnalysisRequest,
        previous_proposal: TaskClassificationProposal,
        overseer_feedback: Dict
    ):
        """Get revised analysis from GPT-5 with overseer feedback"""
        # Build feedback message with context
        feedback_message = f"""
REVISION REQUEST - Your previous classification needs improvement.

PREVIOUS CLASSIFICATION:
- Core Tasks: {len(previous_proposal.core_tasks)} tasks
- Side Tasks: {len(previous_proposal.side_tasks)} tasks

OVERSEER FEEDBACK:
{overseer_feedback.get('feedback_to_analysts', 'Please address the issues below.')}

SPECIFIC ISSUES TO FIX:
"""
        for idx, issue in enumerate(overseer_feedback.get('issues', []), 1):
            feedback_message += f"\n{idx}. [{issue.get('severity', 'unknown').upper()}] {issue.get('description', 'No description')}"
            if issue.get('suggestion'):
                feedback_message += f"\n   Suggestion: {issue['suggestion']}"
        
        feedback_message += "\n\nPlease revise your classification to address ALL the issues above."
        
        # Create enhanced request with feedback context
        enhanced_request = TaskAnalysisRequest(
            task_id=request.task_id,
            task_description=request.task_description + f"\n\n{feedback_message}",
            connections=request.connections,
            files=request.files,
            constraints=request.constraints,
            additional_context=request.additional_context
        )
        
        agent = GPT5TaskUnderstander(self._gpt5_client, reasoning_effort="medium")
        return await agent._analyze(enhanced_request)

