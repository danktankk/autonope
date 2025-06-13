AutoNope prevents surprise upgrades when GitHub release notes include breaking changes.

1. Label any Docker Compose service that should **not auto‑update** without review:

```yaml
labels:
  - autonope
```

2. Add the repo and keywords to `config/config.yml`.
3. Fire up AutoNope:

```bash
docker compose up -d autonope
```

You’ll receive a Discord message whenever a breaking change is published. Then update manually when ready.
