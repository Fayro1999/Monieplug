import uuid
import requests
from decimal import Decimal
from rest_framework import status
from django.shortcuts import render
from django.contrib.auth.hashers import check_password
from rest_framework import generics, permissions
from rest_framework.exceptions import PermissionDenied
from .models import Event, Ticket,  TicketPurchase
from .serializers import EventSerializer, TicketSerializer
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from .paygate import transfer_from_wallet
from django.core.mail import EmailMessage
from django.conf import settings
from drf_spectacular.utils import extend_schema






 #Create Event with Tickets
class EventListCreateView(generics.ListCreateAPIView):
    """
    get:
    List all events.

    Example Response:
    [
        {
            "id": 1,
            "title": "Summer Festival",
            "description": "Biggest festival of the year",
            "date": "2025-12-20T18:00:00Z",
            "location": "Lagos",
            "tickets": [...]
        }
    ]

    post:
    Create a new event with tickets (organizer only).

    Example Request:
    {
        "title": "Summer Festival",
        "description": "Biggest festival of the year",
        "date": "2025-12-20T18:00:00Z",
        "location": "Lagos",
        "tickets": [
            {"name": "VIP", "price": "5000.00"},
            {"name": "Regular", "price": "2000.00"}
        ]
    }
    """
    queryset = Event.objects.all().order_by('-created_at')
    serializer_class = EventSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def perform_create(self, serializer):
        event = serializer.save(organizer=self.request.user)
        tickets_data = self.request.data.get("tickets", [])
        for ticket_data in tickets_data:
            Ticket.objects.create(event=event, **ticket_data)



# 🔹 View, Update, Delete Event
class EventDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    get:
    Retrieve a single event.

    put/patch:
    Update an event (only organizer).

    delete:
    Delete an event (only organizer).

    Example GET Response:
    {
        "id": 1,
        "title": "Summer Festival",
        "description": "Biggest festival of the year",
        "tickets": [...]
    }
    """
    queryset = Event.objects.all()
    serializer_class = EventSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]


# 🔹 Create and List Tickets (Only by Event Organizer)
class TicketListCreateView(generics.ListCreateAPIView):
    """
    get:
    List tickets for a specific event.

    Example: /api/tickets/?event=1

    Response:
    [
        {"id": 1, "name": "VIP", "price": "5000.00"},
        {"id": 2, "name": "Regular", "price": "2000.00"}
    ]

    post:
    Create a ticket (only the event organizer can do this).

    Example Request:
    {
        "event": 1,
        "name": "Backstage Pass",
        "price": "10000.00"
    }
    """

    queryset = Ticket.objects.all()
    serializer_class = TicketSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        event_id = self.request.query_params.get('event')
        if event_id:
            return Ticket.objects.filter(event_id=event_id)
        return Ticket.objects.all()

    def perform_create(self, serializer):
        event = serializer.validated_data['event']
        if event.organizer != self.request.user:
            raise PermissionDenied("You can only create tickets for your own events.")
        serializer.save()


# 🔹 View, Update, Delete a Ticket
class TicketDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    get:
    Retrieve ticket details.

    put/patch:
    Update ticket (organizer only).

    delete:
    Delete ticket (organizer only).

    Example Response:
    {
        "id": 1,
        "name": "VIP",
        "price": "5000.00"
    }
    """

    queryset = Ticket.objects.all()
    serializer_class = TicketSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]



    
#check0ut

from decimal import Decimal
import uuid
import requests
from django.conf import settings
from django.core.mail import EmailMessage
from django.contrib.auth.hashers import check_password
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema
from .models import Ticket, TicketPurchase
from authent.models import User
from rest_framework import status
from django.core.files.storage import default_storage

# === Rova API Config ===
ROVA_API_BASE_URL = "https://baas.dev.getrova.co.uk"
PLATFORM_ACCOUNT_NUMBER = "4000005778"
PLATFORM_BANK_CODE = "000003"  # Fidelity Bank (platform)

# === Utility: Compute platform charge ===
def calculate_platform_charge(amount):
    if amount < 10000:
        return 150
    elif amount < 500000:
        return 200
    else:
        return 250

