# SeaweedFS (S3 for Open WebUI files)

S3 is loopback / Docker DNS only (`openwebui-seaweedfs:8333`). Filer UI is `https://<host>/filer/` + nginx Basic.

```bash
cp s3.json.example s3.json
# accessKey / secretKey = S3_ACCESS_KEY / S3_SECRET_KEY in .env
```

Do not commit live `s3.json`.

Same file uploaded twice → two objects (new UUID). No dedup.

**Targeted delete:** Open WebUI (Knowledge / Files), not Filer and not `volume rm`. Details: [../FAQ.md](../FAQ.md) § Files in SeaweedFS, [START.md](../START.md) does not touch this volume.
