# Agentic SRE Platform - Source Code Documentation

## Repository: nitiya1919/agentic-sre-platform
**Language Composition:** Python (98.7%), HTML (0.5%), JavaScript (0.4%), CSS (0.3%), C (0.1%)

---

## 📁 Directory Structure

```
src/
└── sre_platform/          # Django Project Root
    ├── manage.py          # Django management utility
    ├── sre_platform/      # Main Django configuration
    │   ├── __init__.py
    │   ├── settings.py    # Django settings (DB, Celery, AWX config)
    │   ├── urls.py        # URL routing configuration
    │   ├── celery.py      # Celery task queue config
    │   └── wsgi.py        # WSGI application entry point
    └── dashboard/         # Main Django app for incident management
        ├── models.py      # Database models
        ├── views.py       # View handlers & API endpoints
        ├── tasks.py       # Celery async tasks
        ├── urls.py        # Dashboard URL routes
        ├── apps.py        # App configuration
        ├── services/      # Service layer
        │   ├── awx.py         # AWX REST API client
        │   ├── awx_client.py  # Alternative AWX client
        │   └── awx - Copy.py  # Backup/copy of awx.py
        └── agent/         # Agentic SRE components
            ├── agent_runner.py    # Multi-turn ReAct agent loop (Gemini)
            ├── awx_tools.py       # AWX tool integrations for agent
            └── reasoning.py       # SRE evaluation & planning logic
```

---

## 🔑 Core Components

### 1. **Models (dashboard/models.py)**
Defines three primary database models:

#### `AuditOutbox`
- Tracks all automation events and state machine transitions
- Fields: `trace_id`, `alert_hash`, `event_type`, `status`, `payload`
- Event Statuses: `PENDING`, `PROCESSING`, `RUNNING`, `SUCCESSFUL`, `FAILED`, `REJECTED`, `CANCELED`
- Uses OpenTelemetry Trace IDs for distributed tracing
- Indexed on: trace_id + created_at, processed + created_at, alert_hash + created_at

#### `IncidentAlert`
- Represents incoming monitoring alerts (e.g., Prometheus, Grafana)
- Fields: `alert_name`, `severity`, `target_host`, `summary`, `payload`, `status`
- Statuses: `PENDING`, `PROCESSING`, `RESOLVED`, `FAILED`, `REQUIRES_APPROVAL`
- Auto-ordered by creation timestamp (newest first)

#### `AutomationAuditLog`
- Records all automation playbook executions
- Tracks requested remediation actions via AWX
- Fields: `job_name`, `requested_by`, `status`, `error_message`, `awx_job_id`
- Supports status tracking: PENDING, SUCCESS, RUNNING, FAILED, REJECTED

---

### 2. **Views & API Endpoints (dashboard/views.py)**

#### Main Dashboard
**`index(request)`**
- SRE Command Center dashboard with comprehensive statistics
- Features:
  - Bulk action handling (delete selected audit logs)
  - Advanced filtering: search query, status, date range
  - Pagination (10 items per page)
  - Global stats: total, success, running, failed counts
  - Displays latest 10 incidents
- Returns: Rendered template with context data

**`incident_dashboard(request)`**
- Dedicated incident alert listing view
- Shows all incidents ordered by creation date (newest first)
- Displays pending approval count

**`approval_dashboard_view(request)`**
- HITL (Human-in-the-Loop) approval queue
- Filters incidents with status: PENDING_APPROVAL or REQUIRES_APPROVAL

#### AWX Integration
**`AWXClient` class**
- REST API wrapper for AWX/Ansible Automation Platform
- Constructor: Reads AWX_HOST, AWX_USERNAME, AWX_PASSWORD from settings
- Methods:
  - `launch_job_template(template_id, extra_vars=None)` - Trigger playbook execution
  - `get_job_stdout(job_id)` - Fetch playbook execution logs (removes ANSI escape sequences)
  - `get_job_status(job_id)` - Poll job execution status

#### HITL Approval Handlers
**`approve_action(request, alert_id)`**
- Human operator approves high-risk remediation
- Updates alert status to REMEDIATION_IN_PROGRESS
- Dispatches Celery task: `execute_approved_action_task`

**`reject_action(request, alert_id)`**
- Human operator rejects recommended action
- Updates alert status to REJECTED
- Creates rejection audit log entry

