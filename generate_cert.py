from datetime import datetime, timedelta, timezone
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa

key = rsa.generate_private_key(
    public_exponent=65537,
    key_size=3072,
)

subject = issuer = x509.Name([
    x509.NameAttribute(NameOID.COUNTRY_NAME, "CA"),
    x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Btrust"),
    x509.NameAttribute(NameOID.COMMON_NAME, "Btrust NetSuite M2M"),
])

cert = (
    x509.CertificateBuilder()
    .subject_name(subject)
    .issuer_name(issuer)
    .public_key(key.public_key())
    .serial_number(x509.random_serial_number())
    .not_valid_before(datetime.now(timezone.utc))
    .not_valid_after(datetime.now(timezone.utc) + timedelta(days=730))
    .sign(key, hashes.SHA256())
)

with open("private.pem", "wb") as f:
    f.write(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )

with open("certificate.pem", "wb") as f:
    f.write(cert.public_bytes(serialization.Encoding.PEM))

print("generated: private.pem, certificate.pem")