# === Utility: Transfer money via Rova API ===
def rova_transfer(destination_account, destination_bank_code, amount, narration):
    url = f"{ROVA_API_BASE_URL}/transfer"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {settings.ROVA_BAAS_TOKEN}",
    }
    payload = {
        "destinationAccount": destination_account,
        "destinationBankCode": destination_bank_code,
        "amount": f"{Decimal(amount):.2f}",
        "clientReference": str(uuid.uuid4()),
        "narration": narration[:20],
    }
    response = requests.post(url, json=payload, headers=headers, timeout=30)
    try:
        return response.json()
    except ValueError:
        return {"status": "ERROR", "message": response.text}


# === Checkout View ===
@extend_schema(exclude=True)
class EwalletCheckoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        data = request.data
        ticket_id = data.get("ticket_id")
        copies = int(data.get("copies", 1))
        full_name = data.get("full_name")
        email = data.get("email")
        transaction_pin = data.get("transaction_pin")

        user = request.user

        # Step 1 — Validate transaction PIN
        if not user.transaction_pin:
            return Response(
                {"error": "Transaction PIN not set. Please create one first."},
                status=status.HTTP_403_FORBIDDEN,
            )
        if not check_password(transaction_pin, user.transaction_pin):
            return Response(
                {"error": "Invalid transaction PIN"},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Step 2 — Validate ticket
        try:
            ticket = Ticket.objects.get(id=ticket_id)
        except Ticket.DoesNotExist:
            return Response({"error": "Invalid ticket"}, status=status.HTTP_404_NOT_FOUND)

        # Step 3 — Get vendor (event organizer)
        vendor = ticket.event.organizer
        if not vendor.virtual_account_number:
            return Response({"error": "Vendor does not have a virtual account"}, status=400)

        # Step 4 — Compute total & charges
        total_amount = Decimal(ticket.price) * copies
        platform_charge = calculate_platform_charge(total_amount)
        vendor_amount = total_amount - Decimal(platform_charge)

        # Step 5 — Transfer from buyer → platform
        narration = f"Ticket-{ticket.event.title}"[:20]
        buyer_transfer = rova_transfer(
            destination_account=PLATFORM_ACCOUNT_NUMBER,
            destination_bank_code=PLATFORM_BANK_CODE,
            amount=total_amount,
            narration=narration,
        )
        if buyer_transfer.get("status") != "SUCCESS" or buyer_transfer["data"].get("status") != "SUCCESSFUL":
            return Response(
                {"error": "Failed to debit buyer account", "details": buyer_transfer},
                status=400,
            )

        # Step 6 — Transfer from platform → vendor (FCMB Rova code)
        payout_narration = f"Payout-{ticket.event.title}"[:20]
        vendor_transfer = rova_transfer(
            destination_account=vendor.virtual_account_number,
            destination_bank_code="214001",  # FCMB Rova fixed
            amount=vendor_amount,
            narration=payout_narration,
        )
        if vendor_transfer.get("status") != "SUCCESS" or vendor_transfer["data"].get("status") != "SUCCESSFUL":
            return Response(
                {"error": "Vendor payout failed", "details": vendor_transfer},
                status=400,
            )

        # Step 7 — Save purchase record
        purchase = TicketPurchase.objects.create(
            ticket=ticket,
            full_name=full_name,
            email=email,
            copies=copies,
            total_price=total_amount,
            user=user,
        )

        # Step 8 — Send receipt with all QR codes
        email_subject = f"Your Ticket Receipt - {ticket.event.title}"
        email_body = f"""
Hello {full_name},

✅ Payment Successful!

Event: {ticket.event.title}
Tickets: {copies}
Total Paid: ₦{total_amount}
Platform Charge: ₦{platform_charge}
Vendor Receives: ₦{vendor_amount}

Reference ID: {purchase.reference_id}

Thank you for your purchase!
"""
        email_msg = EmailMessage(
            subject=email_subject,
            body=email_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[email],
        )

        # Attach all QR codes
        for qr_file in purchase.qr_codes:
            file_path = f'qrcodes/{qr_file}'
            if default_storage.exists(file_path):
                with default_storage.open(file_path, 'rb') as f:
                    email_msg.attach(qr_file, f.read(), 'image/png')

        email_msg.send(fail_silently=True)

        return Response(
            {
                "message": "Purchase completed successfully",
                "ticket_code": str(purchase.reference_id),
                "platform_charge": float(platform_charge),
                "vendor_amount": float(vendor_amount),
                "transfer_to_vendor": vendor_transfer,
            },
            status=200,
        )
