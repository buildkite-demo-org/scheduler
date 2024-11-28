# scheduler

## Forward webhooks from Buildkite

```bash
pysmee forward https://smee.io/<your-endpoint> http://localhost:5000/webhooks
```

The cool docker variant:
```bash
docker run --network=host ghcr.io/chmouel/gosmee:latest client https://smee.io/<your-endpoint> http://localhost:5000/webhooks
```

TestPR2
