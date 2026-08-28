from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    # Built-in Django Admin interface
    path('admin/', admin.site.urls),
    
    # Delegates any URLs starting with /dashboard/ to your custom app
    path('dashboard/', include('dashboard.urls')),
    path('', include('dashboard.urls')),
    
]