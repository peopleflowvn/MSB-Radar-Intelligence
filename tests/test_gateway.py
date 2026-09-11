import unittest

from radar_intelligence.providers import Capability, GatewayRequest, GatewayResponse, ModelGateway


class FakeTransport:
    def __init__(self) -> None:
        self.model = None

    def complete(self, *, model: str, text: str, timeout_seconds: float) -> GatewayResponse:
        self.model = model
        return GatewayResponse(text.upper(), "greennode", model)


class GatewayTest(unittest.TestCase):
    def test_business_chooses_capability_not_concrete_model(self) -> None:
        transport = FakeTransport()
        gateway = ModelGateway({
            Capability.FAST: "fast-alias",
            Capability.DEEP: "deep-alias",
            Capability.VISION: "vision-alias",
            Capability.EMBEDDING: "embedding-alias",
        }, transport)
        response = gateway.complete(GatewayRequest(Capability.DEEP, "compare"))
        self.assertEqual(transport.model, "deep-alias")
        self.assertEqual(response.output_text, "COMPARE")


if __name__ == "__main__":
    unittest.main()

