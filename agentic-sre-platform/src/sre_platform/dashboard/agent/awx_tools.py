import os
import json
import requests
from typing import Optional, Dict, Any

AWX_HOST = os.getenv("AWX_BASE_URL", "http://localhost:8013").rstrip("/")
AWX_TOKEN = os.getenv("AWX_TOKEN", "")
AWX_VERIFY_SSL = os.getenv("AWX_VERIFY_SSL", "False").lower() in ("true", "1")

def _get_headers() -> Dict[str, str]:
    """Helper to generate standard authorization headers for AWX REST API."""
    return {
        "Authorization": f"Bearer {AWX_TOKEN}",
        "Content-Type": "application/json",
    }

def awx_list_job_templates(search_name: Optional[str] = None) -> str:
    """
    Search and list available AWX Job Templates (Ansible playbooks) to identify mitigation playbooks.

    Args:
        search_name: Optional substring to search job templates by name (e.g., 'restart', 'disk_cleanup').

    Returns:
        JSON string containing matching job template IDs, names, descriptions, and job types.
    """
    url = f"{AWX_HOST}/api/v2/job_templates/"
    params = {"order_by": "name"}
    if search_name:
        params["name__icontains"] = search_name

    try:
        response = requests.get(
            url, headers=_get_headers(), params=params, verify=AWX_VERIFY_SSL, timeout=10
        )
        response.raise_for_status()
        data = response.json()
        
        templates = [
            {
                "id": jt["id"],
                "name": jt["name"],
                "description": jt.get("description", ""),
                "job_type": jt.get("job_type", "run"),
            }
            for jt in data.get("results", [])
        ]
        return json.dumps({"status": "success", "count": len(templates), "templates": templates})
    except Exception as e:
        return json.dumps({"status": "error", "message": f"Failed to fetch job templates: {str(e)}"})


def awx_launch_job_template(job_template_id: int, extra_vars: Optional[Dict[str, Any]] = None) -> str:
    """
    Launch an AWX Job Template by ID to execute an Ansible playbook across managed infrastructure.

    Args:
        job_template_id: The integer ID of the job template to trigger.
        extra_vars: Dictionary of key-value parameters to pass to the playbook (e.g., {'target_host': 'web01', 'action': 'restart'}).

    Returns:
        JSON string containing the launched AWX Job ID, status, and execution details.
    """
    url = f"{AWX_HOST}/api/v2/job_templates/{job_template_id}/launch/"
    payload = {}
    if extra_vars:
        payload["extra_vars"] = extra_vars

    try:
        response = requests.post(
            url, headers=_get_headers(), json=payload, verify=AWX_VERIFY_SSL, timeout=10
        )
        response.raise_for_status()
        data = response.json()
        return json.dumps({
            "status": "success",
            "job_id": data.get("job"),
            "job_template": data.get("job_template_name"),
            "execution_status": data.get("status"),
        })
    except Exception as e:
        return json.dumps({"status": "error", "message": f"Failed to launch job template {job_template_id}: {str(e)}"})


def awx_get_job_status(job_id: int) -> str:
    """
    Check the current execution status and timing metrics of a running or completed AWX Job.

    Args:
        job_id: The integer ID of the launched AWX job.

    Returns:
        JSON string containing job status ('pending', 'running', 'successful', 'failed'), status breakdown, and duration.
    """
    url = f"{AWX_HOST}/api/v2/jobs/{job_id}/"

    try:
        response = requests.get(url, headers=_get_headers(), verify=AWX_VERIFY_SSL, timeout=10)
        response.raise_for_status()
        data = response.json()
        return json.dumps({
            "status": "success",
            "job_id": job_id,
            "execution_status": data.get("status"),
            "failed": data.get("failed", False),
            "elapsed_seconds": data.get("elapsed", 0),
            "started": data.get("started"),
            "finished": data.get("finished"),
        })
    except Exception as e:
        return json.dumps({"status": "error", "message": f"Failed to fetch status for job {job_id}: {str(e)}"})


def awx_get_job_stdout(job_id: int) -> str:
    """
    Fetch the standard console stdout logs of an executed AWX Ansible job for error diagnosis.

    Args:
        job_id: The integer ID of the executed AWX job.

    Returns:
        JSON string with the raw stdout log snippet from Ansible playbook execution.
    """
    url = f"{AWX_HOST}/api/v2/jobs/{job_id}/stdout/"
    params = {"format": "txt"}

    try:
        response = requests.get(
            url, headers=_get_headers(), params=params, verify=AWX_VERIFY_SSL, timeout=10
        )
        response.raise_for_status()
        stdout_content = response.text
        # Truncate extremely long stdout logs to fit context windows cleanly
        if len(stdout_content) > 4000:
            stdout_content = stdout_content[-4000:] + "\n...[stdout truncated for brevity]"

        return json.dumps({"status": "success", "job_id": job_id, "stdout": stdout_content})
    except Exception as e:
        return json.dumps({"status": "error", "message": f"Failed to fetch stdout for job {job_id}: {str(e)}"})
