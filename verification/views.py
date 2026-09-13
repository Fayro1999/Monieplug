from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated

from .models import Verification
from .services import DojahService, create_verification
from .serializers import (
    StartVerificationSerializer,
    VerificationSerializer,
)


class StartVerificationView(APIView):

    permission_classes = [IsAuthenticated]

    def post(self, request):

        serializer = StartVerificationSerializer(
            data=request.data
        )

        serializer.is_valid(raise_exception=True)

        reference_id = serializer.validated_data["reference_id"]

        try:

            create_verification(
                request.user,
                reference_id
            )

            verification = DojahService.update_verification(
                reference_id
            )

            return Response(
                {
                    "success": True,
                    "message": "Verification completed.",
                    "data": VerificationSerializer(
                        verification
                    ).data
                },
                status=status.HTTP_200_OK
            )

        except Exception as e:

            return Response(
                {
                    "success": False,
                    "message": str(e)
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class VerificationStatusView(APIView):

    permission_classes = [IsAuthenticated]

    def get(self, request):

        verification = (
            Verification.objects
            .filter(user=request.user)
            .order_by("-created_at")
            .first()
        )

        if verification is None:

            return Response(
                {
                    "success": True,
                    "verified": False,
                    "status": "Not Started"
                },
                status=status.HTTP_200_OK
            )

        return Response(
            {
                "success": True,
                "verified": request.user.is_identity_verified,
                "reference_id": verification.reference_id,
                "verification_status": verification.verification_status,
                "verification_mode": verification.verification_mode,
                "verification_type": verification.verification_type,
                "selfie_url": verification.selfie_url,
                "id_url": verification.id_url,
                "verified_at": request.user.identity_verified_at,
            },
            status=status.HTTP_200_OK
        )