**`trigger_agent_analysis_view(request, alert_id)`**
- Manual agent analysis trigger (API endpoint)
- Queues `process_incident_alert_task` via Celery

#### API Endpoints
**`ingest_alert_api(request)` - @csrf_exempt**
- Webhook receiver for incoming monitoring alerts
- Method: POST
- Input: JSON with alert_name, target_host, severity, summary
- Returns: JSON with alert_id and status
- Status codes: 201 (created), 400 (error), 405 (invalid method)
- Automatically queues agent analysis task

**`get_awx_job_logs_api(request, job_id)`**
- Retrieve live AWX job logs for UI modal display
- Returns: Job ID, status, and formatted stdout logs
- Used for real-time execution monitoring

#### Authentication
- `login_view(request)` - Django authenticate + login redirect
- `signup_view(request)` - Registration form
- `verify_email_view(request)` - Email verification
- `profile_view(request)` - User profile (login_required)
- `logout_view(request)` - Session cleanup + logout redirect

---

### 3. **Async Tasks (dashboard/tasks.py)**

#### `process_incident_alert_task(self, alert_id)`
**Purpose:** Agentic triage and risk scoring

- Decorator: `@shared_task(bind=True, max_retries=3)`
- Workflow:
  1. Retrieves IncidentAlert from database
  2. Analyzes alert text using pattern matching
  3. Maps alert keywords to remediation strategies
  4. Performs risk assessment (LOW/HIGH)
  5. Routes to either auto-execution or HITL approval queue
  
**Risk Assessment Logic:**
- CPU/Load alerts → Low risk (service restart)
- Disk/Storage alerts → Low risk (cleanup tmp files)
- Other → High risk (node failover)

**Tool Selection:**
- Maps to AWX job templates (template_id 1, 2, or 3)
- Includes extra_vars with target_host and action parameters
- Stores payload for audit trail

#### `execute_approved_action_task(self, alert_id, tool_name, tool_args)`
**Purpose:** Execute approved remediation via AWX

- Decorator: `@shared_task(bind=True, max_retries=2)`
- Workflow:
  1. Retrieves approved alert from database
  2. Instantiates AWXTaskClient
  3. Launches job template with extra variables
  4. Creates AutomationAuditLog entry
  5. Updates alert status to COMPLETED/FAILED
  
**Error Handling:**
- Catches exceptions and retries with 15-second countdown
- Logs detailed error messages for investigation

**Technologies:**
- **Celery** for async task queue
- **Redis** as message broker (AWS ElastiCache)
- **PostgreSQL** for result backend
- **Broker URL:** `redis://localhost:6379/0` (configurable via env)

---

### 4. **Agent Components (dashboard/agent/)**

#### `agent_runner.py` - Autonomous SRE Agent (Gemini)
**Purpose:** Multi-turn reasoning agent for incident resolution

**Architecture:**
- **Model:** Google Gemini 3.6 Flash (configurable)
- **Pattern:** ReAct (Reasoning + Acting) loop
- **Max Turns:** 5 (configurable)
- **System Instruction:** Instructs agent to diagnose alerts, inspect logs, propose playbook execution

**Key Class: `SREAgentRunner`**
- Constructor: `__init__(model_name="gemini-3.6-flash")`
- Main Method: `run_agent_loop(incident_context, max_turns=5) -> Dict[str, Any]`

**Tool Integration:**
- Registers AWX tools via `AWX_TOOLSET`
- Validates tool risk before execution
- Available Tools:
  - `awx_list_job_templates` (read-only)
  - `awx_launch_job_template` (mutation - HIGH RISK)
  - `awx_get_job_status` (read-only)
  - `awx_get_job_stdout` (read-only)

**HITL Risk Gate:**
- `evaluate_tool_risk(function_name, function_args)` - Risk assessment engine
- Low-risk tools (read-only) → Execute automatically
- High-risk mutations (`awx_launch_job_template`) → Return `PENDING_APPROVAL` status
- Includes full reasoning context for operator review
- Returns: agent_thoughts[], pending_action{}, final_response

**Agent States:**
- `PENDING_APPROVAL` - High-risk action intercepted, awaiting human sign-off
- `COMPLETED` - Agent successfully resolved incident
- `MAX_TURNS_EXCEEDED` - Agent reached iteration limit

#### `awx_tools.py` - Agentic Tool Implementations
Provides 4 callable tools for the agent (JSON-serializable):

