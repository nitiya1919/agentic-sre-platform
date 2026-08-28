import os
import requests

class AWXClient:
    def __init__(self):
        self.base_url = os.getenv('AWX_BASE_URL', '')
        self.token = os.getenv('AWX_TOKEN', '')

    def launch_job_template(self, template_id, extra_vars=None):
        headers = {
            'Authorization': f'Bearer {self.token}',
            'Content-Type': 'application/json',
        }
        url = f"{self.base_url.rstrip('/')}/api/v2/job_templates/{template_id}/launch/"
        response = requests.post(url, json={'extra_vars': extra_vars or {}}, headers=headers, verify=False)
        return response.json()