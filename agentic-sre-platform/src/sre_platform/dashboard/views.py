import json
import logging
import re
import requests
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q, Count
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.utils import timezone

from dashboard.models import IncidentAlert, AutomationAuditLog, AuditOutbox
from dashboard.tasks import process_incident_alert_task, execute_approved_action_task

logger = logging.getLogger(__name__)


# ==========================================
# AWX REST API Client Helper
# ==========================================
class AWXClient:
    def __init__(self):
        self.host = getattr(settings, 'AWX_HOST', 'http://localhost:8052').rstrip('/')
        self.username = getattr(settings, 'AWX_USERNAME', 'admin')
        self.password = getattr(settings, 'AWX_PASSWORD', 'password')
        self.auth = (self.username, self.password)

    def launch_job_template(self, template_id, extra_vars=None):
        url = f"{self.host}/api/v2/job_templates/{template_id}/launch/"
        payload = {}
        if extra_vars:
            payload['extra_vars'] = extra_vars
        
        try:
            res = requests.post(url, json=payload, auth=self.auth, timeout=10)
            if res.status_code in (200, 201):
                data = res.json()
                return {"success": True, "job_id": data.get("id")}
            else:
                return {"success": False, "error": f"AWX API HTTP {res.status_code}: {res.text}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_job_stdout(self, job_id):
        url = f"{self.host}/api/v2/jobs/{job_id}/stdout/?format=txt"
        try:
            res = requests.get(url, auth=self.auth, timeout=10)
            if res.status_code == 200:
                # Strip ANSI escape sequence formatting for clean rendering
                clean_text = re.sub(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])', '', res.text)
                return clean_text
            return f"Error retrieving logs (HTTP {res.status_code})"
        except Exception as e:
            return f"Exception fetching stdout: {str(e)}"

    def get_job_status(self, job_id):
        url = f"{self.host}/api/v2/jobs/{job_id}/"
        try:
            res = requests.get(url, auth=self.auth, timeout=10)
            if res.status_code == 200:
                return res.json().get('status', 'unknown')
            return 'unknown'
        except Exception:
            return 'error'


