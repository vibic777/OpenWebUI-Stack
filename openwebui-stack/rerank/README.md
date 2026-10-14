# llama.cpp rerank — CPU x86, like Portainer (separate project). No host ports.

**Optional.** The main stack runs without this. How to start / drop: [../START.md](../START.md).

Image: `ghcr.io/ggml-org/llama.cpp:server@sha256:7fa75431b8a78f9528cab4aaf65e8ae3e13da546a3cc7221247ca81bab864d84`
`platform: linux/amd64`. Not CUDA, not ARM.

Model: `bge-reranker-v2-m3-Q8_0.gguf` from Hugging Face [`gpustack/bge-reranker-v2-m3-GGUF`](https://huggingface.co/gpustack/bge-reranker-v2-m3-GGUF), approximately 607 MiB. Download the model separately; it is not stored in this repository. Save the actual GGUF file as `rerank/models/model.gguf` before enabling this service. See [`models/SOURCE.txt`](models/SOURCE.txt) for artifact details.

Run these commands from the project root (the directory containing `docker-compose.yml`), after downloading the model and starting the main stack:

```bash
docker compose -f docker-compose.rerank.yml up -d
docker compose -f docker-compose.yml -f docker-compose.rerank-owui.yml up -d
```

Off (keep volumes). Recreate Open WebUI **first**, then stop llama.cpp — otherwise the UI still points at a dead URL:

```bash
docker compose up -d
docker compose -f docker-compose.rerank.yml down
```

Never `down -v`. Do not put this id in `EMBEDDING_MODEL`.

Probe (no host port):

```bash
./rerank/test-rerank.sh
# expect: ok  and  best_index 1
```

Ask a question whose answer is in a Knowledge collection. Check whether the reranker handled the query:

```bash
docker logs open-webui --since 5m 2>&1 | grep ExternalReranker
```

Look for `ExternalReranker:predict:query`. If the embedding request fails first (for example, HTTP 400 on `/v1/embeddings`), Open WebUI may not invoke the reranker. The reranker has no published host port; it is available to Open WebUI over its internal Docker network.
