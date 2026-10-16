"""attested_rpc.py: attested, encrypted invocation of a cloud-only feature (Algorithm 1).

Implements lines 1-8 and 10-13 of Algorithm 1; the rate limiter (line 9) and the output
watermark (line 13) are left out. The client derives a per-request AES-GCM key from an
ephemeral X25519 exchange with the server and signs (ephemeral key || nonce || timestamp)
with an Ed25519 device key. In production that key would be bound to a platform
attestation verdict (Play Integrity / App Attest); here a locally registered key stands in.

Run:  python attested_rpc.py
"""
import base64, json, os, time
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

b64 = lambda b: base64.b64encode(b).decode()
unb64 = base64.b64decode
raw = dict(encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw)

def derive_key(shared, nonce):
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=nonce, info=b"sa-heacs/v1").derive(shared)

# ---- server ----------------------------------------------------------------
SERVER_KEY = X25519PrivateKey.generate()
TRUSTED_DEVICE_KEYS = {}   # stands in for a Play Integrity / App Attest verifier
SEEN_NONCES, MAX_SKEW_S = set(), 30

def proprietary_filter(pixels):
    """The protected IP. It exists only in the server process."""
    mean = sum(pixels) / len(pixels)
    return [round(0.8 * p + 0.2 * mean, 4) for p in pixels]

FEATURES = {"neural_filter_v3": proprietary_filter}

class Envelope(BaseModel):
    device_id: str; client_pub: str; nonce: str; ts: int; signature: str; ciphertext: str

app = FastAPI(title="SA-HEACS secure cluster")

@app.post("/v1/invoke")
def invoke(env: Envelope):
    nonce = unb64(env.nonce)
    if abs(time.time() - env.ts) > MAX_SKEW_S or nonce in SEEN_NONCES:
        raise HTTPException(401, "stale or replayed request")
    device = TRUSTED_DEVICE_KEYS.get(env.device_id)
    if device is None:
        raise HTTPException(401, "device not attested")
    signed = unb64(env.client_pub) + nonce + str(env.ts).encode()
    try:
        device.verify(unb64(env.signature), signed)
    except Exception:
        raise HTTPException(401, "bad attestation signature")
    SEEN_NONCES.add(nonce)
    key = derive_key(SERVER_KEY.exchange(X25519PublicKey.from_public_bytes(unb64(env.client_pub))), nonce)
    aes = AESGCM(key)
    req = json.loads(aes.decrypt(nonce[:12], unb64(env.ciphertext), signed))
    fn = FEATURES.get(req["feature"])
    if fn is None:
        raise HTTPException(404, "unknown feature")
    out = json.dumps({"result": fn(req["args"])}).encode()
    return {"ciphertext": b64(aes.encrypt(nonce[12:] + b"\x00" * 8, out, signed))}

# ---- client shell: no proprietary logic, only identity and transport --------
class ClientShell:
    def __init__(self, http, server_pub, device_id, device_key):
        self.http, self.server_pub, self.device_id, self.device_key = http, server_pub, device_id, device_key

    def call(self, feature, args):
        eph = X25519PrivateKey.generate()
        nonce, ts = os.urandom(16), int(time.time())
        pub = eph.public_key().public_bytes(**raw)
        signed = pub + nonce + str(ts).encode()
        aes = AESGCM(derive_key(eph.exchange(self.server_pub), nonce))
        body = json.dumps({"feature": feature, "args": args}).encode()
        env = Envelope(device_id=self.device_id, client_pub=b64(pub), nonce=b64(nonce), ts=ts,
                       signature=b64(self.device_key.sign(signed)),
                       ciphertext=b64(aes.encrypt(nonce[:12], body, signed)))
        r = self.http.post("/v1/invoke", json=env.model_dump())
        r.raise_for_status()
        out = aes.decrypt(nonce[12:] + b"\x00" * 8, unb64(r.json()["ciphertext"]), signed)
        return json.loads(out)["result"]

if __name__ == "__main__":
    from fastapi.testclient import TestClient
    device_key = Ed25519PrivateKey.generate()
    TRUSTED_DEVICE_KEYS["device-42"] = device_key.public_key()   # result of a passed attestation
    shell = ClientShell(TestClient(app), SERVER_KEY.public_key(), "device-42", device_key)
    print("server result:", shell.call("neural_filter_v3", [0.1, 0.5, 0.9]))
    rogue = ClientShell(TestClient(app), SERVER_KEY.public_key(), "device-42", Ed25519PrivateKey.generate())
    try:
        rogue.call("neural_filter_v3", [0.1])
    except Exception as e:
        print("unattested clone rejected:", e.response.status_code, e.response.json()["detail"])
