"""Certificates for the HTTPS run of the feasibility check.

    python -m experiments.feasibility.make_certs

Writes, in experiments/feasibility/tls/, a test certificate authority (ca.pem) and
one server certificate (server.pem, server.key) signed by it, valid for the four
services by their names in the compose network and for 127.0.0.1, so that every
hop, from the client to the gateway and from the gateway to the UMMS, the IDMS and
the DCMS, is encrypted and verified. Needs the openssl command. For tests only:
the keys are not protected and are not kept in the repository.
"""
import subprocess
from pathlib import Path

TLS = Path(__file__).parent / "tls"
NAMES = ["gateway", "umms", "idms", "dcms", "localhost"]


def openssl(*args: str) -> None:
    subprocess.run(["openssl", *args], check=True, capture_output=True)


def main() -> None:
    TLS.mkdir(exist_ok=True)
    ca_key, ca, key, csr, cert = (str(TLS / n) for n in ("ca.key", "ca.pem", "server.key", "server.csr", "server.pem"))
    ext = TLS / "server.ext"
    ext.write_text("subjectAltName=" + ",".join([f"DNS:{n}" for n in NAMES] + ["IP:127.0.0.1"]) + "\n"
                   "basicConstraints=CA:FALSE\nkeyUsage=digitalSignature,keyEncipherment\n"
                   "extendedKeyUsage=serverAuth\n", encoding="utf-8")
    openssl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", ca_key, "-out", ca, "-days", "30",
            "-subj", "/CN=MSIDS-IoT test CA", "-addext", "basicConstraints=critical,CA:TRUE",
            "-addext", "keyUsage=critical,keyCertSign,cRLSign")
    openssl("req", "-newkey", "rsa:2048", "-nodes", "-keyout", key, "-out", csr, "-subj", "/CN=msids-feasibility")
    openssl("x509", "-req", "-in", csr, "-CA", ca, "-CAkey", ca_key, "-CAcreateserial", "-out", cert,
            "-days", "30", "-extfile", str(ext))
    print("wrote", TLS)


if __name__ == "__main__":
    main()
