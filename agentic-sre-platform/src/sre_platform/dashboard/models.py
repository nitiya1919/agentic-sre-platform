from django.db import models

import uuid
from django.db import models


class AuditOutbox(models.Model):
    class EventStatus(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        PROCESSING = 'PROCESSING', 'Processing'
        RUNNING = 'RUNNING', 'Running'
        SUCCESSFUL = 'SUCCESSFUL', 'Successful'
        FAILED = 'FAILED', 'Failed'
        REJECTED = 'REJECTED', 'Rejected'
        CANCELED = 'CANCELED', 'Canceled'

    id = models.UUIDField(
        primary_key=True, 
        default=uuid.uuid4, 
        editable=False,
        help_text="Unique identifier for the audit record."
    )
    trace_id = models.CharField(
        max_length=64, 
        db_index=True, 
        help_text="OpenTelemetry Trace ID for distributed tracking across systems."
    )
    alert_hash = models.CharField(
        max_length=64, 
        db_index=True, 
        help_text="SHA256 fingerprint (alertname + instance) for incident isolation."
    )
    event_type = models.CharField(
        max_length=50, 
        help_text="State machine event type (e.g., INSTRUCTION_RECEIVED, AWX_DISPATCHED, AWX_COMPLETED)."
    )
    status = models.CharField(
        max_length=20, 
        choices=EventStatus.choices, 
        default=EventStatus.PENDING
    )
    payload = models.JSONField(
        default=dict, 
        blank=True, 
        help_text="Full execution payload including extra_vars, AWX job metadata, or error tracebacks."
    )
    created_at = models.DateTimeField(
        auto_now_add=True, 
        db_index=True
    )
    processed = models.BooleanField(
        default=False, 
        db_index=True, 
        help_text="Flag indicating whether an outbox flusher/worker has processed this record."
    )

    class Meta:
        db_table = 'audit_outbox'
        verbose_name = 'Audit Outbox Event'
        verbose_name_plural = 'Audit Outbox Events'
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['trace_id', 'created_at'], name='idx_audit_trace_created'),
            models.Index(fields=['processed', 'created_at'], name='idx_audit_processed_created'),
            models.Index(fields=['alert_hash', 'created_at'], name='idx_audit_hash_created'),
        ]

    def __str__(self):
        return f"[{self.created_at.strftime('%Y-%m-%d %H:%M:%S')}] {self.event_type} | Status: {self.status} | Trace: {self.trace_id[:8]}"
        
class IncidentAlert(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending Agent Evaluation'),
        ('PROCESSING', 'Processing by Agent'),
        ('RESOLVED', 'Resolved'),
        ('FAILED', 'Remediation Failed'),
        ('REQUIRES_APPROVAL', 'Requires Human Approval'),
    ]

    alert_name = models.CharField(max_length=255)
    severity = models.CharField(max_length=50, default='warning')
    target_host = models.CharField(max_length=255, blank=True, null=True)
    summary = models.TextField(blank=True, null=True)
    payload = models.JSONField(help_text="Full raw JSON webhook payload")
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='PENDING')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
  
    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.severity.upper()}] {self.alert_name} - {self.target_host} ({self.status})"
        
        
class AutomationAuditLog(models.Model):
    job_name = models.CharField(max_length=255)
    requested_by = models.CharField(max_length=255)
    status = models.CharField(max_length=50, default="PENDING")
    error_message = models.TextField(blank=True, null=True)
    awx_job_id = models.IntegerField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"AWX Job {self.awx_job_id} - {self.status}"