from django.urls import path
from .views import (
    EventListCreateView, EventDetailView,
    TicketListCreateView, TicketDetailView,
    EwalletCheckoutView,GuestPaystackCheckoutView,#PaystackVerifyAndPayoutView,PaystackBanksView,paystack_webhook
)

urlpatterns = [
    path('events/', EventListCreateView.as_view(), name='events-list-create'),
    path('events/<int:pk>/', EventDetailView.as_view(), name='event-detail'),
    path('tickets/', TicketListCreateView.as_view(), name='tickets-list-create'),
    path('tickets/<int:pk>/', TicketDetailView.as_view(), name='ticket-detail'),
    path('ewallet/checkout/', EwalletCheckoutView.as_view(), name='ewallet-checkout'),
    path("guest/paystack/checkout/",GuestPaystackCheckoutView.as_view(),name="guest-paystack-checkout",),

    #path('ewallet/verify/', PaystackVerifyAndPayoutView.as_view(), name='ewallet-verify'),
    #path("paystack/banks/", PaystackBanksView.as_view(), name="paystack-banks"),
    #path("paystack/webhook/", paystack_webhook, name="paystack-webhook"),

]

