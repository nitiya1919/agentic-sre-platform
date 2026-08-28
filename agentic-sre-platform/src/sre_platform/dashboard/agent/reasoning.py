import logging
from dashboard.services.awx import AWXClient
from dashboard.models import AutomationAuditLog

logger = logging.getLogger(__name__)

class SREAgentEvaluator:
    def __init__(self, incident_alert):
        self.alert = incident_alert
        self.awx_client = AWXClient()

    def evaluate_and_plan(self):
        logger.info(f"SRE Agent evaluating alert: {self.alert.alert_name} on {self.alert.target_host}")
        
        self.alert.status = 'PROCESSING'
        self.alert.save()

        try:
            action_plan = self._generate_strategy()
            
            if action_plan['requires_approval']:
                self.alert.status = 'REQUIRES_APPROVAL'
            else:
                success, awx_job_id = self._execute_remediation(action_plan)
                self.alert.status = 'RESOLVED' if success else 'FAILED'
                
                # Log execution in Automation Audit Log
                AutomationAuditLog.objects.create(
                    job_name=action_plan.get('job_name', 'Manual/Shell Task'),
                    requested_by='SRE-Agent-Bot',
                    status='SUCCESS' if success else 'FAILED',
                    awx_job_id=awx_job_id
                )
                
            self.alert.save()
            return action_plan
            
        except Exception as e:
            logger.error(f"Agent evaluation failed: {str(e)}")
            self.alert.status = 'FAILED'
            self.alert.save()
            raise

    def _generate_strategy(self):
        alert_name = self.alert.alert_name.lower()
        
        if 'memory' in alert_name or 'highmemory' in alert_name:
            return {
                "diagnosis": "Memory utilization exceeded safe threshold.",
                "recommended_fix": "Trigger AWX Remediation Playbook: Restart App Services",
                "risk_level": "medium",
                "requires_approval": False,
                "awx_template_id": 12,  # Replace with your actual AWX Job Template ID
                "job_name": "Remediate-High-Memory-Usage",
                "extra_vars": {
                    "target_host": self.alert.target_host,
                    "alert_name": self.alert.alert_name,
                    "reason": self.alert.summary
                }
            }
        else:
            return {
                "diagnosis": "Unknown anomaly detected.",
                "recommended_fix": "Manual SRE investigation required.",
                "risk_level": "high",
                "requires_approval": True,
                "awx_template_id": None
            }

    def _execute_remediation(self, plan):
        template_id = plan.get('awx_template_id')
        if not template_id:
            logger.info("No AWX template mapped for this action plan.")
            return True, None

        logger.info(f"Triggering AWX Job Template ID {template_id}...")
        result = self.awx_client.launch_job_template(
            template_id=template_id,
            extra_vars=plan.get('extra_vars', {})
        )
        
        if result['success']:
            return True, result.get('job_id')
        return False, None