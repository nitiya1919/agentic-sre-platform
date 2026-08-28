import logging
import requests
from django.conf import settings

logger = logging.getLogger(__name__)

class AWXClient:
    """
    Client for interacting with AWX / Ansible Automation Platform REST API.
    """
    def __init__(self):
        # These can be configured in settings.py or /etc/agentic-sre.env
        self.base_url = getattr(settings, 'AWX_HOST', 'http://localhost:8013').rstrip('/')
        self.token = getattr(settings, 'AWX_TOKEN', '')
        self.verify_ssl = getattr(settings, 'AWX_VERIFY_SSL', False)

    def launch_job_template(self, template_id, extra_vars=None):
        """
        Launches an AWX Job Template by ID with optional extra variables.
        """
        url = f"{self.base_url}/api/v2/job_templates/{template_id}/launch/"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.token}" if self.token else None
        }
        # Fallback to basic auth if token is not provided (or use session auth)
        auth = None if self.token else (getattr(settings, 'AWX_USER', 'admin'), getattr(settings, 'AWX_PASSWORD', ''))

        payload = {}
        if extra_vars:
            payload["extra_vars"] = extra_vars

        try:
            response = requests.post(
                url, 
                json=payload, 
                headers={k: v for k, v in headers.items() if v},
                auth=auth,
                verify=self.verify_ssl,
                timeout=10
            )
            
            if response.status_code in [200, 201]:
                data = response.json()
                job_id = data.get('job') or data.get('id')
                logger.info(f"Successfully triggered AWX Job ID: {job_id} for template {template_id}")
                return {"success": True, "job_id": job_id, "response": data}
            else:
                logger.error(f"Failed to launch AWX job. Status: {response.status_code}, Body: {response.text}")
                return {"success": False, "error": response.text}
                
        except Exception as e:
            logger.error(f"Exception occurred while calling AWX API: {str(e)}")
            return {"success": False, "error": str(e)}