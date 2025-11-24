# authent/urls.py
from django.urls import path
from .views import (
    SignupAndOpenVirtualAccount,
    VerifyEmail,
    Login,
    SetTransactionPin,
    ForgotPassword,
    ResetPassword,
    TransferFundsView,
    VerifyAccountView,
    GetAccountBalance,
    PaymentWebhookView,
    BanksListView,
)

urlpatterns = [
    path("signup/", SignupAndOpenVirtualAccount.as_view(), name="signup"),
    path("verify-email/", VerifyEmail.as_view(), name="verify_email"),
    path("login/", Login.as_view(), name="login"),
    path("set-pin/", SetTransactionPin.as_view(), name="set_pin"),
    path("forgot-password/", ForgotPassword.as_view(), name="forgot_password"),
    path("reset-password/", ResetPassword.as_view(), name="reset_password"),
    path("transfer-funds/", TransferFundsView.as_view(), name="transfer_funds"),
    path("verify-account/", VerifyAccountView.as_view(), name="verify_account"),
    path("get-balance/", GetAccountBalance.as_view(), name="get_balance"),
    path("webhook/payment/", PaymentWebhookView.as_view(), name="payment_webhook"),
    path("banks/", BanksListView.as_view(), name="banks-list"),
]
