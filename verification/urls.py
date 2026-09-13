from django.urls import path

from .views import (
    StartVerificationView,
    VerificationStatusView,
)

urlpatterns = [

    path(
        "start/",
        StartVerificationView.as_view(),
        name="start-verification",
    ),

    path(
        "status/",
        VerificationStatusView.as_view(),
        name="verification-status",
    ),

]