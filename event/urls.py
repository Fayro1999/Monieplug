from django.urls import path
from .views import (
    EventListCreateView, EventDetailView,
    TicketListCreateView, TicketDetailView,
    EwalletCheckoutView
)

urlpatterns = [
    path('events/', EventListCreateView.as_view(), name='events-list-create'),
    path('events/<int:pk>/', EventDetailView.as_view(), name='event-detail'),
    path('tickets/', TicketListCreateView.as_view(), name='tickets-list-create'),
    path('tickets/<int:pk>/', TicketDetailView.as_view(), name='ticket-detail'),
    path('ewallet/checkout/', EwalletCheckoutView.as_view(), name='ewallet-checkout'),
]

