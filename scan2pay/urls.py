from django.urls import path
from .views import VendorQRCodeCreateView, Scan2PayCheckoutView, Scan2PayUnregisteredView

urlpatterns = [
    path("vendor/qrcode/create/", VendorQRCodeCreateView.as_view(), name="vendor_qrcode_create"),
    path("checkout/", Scan2PayCheckoutView.as_view(), name="scan2pay_checkout"),
    path("unregistered/", Scan2PayUnregisteredView.as_view(), name="scan2pay_unregistered"),
]
