from rest_framework import serializers

from .models import Verification


class StartVerificationSerializer(serializers.Serializer):

    reference_id = serializers.CharField(
        max_length=100
    )


class VerificationSerializer(serializers.ModelSerializer):

    class Meta:

        model = Verification

        fields = [
            "id",
            "reference_id",
            "verification_status",
            "verification_mode",
            "verification_type",
            "verification_value",
            "selfie_url",
            "id_url",
            "confidence_score",
            "created_at",
            "completed_at",
        ]