from rest_framework import serializers
from .models import VendorQRCode, Scan2PayTransaction

class VendorQRCodeSerializer(serializers.ModelSerializer):
    class Meta:
        model = VendorQRCode
        fields = "__all__"
        read_only_fields = ["qr_code_image", "vendor", "created_at"]

    def create(self, validated_data):
        # Attach vendor automatically from request context
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            raise serializers.ValidationError("User authentication required to create QR code.")

        qr_code = VendorQRCode.objects.create(vendor=request.user, **validated_data)
        return qr_code


class Scan2PayTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Scan2PayTransaction
        fields = "__all__"
        read_only_fields = ["reference_id", "status", "created_at", "vendor"]