**1. `awx_list_job_templates(search_name=None) -> str`**
   - Lists available Ansible playbooks in AWX
   - Optional search by name substring
   - Returns: JSON with ID, name, description, job_type for each template
   - HTTP GET to `/api/v2/job_templates/`

**2. `awx_launch_job_template(job_template_id, extra_vars=None) -> str`**
   - Triggers playbook execution with parameters
   - Parameters: target_host, action, and custom variables
   - Returns: JSON with job_id, template_name, execution_status
   - HTTP POST to `/api/v2/job_templates/{id}/launch/`
   - HIGH RISK tool - requires HITL approval

**3. `awx_get_job_status(job_id) -> str`**
   - Polls current execution status and metrics
   - Returns: status, failed flag, elapsed_seconds, started, finished timestamps
   - HTTP GET to `/api/v2/jobs/{id}/`

**4. `awx_get_job_stdout(job_id) -> str`**
   - Fetches Ansible playbook logs for error diagnosis
   - Truncates output >4000 chars for context efficiency
   - Returns: JSON with stdout content (truncated if needed)
   - HTTP GET to `/api/v2/jobs/{id}/stdout/?format=txt`

**Configuration:**
- AWX_HOST: `os.getenv("AWX_BASE_URL", "http://localhost:8013")`
- AWX_TOKEN: Bearer token authentication
- AWX_VERIFY_SSL: SSL verification flag (default: False)

#### `reasoning.py` - Deterministic SRE Evaluator
**Purpose:** Fallback rule-based incident evaluation (non-AI)

**Key Class: `SREAgentEvaluator`**
- Constructor: `__init__(incident_alert)`
- Main Method: `evaluate_and_plan() -> action_plan`

**Methods:**
- `_generate_strategy()` - Maps alert types to remediation templates
  - Memory/HighMemory alerts → Low risk (restart app services)
  - Unknown alerts → High risk (manual investigation)
- `_execute_remediation(plan)` - Launches AWX templates
  - Returns: (success: bool, awx_job_id: int|None)

**Auto-Execution Logic:**
- Low-risk plans execute automatically
- High-risk plans route to HITL approval
- All executions logged to AutomationAuditLog

---

### 5. **Configuration (sre_platform/)**

#### `settings.py`
**Debug & Security:**
- `DEBUG = 'True'` ⚠️ **Security Warning**: Should be `False` in production
- `SECRET_KEY`: Fallback dev key, use environment variable in production
- `ALLOWED_HOSTS = ['*']` ⚠️ **Security Warning**: Overly permissive
- `SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')` - AWS ALB support

**Database Configuration:**
- Engine: PostgreSQL (Django backend)
- Connection pooling: Configurable via env vars
- Env vars: DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT
- Default: localhost:5432 (dev)

**Message Broker (Celery):**
- Broker URL: Redis (AWS ElastiCache)
- Result Backend: Same as broker
- Serializer: JSON (for compatibility)
- Env var: CELERY_BROKER_URL

**AWX Integration:**
- `AWX_HOST`: Base URL for AWX API
- `AWX_TOKEN`: Personal access token (PAT)
- `AWX_VERIFY_SSL`: SSL certificate verification (default: False)
- `AWX_DISK_CLEANUP_TEMPLATE_ID`: Specific template ID for disk cleanup

**Installed Apps:**
- django.contrib.* (standard)
- dashboard (custom app)

**Middleware Stack:**
- Security, Sessions, CSRF, Auth, Messages, XFrame

**Static Files:**
- STATIC_URL: `/static/`
- STATIC_ROOT: `{BASE_DIR}/static`

**Templates:**
- Template loader from `{BASE_DIR}/templates`
- Context processors for debug, request, auth, messages

#### `urls.py`
**URL Routing:**
- `/admin/` → Django admin interface
- `/dashboard/` → Include dashboard.urls
- `/` → Include dashboard.urls (root)

#### `celery.py`
- Configures Celery client
- Sets up Redis broker
- JSON serialization for tasks

#### `wsgi.py`
- Standard Django WSGI application entry point
- Used by production servers (Gunicorn, uWSGI, etc.)

---

### 6. **Service Layer (dashboard/services/)**

#### `awx.py` - Feature-Rich AWX Client
**Class: `AWXClient`**

