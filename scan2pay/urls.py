from django.urls import path

from .views import (
    VendorQRCodeCreateView,
    Scan2PayCheckoutView,
    Scan2PayPaystackView,
    PaystackWebhookView,
)

urlpatterns = [

    path(
        "qr/create/",
        VendorQRCodeCreateView.as_view(),
        name="scan2pay-qr-create",
    ),

    path(
        "checkout/<int:qr_id>/",
        Scan2PayCheckoutView.as_view(),
        name="scan2pay-wallet-checkout",
    ),

    path(
        "checkout/paystack/<int:qr_id>/",
        Scan2PayPaystackView.as_view(),
        name="scan2pay-paystack-checkout",
    ),

    path(
        "paystack/webhook/",
        PaystackWebhookView.as_view(),
        name="scan2pay-paystack-webhook",
    ),
]