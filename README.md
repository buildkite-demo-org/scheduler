# scheduler

## Forward webhooks from Buildkite

```bash
pysmee forward https://smee.io/<your-endpoint> http://localhost:5000/webhooks
```

## Docker Go Smee Client

### Github
```bash
docker run --network=host ghcr.io/chmouel/gosmee:latest client https://smee.io/<your-endpoint> http://localhost:5000/github_webhooks
```

### Buildkite
```bash
docker run --network=host ghcr.io/chmouel/gosmee:latest client https://smee.io/<your-endpoint> http://localhost:5000/buildkite_webhooks
```
TestCommit
