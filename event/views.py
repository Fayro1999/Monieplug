from django.shortcuts import render
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




 #Create Event with Tickets
class EventListCreateView(generics.ListCreateAPIView):
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
    queryset = Event.objects.all()
    serializer_class = EventSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]


# 🔹 Create and List Tickets (Only by Event Organizer)
class TicketListCreateView(generics.ListCreateAPIView):
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
    queryset = Ticket.objects.all()
    serializer_class = TicketSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]



    

class EwalletCheckoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        data = request.data
        ticket_id = data.get("ticket_id")
        copies = int(data.get("copies", 1))  # how many copies user wants
        acct_number = data.get("account_number")
        full_name = data.get("full_name")
        email = data.get("email")
        phone = data.get("phone")

        try:
            ticket = Ticket.objects.get(id=ticket_id)
        except Ticket.DoesNotExist:
            return Response({"error": "Invalid ticket"}, status=404)

        total_kobo = int(ticket.price * copies * 100)

        user_data = {
            "first_name": full_name.split()[0],
            "last_name": full_name.split()[-1],
            "email": email,
            "phone": phone,
            "event": ticket.event.title
        }

        # Call your wallet transfer function
        pay_response, request_ref = transfer_from_wallet(request.user, total_kobo, acct_number, user_data)

        if pay_response.get("status") == "Successful":
            purchase = TicketPurchase.objects.create(
                ticket=ticket,
                full_name=full_name,
                email=email,
                copies=copies,
                total_price=total_kobo / 100,
                user=request.user
            )

            # Send receipt with QR code to customer email
            email_subject = f"Your Ticket Receipt - {ticket.event.title}"
            email_body = f"Hello {full_name},\n\nThank you for purchasing {copies} ticket(s) for {ticket.event.title}.\nPlease find your ticket QR code attached.\n\nEnjoy the event!\n\nYourApp Team"

            email_msg = EmailMessage(
                subject=email_subject,
                body=email_body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[email]
            )
            
            if purchase.qr_code:
                email_msg.attach_file(purchase.qr_code.path)

            email_msg.send(fail_silently=False)

            return Response({"message": "Purchase successful, receipt sent to email", "ticket_code": str(purchase.reference_id)})

        elif pay_response.get("status") == "WaitingForOTP":
            return Response({
                "status": "otp_required",
                "request_ref": request_ref,
                "message": "OTP required to complete transaction"
            }, status=202)

        return Response({
            "status": "error",
            "details": pay_response.get("message", "Transfer failed")
        }, status=400)