**Constructor:**
- Reads AWX_HOST, AWX_USERNAME, AWX_PASSWORD from Django settings
- Defaults: localhost:8013, admin, password

**Methods:**
- `launch_job_template(template_id, extra_vars=None)`
  - Supports both Bearer token and basic auth
  - Returns: {"success": bool, "job_id": int, "response": dict} | {"success": False, "error": str}
  - Handles timeout (10s) and HTTP error codes
  - Comprehensive logging for debugging

**Features:**
- Bearer token support (if token available)
- Fallback to basic auth
- SSL verification configurable
- ANSI escape sequence stripping for clean logs
- Comprehensive error logging

#### `awx_client.py` - Minimal AWX Client
**Class: `AWXClient` (lightweight version)**

**Constructor:**
- Uses environment variables: AWX_BASE_URL, AWX_TOKEN

**Methods:**
- `launch_job_template(template_id, extra_vars=None)`
  - Simple wrapper with Bearer token auth
  - Returns: Raw JSON response from AWX API

**Use Case:** Simpler alternative for basic operations

---

## 🔄 Incident Flow Diagram

```
Monitoring System (Prometheus/Grafana/AlertManager)
       ↓
[ingest_alert_api] → IncidentAlert (DB) + Celery Task
       ↓
[process_incident_alert_task] (Celery Worker)
       ↓
    ┌──────────────────────────────┐
    │ Agentic Risk Assessment      │
    │ (Pattern matching + AI)       │
    └──────────────────────────────┘
          ↙                    ↖
    LOW RISK              HIGH RISK
         ↓                      ↓
  AUTO-EXECUTE          HITL APPROVAL DASHBOARD
         ↓                      ↓
  [execute_approved]     [approve_action]
         ↓                      ↓
    AWX Job Template Launch
         ↓
    Ansible Playbook Execution
         ↓
    [AutomationAuditLog] + [AuditOutbox]
         ↓
    Dashboard Stats Updated
```

---

## 🛡️ Human-in-the-Loop (HITL) Gates

### Gate 1: Agent Risk Evaluation
- **Location:** `agent_runner.py:evaluate_tool_risk()`
- **Trigger:** Agent requests `awx_launch_job_template` tool
- **Action:** Intercepts high-risk mutations
- **Outcome:** Returns PENDING_APPROVAL with reasoning context

### Gate 2: Manual Approval
- **Location:** `views.approve_action()` / `approval_dashboard_view()`
- **Trigger:** SRE operator reviews pending incidents
- **Action:** Human approval/rejection of remediation
- **Outcome:** Executes or rejects based on operator decision

### Gate 3: Audit Trail
- **Location:** `AuditOutbox` + `AutomationAuditLog` models
- **Purpose:** Complete traceability via OpenTelemetry Trace IDs
- **Data Captured:**
  - Alert payload
  - Agent analysis & risk assessment
  - Operator decision & timestamp
  - Execution results

---

## 🚀 Key Deployment Architecture

```
┌─────────────────────────────────────────────────────────┐
│                  AWS Infrastructure                      │
├─────────────────────────────────────────────────────────┤
│                                                           │
│  ┌──────────────────┐          ┌────────────────────┐   │
│  │   AWS ALB        │          │  Django App        │   │
│  │  (Load Balancer) │────────→ │  (Gunicorn/uWSGI)  │   │
│  └──────────────────┘          └────────────────────┘   │
│                                       ↓                  │
│                        ┌──────────────┴──────────────┐  │
│                        ↓                             ↓   │
│                  ┌──────────┐              ┌──────────┐  │
│                  │ Celery   │              │   Django │  │
│                  │ Workers  │              │   Admin  │  │
│                  └──────────┘              └──────────┘  │
│                        ↓                        ↓        │
│            ┌───────────┴───────────┐            │       │
│            ↓                       ↓            ↓       │
│      ┌──────────┐            ┌──────────┐ ┌────────┐  │
│      │  Redis   │            │PostgreSQL│ │ AWX/   │  │
│      │ElastiCache│           │   RDS    │ │Ansible │  │
│      └──────────┘            └──────────┘ └────────┘  │
│                                                         │
└─────────────────────────────────────────────────────────┘

External Services:
- Google Gemini 3.6 Flash (API)
- Monitoring Systems (Prometheus, Grafana, AlertManager)
```

