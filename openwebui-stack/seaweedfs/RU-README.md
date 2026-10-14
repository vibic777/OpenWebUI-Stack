# SeaweedFS (S3 для файлов Open WebUI)

Русская копия [README.md](README.md).

S3 только loopback / Docker DNS (`openwebui-seaweedfs:8333`). Filer UI: `https://<хост>/filer/` + nginx Basic.

```bash
cp s3.json.example s3.json
# accessKey / secretKey = S3_ACCESS_KEY / S3_SECRET_KEY в .env
```

Живой `s3.json` в git не коммитить.

Один файл два раза → два объекта (новый UUID). Дедупа нет.

**Точечное удаление:** Open WebUI (Knowledge / Files), не Filer и не `volume rm`. Подробно: [../RU-FAQ.md](../RU-FAQ.md), раздел про файлы. [RU-START.md](../RU-START.md) этот том не трогает.
