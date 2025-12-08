# events/serializers.py
from rest_framework import serializers
from .models import Event
from .models import Ticket, TicketPurchase

class TicketSerializer(serializers.ModelSerializer):
    class Meta:
        model = Ticket
        fields = ['name', 'price','ticket_image']

class EventSerializer(serializers.ModelSerializer):
    tickets = TicketSerializer(many=True)  # Nested tickets

    class Meta:
        model = Event
        fields = ['id', 'title', 'description', 'date', 'location', 'image','bank_name','bank_code','account_number','account_name', 'tickets']

    def create(self, validated_data):
        tickets_data = validated_data.pop('tickets')
        event = Event.objects.create(**validated_data)
        for ticket_data in tickets_data:
            Ticket.objects.create(event=event, **ticket_data)
        return event






 #Ticket Purchase

class TicketPurchaseSerializer(serializers.ModelSerializer):
    confirm_email = serializers.EmailField(write_only=True)

    class Meta:
        model = TicketPurchase
        fields = [
            'id', 'user', 'full_name', 'email', 'confirm_email',
            'ticket', 'quantity', 'total_price', 'qr_code',
            'reference_id', 'created_at'
        ]
        read_only_fields = ['user', 'total_price', 'qr_code', 'reference_id', 'created_at']

    def validate(self, data):
        if data['email'] != data['confirm_email']:
            raise serializers.ValidationError("Emails do not match.")

        ticket = data['ticket']
        quantity = data['quantity']

        # Check if there's a ticket limit
        if ticket.quantity is not None and quantity > ticket.quantity:
            raise serializers.ValidationError("Not enough tickets available.")

        return data

    def create(self, validated_data):
        validated_data.pop('confirm_email')
        ticket = validated_data['ticket']
        quantity = validated_data['quantity']

        # Calculate total price
        validated_data['total_price'] = ticket.price * quantity

        # Reduce available quantity (if limited)
        if ticket.quantity is not None:
            ticket.quantity -= quantity
            ticket.save()

        return super().create(validated_data)