**Components:**
- **Frontend:** Django templates + static assets (CSS, JS)
- **Backend:** Django REST API + Views
- **Async:** Celery task workers
- **Database:** AWS RDS PostgreSQL
- **Message Queue:** AWS ElastiCache Redis
- **Load Balancer:** AWS ALB (X-Forwarded-Proto header support)
- **Automation Engine:** External AWX/Ansible Automation Platform
- **AI Agent:** Google Gemini 3.6 Flash (LLM)
- **Monitoring:** Webhook receivers for Prometheus/AlertManager

---

## ⚠️ Security Notes & TODOs

### High Priority
- [ ] Disable DEBUG mode in production (`DEBUG = False`)
- [ ] Restrict ALLOWED_HOSTS to specific domains
- [ ] Use environment variables for all sensitive config
- [ ] Implement rate limiting on webhook endpoints
- [ ] Add API authentication (API keys/tokens for ingest_alert_api)
- [ ] Enable Django CSRF protection on all POST endpoints
- [ ] Validate and sanitize all user inputs

### Medium Priority
- [ ] Implement request logging for audit trail
- [ ] Add distributed request tracing (OpenTelemetry)
- [ ] Use Django Signals for better event handling
- [ ] Implement request/response caching for AWX calls
- [ ] Add monitoring/alerting for Celery task failures
- [ ] Implement circuit breaker pattern for AWX API calls

### Recommendations
- Use secrets management (AWS Secrets Manager, HashiCorp Vault)
- Enable SSL/TLS for all external communications
- Implement API versioning for future changes
- Add comprehensive unit & integration tests
- Set up CI/CD pipeline with automated tests
- Document runbooks for common failure scenarios

---

## 📦 Dependencies

### Core Framework
- Django (web framework)
- djangorestframework (if upgrading to REST)

### Async & Task Queue
- Celery (async task queue)
- redis (message broker)

### Database
- psycopg2 (PostgreSQL adapter)

### Integration
- requests (HTTP client for AWX)
- google-genai (Gemini AI integration)

### Optional
- boto3 (AWS SDK for services)
- gunicorn (production WSGI server)
- prometheus-client (metrics export)

---

## 🔍 Key Features Summary

| Feature | Status | Location |
|---------|--------|----------|
| Dashboard UI | ✅ | views.py, templates/ |
| Alert Ingestion | ✅ | ingest_alert_api() |
| Agentic Triage | ✅ | agent_runner.py |
| Risk Assessment | ✅ | reasoning.py |
| HITL Approval | ✅ | approve_action() |
| AWX Integration | ✅ | services/awx.py |
| Audit Logging | ✅ | AuditOutbox model |
| Real-time Logs | ✅ | get_awx_job_logs_api() |
| Multi-turn Agent | ✅ | agent_runner.py (Gemini) |

---

## 📝 Usage Examples

### 1. Ingest Alert via Webhook
```bash
curl -X POST http://localhost:8000/dashboard/api/alerts/ingest/ \
  -H "Content-Type: application/json" \
  -d '{
    "alert_name": "HighCPUUsage",
    "target_host": "web-server-01",
    "severity": "HIGH",
    "summary": "CPU usage exceeded 80% threshold"
  }'
```

### 2. Manual Agent Analysis Trigger
```bash
curl http://localhost:8000/dashboard/api/alert/1/analyze/
```

### 3. Approve Incident Remediation
```bash
curl -X POST http://localhost:8000/dashboard/alert/1/approve/
```

### 4. Get AWX Job Logs
```bash
curl http://localhost:8000/dashboard/api/awx/logs/42/
```

---

## 🎯 Next Steps / Roadmap

- [ ] Add Prometheus metrics export for monitoring
- [ ] Implement Slack/PagerDuty integration
- [ ] Add comprehensive test coverage (unit, integration)
- [ ] Create API documentation (OpenAPI/Swagger)
- [ ] Implement role-based access control (RBAC)
- [ ] Add incident trend analysis & forecasting
- [ ] Integrate with additional monitoring systems
- [ ] Create mobile app for HITL approvals
- [ ] Implement advanced filtering & search UI

---

**Last Updated:** 2026-08-29  
**Repository:** https://github.com/nitiya1919/agentic-sre-platform  
**Primary Language:** Python (98.7%)  
**Framework:** Django + Celery  
**AI Model:** Google Gemini 3.6 Flash
