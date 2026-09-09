from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa

# 1. 生成 RSA 私钥
private_key = rsa.generate_private_key(
    public_exponent=65537,
    key_size=2048,
)

# 2. 保存私钥
with open("private.pem", "wb") as f:
    f.write(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )

# 3. CSR 中的身份信息
subject = x509.Name([
    x509.NameAttribute(NameOID.COUNTRY_NAME, "CA"),
    x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Btrust"),
    x509.NameAttribute(NameOID.COMMON_NAME, "NetSuite M2M"),
])

# 4. 生成 CSR
csr = (
    x509.CertificateSigningRequestBuilder()
    .subject_name(subject)
    .sign(private_key, hashes.SHA256())
)

# 5. 保存 CSR
with open("request.csr", "wb") as f:
    f.write(csr.public_bytes(serialization.Encoding.PEM))

print("Generated:")
print("  private.pem   <-- keep secret")
print("  request.csr   <-- send to administrator")