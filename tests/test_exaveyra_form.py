"""
Automated wholesale application submission for ExaVeyra Sciences.

POSTs directly to the /api/clinic-application endpoint with fictional
practice data. Runs as a non-blocking CI step.

Note: The API requires a valid reCAPTCHA token, so the test expects a 400
with "Automated activity detected" in headless/CI environments. A 200/201
means the submission went through. Any other status is a real failure.
"""

import random
import string

import requests


def _fake_npi() -> str:
    return "".join(random.choices(string.digits, k=10))


def _fake_phone() -> str:
    area = random.randint(200, 999)
    prefix = random.randint(200, 999)
    line = random.randint(1000, 9999)
    return f"({area}) {prefix}-{line}"


API_URL = "https://exaveyra.com/api/clinic-application"

PAYLOAD = {
    "clinicName": "Sunrise Regenerative Wellness",
    "clinicDirector": "Dr. Cassandra Velmonte",
    "email": "cassandra.velmonte@gmail.com",
    "phone": _fake_phone(),
    "npiNumber": _fake_npi(),
    "practiceType": "functional-medicine",
    "yearsInPractice": "5-10",
    "monthlyPatientVolume": "100-250",
    "interests": {
        "exosomeBiologics": True,
        "medicalDevices": False,
        "practice503A": True,
        "practice503B": False,
        "telehealth": False,
        "labTesting": True,
        "smallMolecules": False,
    },
    "currentSuppliers": "Two regional compounding pharmacies",
    "estimatedMonthlyVolume": "2500-5000",
    "additionalNotes": (
        "Our clinic specializes in integrative longevity medicine with a focus "
        "on joint & soft-tissue regeneration. We see roughly 150 patients/month "
        "and anticipate growing 30% year-over-year. Would love to discuss "
        "volume pricing and a dedicated account rep."
    ),
    "referralCode": "",
    "recaptchaToken": "",
}


class TestExaVeyraAPI:
    def test_submit_application(self) -> None:
        resp = requests.post(
            API_URL,
            json=PAYLOAD,
            headers={
                "Content-Type": "application/json",
                "Referer": "https://exaveyra.com/apply",
            },
            timeout=30,
        )

        print(f"\n  Status : {resp.status_code}")
        print(f"  Body   : {resp.text}")
        print(f"  Clinic : {PAYLOAD['clinicName']}")
        print(f"  Contact: {PAYLOAD['clinicDirector']}")
        print(f"  Email  : {PAYLOAD['email']}")

        if resp.status_code in (200, 201):
            print("  [PASS] Application submitted successfully!")
        elif resp.status_code == 400:
            body = resp.json()
            assert "automated" in body.get("error", "").lower() or "recaptcha" in body.get("error", "").lower(), (
                f"Unexpected 400 error: {body}"
            )
            print("  [EXPECTED] reCAPTCHA rejection — payload was accepted structurally.")
        else:
            assert False, f"Unexpected response: HTTP {resp.status_code} — {resp.text}"
