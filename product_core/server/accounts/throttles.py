from rest_framework.throttling import AnonRateThrottle


class LoginRateThrottle(AnonRateThrottle):
    scope = "login"


class EmailOtpRequestThrottle(AnonRateThrottle):
    scope = "email_otp_request"


class EmailOtpVerifyThrottle(AnonRateThrottle):
    scope = "email_otp_verify"
