from django.urls import path
from dashboard import views

urlpatterns = [
    # --- Main Dashboard & Logs UI ---
    path('', views.index, name='index'),
    path('dashboard/', views.index, name='dashboard_index'),
    path('incidents/', views.incident_dashboard, name='incident_dashboard'),
    path('approvals/', views.approval_dashboard_view, name='approval_dashboard'),

    # --- HITL Action Endpoints ---
    path('alert/<int:alert_id>/approve/', views.approve_action, name='approve_action'),
    path('alert/<int:alert_id>/reject/', views.reject_action, name='reject_action'),
    path('alert/<int:alert_id>/approve-legacy/', views.approve_alert_view, name='approve_alert_legacy'),
    path('api/alert/<int:alert_id>/analyze/', views.trigger_agent_analysis_view, name='trigger_agent_analysis'),
    path('api/alert/<int:alert_id>/agent-action/', views.approve_agent_action_view, name='approve_agent_action'),

    # --- API & Integration Endpoints ---
    path('api/alerts/ingest/', views.ingest_alert_api, name='ingest_alert_api'),
    path('api/awx/logs/<int:job_id>/', views.get_awx_job_logs_api, name='awx_job_logs_api'),

    # --- Authentication & User Profile ---
    path('login/', views.login_view, name='login'),
    path('signup/', views.signup_view, name='signup'),
    path('verify/', views.verify_email_view, name='verify_email'),
    path('profile/', views.profile_view, name='profile'),
    path('logout/', views.logout_view, name='logout'),
]