# ==========================================
# Main Dashboard & Log Management
# ==========================================
def index(request):
    """
    Main SRE Command Center Dashboard View.
    Handles stats computation, incident listings, filtering, search, pagination, and bulk deletion.
    """
    # 1. Handle Bulk Actions (e.g., Delete Selected Audit Logs)
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'delete_selected':
            log_ids = request.POST.getlist('log_ids')
            if log_ids:
                deleted_count, _ = AutomationAuditLog.objects.filter(id__in=log_ids).delete()
                messages.success(request, f"Successfully deleted {deleted_count} audit log entry/entries.")
            else:
                messages.warning(request, "No logs were selected for deletion.")
            return redirect('index')

    # 2. Extract Filter Query Parameters
    search_query = request.GET.get('search', '').strip()
    status_filter = request.GET.get('status', '').strip()
    date_from = request.GET.get('date_from', '').strip()
    date_to = request.GET.get('date_to', '').strip()

    # 3. Base Audit Logs Queryset
    logs_qs = AutomationAuditLog.objects.all().order_by('-created_at')

    # Compute Global Statistics (Unfiltered count)
    total_count = AutomationAuditLog.objects.count()
    success_count = AutomationAuditLog.objects.filter(status__iexact='SUCCESS').count()
    running_count = AutomationAuditLog.objects.filter(status__iexact='RUNNING').count()
    failed_count = AutomationAuditLog.objects.filter(status__in=['FAILED', 'REJECTED', 'failed', 'rejected']).count()

    # Apply Search & Filter Logic
    if status_filter:
        logs_qs = logs_qs.filter(status__iexact=status_filter)

    if search_query:
        if search_query.isdigit():
            logs_qs = logs_qs.filter(
                Q(id=int(search_query)) | 
                Q(awx_job_id=int(search_query)) | 
                Q(job_name__icontains=search_query) | 
                Q(requested_by__icontains=search_query)
            )
        else:
            logs_qs = logs_qs.filter(
                Q(job_name__icontains=search_query) | 
                Q(requested_by__icontains=search_query) | 
                Q(error_message__icontains=search_query)
            )

    if date_from:
        logs_qs = logs_qs.filter(created_at__gte=date_from)
    if date_to:
        logs_qs = logs_qs.filter(created_at__lte=f"{date_to} 23:59:59")

    # 4. Paginate Audit Logs (10 items per page)
    paginator = Paginator(logs_qs, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # 5. Retrieve Active & Pending Incidents
    incidents = IncidentAlert.objects.all().order_by('-created_at')[:10]
    pending_count = IncidentAlert.objects.filter(status__in=['PENDING_APPROVAL', 'REQUIRES_APPROVAL']).count()

    context = {
        'incidents': incidents,
        'page_obj': page_obj,
        'pending_count': pending_count,
        'total_count': total_count,
        'success_count': success_count,
        'running_count': running_count,
        'failed_count': failed_count,
        'search_query': search_query,
        'status_filter': status_filter,
        'date_from': date_from,
        'date_to': date_to,
    }
    return render(request, 'dashboard/index.html', context)


def incident_dashboard(request):
    """Dedicated view for all incident alerts."""
    incidents = IncidentAlert.objects.all().order_by('-created_at')
    pending_count = IncidentAlert.objects.filter(status__in=['PENDING_APPROVAL', 'REQUIRES_APPROVAL']).count()
    return render(request, 'dashboard/incidents.html', {'incidents': incidents, 'pending_count': pending_count})


def approval_dashboard_view(request):
    """Dedicated view for pending HITL approvals."""
    pending_incidents = IncidentAlert.objects.filter(status__in=['PENDING_APPROVAL', 'REQUIRES_APPROVAL']).order_by('-created_at')
    return render(request, 'dashboard/approvals.html', {'pending_incidents': pending_incidents, 'pending_count': pending_incidents.count()})


# ==========================================
# HITL Action & Approval Endpoints
# ==========================================
def approve_action(request, alert_id):
    """Human-in-the-Loop Approval Handler."""
    alert = get_object_or_404(IncidentAlert, id=alert_id)
    payload = alert.payload if isinstance(alert.payload, dict) else {}
    agent_analysis = payload.get('agent_analysis', {})
    recommended_action = agent_analysis.get('recommended_action', {})

    tool_name = recommended_action.get('tool_name', 'awx_launch_job_template')
    tool_args = recommended_action.get('tool_args', {})

    # Trigger Celery Task to execute the approved remediation action
    execute_approved_action_task.delay(alert.id, tool_name, tool_args)
    
    alert.status = 'REMEDIATION_IN_PROGRESS'
    alert.save(update_fields=['status'])

    messages.success(request, f"Approved remediation for Incident #{alert.id}. Celery task dispatched.")
    return redirect(request.META.get('HTTP_REFERER', 'index'))


def reject_action(request, alert_id):
    """Human-in-the-Loop Rejection Handler."""
    alert = get_object_or_404(IncidentAlert, id=alert_id)
    alert.status = 'REJECTED'
    alert.save(update_fields=['status'])

    # Log rejection in Audit Log
    AutomationAuditLog.objects.create(
        job_name=f"Remediation Rejected (Alert #{alert.id})",
        requested_by=request.user.username if request.user.is_authenticated else 'SRE-Operator',
        status='REJECTED',
        error_message='Manual rejection by SRE operator.'
    )

    messages.info(request, f"Rejected action for Incident #{alert.id}.")
    return redirect(request.META.get('HTTP_REFERER', 'index'))


def approve_alert_view(request, alert_id):
    """Legacy route alias for approve_action."""
    return approve_action(request, alert_id)


def trigger_agent_analysis_view(request, alert_id):
    """API endpoint to manually trigger agent analysis for an incident."""
    process_incident_alert_task.delay(alert_id)
    return JsonResponse({"success": True, "message": f"Agent analysis queued for Alert #{alert_id}"})


def approve_agent_action_view(request, alert_id):
    """API endpoint for approving agent action via JSON."""
    return approve_action(request, alert_id)


# ==========================================
# APIs & Integrations
# ==========================================
@csrf_exempt
def ingest_alert_api(request):
    """Webhook endpoint to receive incoming incident alerts from monitoring systems."""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            alert = IncidentAlert.objects.create(
                alert_name=data.get('alert_name', 'Generic Incident Alert'),
                target_host=data.get('target_host', 'localhost'),
                severity=data.get('severity', 'HIGH'),
                summary=data.get('summary', 'No summary provided'),
                status='PENDING_APPROVAL',
                payload=data
            )
            process_incident_alert_task.delay(alert.id)
            return JsonResponse({'status': 'success', 'alert_id': alert.id}, status=201)
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
    return JsonResponse({'status': 'error', 'message': 'Invalid HTTP method'}, status=405)


def get_awx_job_logs_api(request, job_id):
    """API endpoint to poll live AWX stdout logs and job status for UI modal display."""
    client = AWXClient()
    logs = client.get_job_stdout(job_id)
    status = client.get_job_status(job_id)
    return JsonResponse({
        'success': True,
        'job_id': job_id,
        'status': status,
        'logs': logs
    })


# ==========================================
# Authentication & User Profiles
# ==========================================
def login_view(request):
    if request.method == 'POST':
        u = request.POST.get('username')
        p = request.POST.get('password')
        user = authenticate(username=u, password=p)
        if user:
            login(request, user)
            return redirect('index')
        messages.error(request, 'Invalid credentials.')
    return render(request, 'dashboard/login.html')

def signup_view(request):
    return render(request, 'dashboard/signup.html')

def verify_email_view(request):
    return render(request, 'dashboard/verify.html')

@login_required
def profile_view(request):
    return render(request, 'dashboard/profile.html')

def logout_view(request):
    logout(request)
    messages.info(request, 'Logged out successfully.')
    return redirect('login')
