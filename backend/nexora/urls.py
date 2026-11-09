from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path

from core import views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", views.home),
    path("login/", views.login_view),
    path("signup/", views.signup_view),
    path("signup/verify/", views.signup_verify_view),
    path("reset/", views.reset_request_view),
    path("reset/verify/", views.reset_verify_view),
    path("logout/", views.logout_view),
    path("dashboard/client/", views.client_dashboard),
    path("dashboard/admin/", views.admin_dashboard),
    path("api/dashboard/", views.api_dashboard),
    path("api/wa/status/", views.wa_status),
    path("api/wa/connect/", views.wa_connect),
    path("api/webhook/wa/", views.wa_webhook),
    path("api/order/<int:order_id>/", views.order_detail),
    path("api/order/<int:order_id>/action/", views.order_action),
    path("api/product/save/", views.product_save),
    path("api/product/upload/", views.product_upload),
    path("api/product/archive/", views.product_archive),
    path("api/product/duplicate/", views.product_duplicate),
    path("api/product/stock/", views.product_stock),
    path("api/conversation/<int:conv_id>/resolve/", views.conversation_resolve),
    path("api/tenant/settings/", views.tenant_settings),
    path("api/tenant/couriers/", views.tenant_couriers),
    path("api/courier/test/", views.courier_test),
    path("api/account/update/", views.account_update),
    path("api/admin/config/", views.admin_config),
    path("api/admin/models/", views.admin_models),
    path("api/admin/test-llm/", views.admin_test_llm),
    path("api/admin/plan/", views.admin_plan),
    path("api/admin/tenant/", views.admin_tenant_create),
    path("api/admin/tenant/<int:tenant_id>/", views.admin_tenant_detail),
    path("api/admin/tenant/<int:tenant_id>/delete/", views.admin_tenant_delete),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATICFILES_DIRS[0])
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
