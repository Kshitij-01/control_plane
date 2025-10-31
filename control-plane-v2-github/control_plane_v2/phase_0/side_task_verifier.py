"""
Side Task Verifier - Checks if side tasks passed and decides whether to proceed
"""
import json
import logging
from pathlib import Path
from typing import Dict, Any, List

logger = logging.getLogger(__name__)


class SideTaskVerifier:
    """
    Verifies side task results and determines if pipeline should proceed.
    Critical failures will stop the pipeline.
    """
    
    def __init__(self, workspace_dir: Path):
        """
        Initialize Side Task Verifier
        
        Args:
            workspace_dir: Directory containing side task result files
        """
        self._workspace = workspace_dir
        logger.info(f"SideTaskVerifier initialized with workspace: {self._workspace}")
    
    def verify_and_decide(self, summary: Dict[str, Any]) -> Dict[str, Any]:
        """
        Verify side task results and decide if pipeline should proceed
        
        Args:
            summary: Summary from SideTaskSolver
            
        Returns:
            Decision dict with proceed flag and details
        """
        logger.info("="*80)
        logger.info("SIDE TASK VERIFIER - ANALYZING RESULTS")
        logger.info("="*80)
        
        total = summary['total']
        success = summary['success']
        failed = summary['failed']
        critical_failures = summary['critical_failures']
        
        logger.info(f"Total tasks: {total}")
        logger.info(f"Successful: {success}")
        logger.info(f"Failed: {failed}")
        logger.info(f"Critical failures: {critical_failures}")
        logger.info("")
        
        # Decision logic
        if critical_failures > 0:
            logger.error("CRITICAL FAILURES DETECTED")
            logger.error("="*80)
            
            for failure in summary['critical_failure_details']:
                task_id = failure['task_id']
                error = failure.get('error', failure.get('result', {}).get('message', 'Unknown error'))
                logger.error(f"  - {task_id}: {error}")
            
            logger.error("="*80)
            logger.error("PIPELINE CANNOT PROCEED - Critical verification failed")
            logger.error("Please fix the issues above and retry")
            logger.error("="*80)
            
            decision = {
                'proceed': False,
                'reason': 'Critical side tasks failed',
                'critical_failures': summary['critical_failure_details'],
                'recommendations': self._generate_recommendations(summary)
            }
        
        elif failed > 0:
            logger.warning("NON-CRITICAL FAILURES DETECTED")
            logger.warning("="*80)
            
            for result in summary['all_results']:
                if isinstance(result, dict) and not result.get('success') and not result.get('is_critical'):
                    task_id = result['task_id']
                    error = result.get('error', result.get('result', {}).get('message', 'Unknown error'))
                    logger.warning(f"  - {task_id}: {error}")
            
            logger.warning("="*80)
            logger.warning("PROCEEDING WITH WARNINGS - Non-critical tasks failed")
            logger.warning("Monitor the pipeline closely")
            logger.warning("="*80)
            
            decision = {
                'proceed': True,
                'reason': 'All critical checks passed, some non-critical warnings',
                'warnings': [r for r in summary['all_results'] if isinstance(r, dict) and not r.get('success')],
                'recommendations': self._generate_recommendations(summary)
            }
        
        else:
            logger.info("ALL VERIFICATIONS PASSED")
            logger.info("="*80)
            logger.info("All side tasks completed successfully")
            logger.info("Pipeline is ready to proceed to core tasks")
            logger.info("="*80)
            
            decision = {
                'proceed': True,
                'reason': 'All side tasks passed',
                'warnings': [],
                'recommendations': []
            }
        
        logger.info("")
        return decision
    
    def _generate_recommendations(self, summary: Dict[str, Any]) -> List[str]:
        """
        Generate generic recommendations based on failures.
        
        NOTE: This is intentionally NON-PRESCRIPTIVE. We don't pattern-match
        on keywords or make domain assumptions (database, file, API, etc.).
        The generated agents already provided detailed error context.
        """
        recommendations = []
        
        failed_count = summary['failed']
        if failed_count > 0:
            # Generic, domain-agnostic recommendations
            recommendations.append(
                "Review failed task logs above for specific error messages and root causes"
            )
            recommendations.append(
                "Check that all required resources and prerequisites are available"
            )
            recommendations.append(
                "Verify credentials, access permissions, and network connectivity as applicable"
            )
            recommendations.append(
                "Consult the detailed agent execution logs in the workspace directories"
            )
        
        return recommendations

