from django.urls import path
from .views import (
    VendorQRCodeCreateView,
    Scan2PayCheckoutView,
    Scan2PayUnregisteredView
)

urlpatterns = [
    path(
        "vendor/qrcode/create/",
        VendorQRCodeCreateView.as_view(),
        name="vendor_qrcode_create"
    ),

    # ✅ FIXED: QR must pass ID
    path(
        "checkout/<int:qr_id>/",
        Scan2PayCheckoutView.as_view(),
        name="scan2pay_checkout"
    ),

    path(
        "unregistered/",
        Scan2PayUnregisteredView.as_view(),
        name="scan2pay_unregistered"
    ),
]