import logging
import time
import requests
from celery import shared_task
from django.conf import settings
from django.utils import timezone
from dashboard.models import IncidentAlert, AutomationAuditLog

logger = logging.getLogger(__name__)


class AWXTaskClient:
    def __init__(self):
        self.host = getattr(settings, 'AWX_HOST', 'http://localhost:8052').rstrip('/')
        self.auth = (getattr(settings, 'AWX_USERNAME', 'admin'), getattr(settings, 'AWX_PASSWORD', 'password'))

    def launch_job_template(self, template_id, extra_vars=None):
        url = f"{self.host}/api/v2/job_templates/{template_id}/launch/"
        payload = {'extra_vars': extra_vars} if extra_vars else {}
        try:
            res = requests.post(url, json=payload, auth=self.auth, timeout=10)
            if res.status_code in (200, 201):
                data = res.json()
                return {"success": True, "job_id": data.get("id")}
            return {"success": False, "error": f"AWX HTTP {res.status_code}: {res.text}"}
        except Exception as e:
            return {"success": False, "error": str(e)}


@shared_task(bind=True, max_retries=3)
def process_incident_alert_task(self, alert_id):
    """
    Celery task: Agentic analysis, risk scoring, and zero-touch vs HITL decision logic.
    """
    try:
        alert = IncidentAlert.objects.get(id=alert_id)
        logger.info(f"Running Agentic Triage & Risk Evaluation for Incident #{alert.id}: {alert.alert_name}")

        # 1. Simulate/Run Agent Analysis & Tool Selection
        alert_text = f"{alert.alert_name} on {alert.target_host}: {alert.summary}".lower()
        
        # Determine appropriate tool and template ID based on alert content
        if 'cpu' in alert_text or 'load' in alert_text:
            tool_name = 'awx_launch_job_template'
            tool_args = {'template_id': 1, 'extra_vars': {'target_host': alert.target_host, 'action': 'restart_service'}}
            risk_level = 'LOW'
            risk_reason = 'Service restart is a low-impact, idempotent remediation.'
        elif 'disk' in alert_text or 'storage' in alert_text:
            tool_name = 'awx_launch_job_template'
            tool_args = {'template_id': 2, 'extra_vars': {'target_host': alert.target_host, 'action': 'clean_tmp'}}
            risk_level = 'LOW'
            risk_reason = 'Clearing temporary files is safe and non-destructive.'
        else:
            tool_name = 'awx_launch_job_template'
            tool_args = {'template_id': 3, 'extra_vars': {'target_host': alert.target_host, 'action': 'failover_node'}}
            risk_level = 'HIGH'
            risk_reason = 'Node failover affects traffic routing and requires manual SRE verification.'

        # Store agent analysis and risk evaluation in payload
        payload = alert.payload if isinstance(alert.payload, dict) else {}
        payload['agent_analysis'] = {
            'root_cause': f"Automated analysis identified threshold breach on {alert.target_host}.",
            'recommended_action': {
                'tool_name': tool_name,
                'tool_args': tool_args
            },
            'risk_assessment': {
                'level': risk_level,
                'reason': risk_reason
            }
        }
        alert.payload = payload

        # 2. Dynamic Routing: Zero-Touch vs. HITL Approval
        if risk_level == 'LOW':
            alert.status = 'REMEDIATION_IN_PROGRESS'
            alert.save(update_fields=['status', 'payload'])
            logger.info(f"Zero-Touch Automation triggered for Incident #{alert.id} (Risk: LOW)")
            # Automatically dispatch execution
            execute_approved_action_task.delay(alert.id, tool_name, tool_args)
        else:
            alert.status = 'PENDING_APPROVAL'
            alert.save(update_fields=['status', 'payload'])
            logger.info(f"Incident #{alert.id} routed to HITL Approvals dashboard (Risk: {risk_level})")

        return f"Processed Incident #{alert.id} with Risk Level: {risk_level}"

    except IncidentAlert.DoesNotExist:
        logger.error(f"IncidentAlert ID {alert_id} not found.")
    except Exception as exc:
        logger.error(f"Error in process_incident_alert_task: {str(exc)}")
        raise self.retry(exc=exc, countdown=10)


@shared_task(bind=True, max_retries=2)
def execute_approved_action_task(self, alert_id, tool_name, tool_args):
    """
    Executes the approved remediation action via AWX and records the audit trail.
    """
    try:
        alert = IncidentAlert.objects.get(id=alert_id)
        logger.info(f"Executing approved action for Incident #{alert.id} using tool {tool_name}")

        client = AWXTaskClient()
        template_id = tool_args.get('template_id', 1)
        extra_vars = tool_args.get('extra_vars', {})

        result = client.launch_job_template(template_id, extra_vars)

        if result['success']:
            awx_job_id = result['job_id']
            alert.status = 'COMPLETED'
            alert.save(update_fields=['status'])

            AutomationAuditLog.objects.create(
                job_name=f"Auto-Remediation: {alert.alert_name}",
                awx_job_id=awx_job_id,
                requested_by='Agentic SRE AI',
                status='RUNNING',
                error_message=''
            )
            logger.info(f"AWX Job #{awx_job_id} successfully launched for Incident #{alert.id}")
        else:
            alert.status = 'FAILED'
            alert.save(update_fields=['status'])
            AutomationAuditLog.objects.create(
                job_name=f"Auto-Remediation Failed: {alert.alert_name}",
                requested_by='Agentic SRE AI',
                status='FAILED',
                error_message=result['error']
            )
            logger.error(f"Failed to launch AWX job for Incident #{alert.id}: {result['error']}")

    except Exception as exc:
        logger.error(f"Exception in execute_approved_action_task: {str(exc)}")
        raise self.retry(exc=exc, countdown=15)
