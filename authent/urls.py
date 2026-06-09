# authent/urls.py
from django.urls import path
from .views import (
    SignupAndOpenWallet,
    VerifyEmail,
    Login,
    SetTransactionPin,
    ForgotPassword,
    ResetPassword,
    TransferFundsView,
    VerifyAccountView,
    WalletEnquiryView,
    PaymentWebhookView,
    WAASBanksView,
    GetUsersView,
    GetSingleUserView,
    WalletTransactionHistoryView,
    OtherBankAccountEnquiryView,
    CheckTransactionPin,
)

urlpatterns = [
    path("signup/", SignupAndOpenWallet.as_view(), name="signup"),
    path("verify-email/", VerifyEmail.as_view(), name="verify_email"),
    path("login/", Login.as_view(), name="login"),
    path("set-pin/", SetTransactionPin.as_view(), name="set_pin"),
    path("forgot-password/", ForgotPassword.as_view(), name="forgot_password"),
    path("reset-password/", ResetPassword.as_view(), name="reset_password"),
    path("transfer-funds/", TransferFundsView.as_view(), name="transfer_funds"),
    path("verify-account/", VerifyAccountView.as_view(), name="verify_account"),
    path("get-balance/", WalletEnquiryView.as_view(), name="get_balance"),
    path("webhook/payment/", PaymentWebhookView.as_view(), name="payment_webhook"),
    path("banks/", WAASBanksView.as_view(), name="banks-list"),
    path("users/", GetUsersView.as_view(), name="get-users"),
    path("users/<uuid:id>/",GetSingleUserView.as_view(), name="get-user"),
    path("transaction-history/",WalletTransactionHistoryView.as_view(), name="transaction-history"),
    path("other-bank-enquiry/",OtherBankAccountEnquiryView.as_view(), name="other-bank-enquiry"),
    path("check-transaction-pin/",CheckTransactionPin.as_view(), name="CheckTransactionPin"),
]
