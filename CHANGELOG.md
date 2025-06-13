# 🧠 AutoNope v0.1.0 — MVP

**Purpose**: Prevent automatic Docker Compose updates when breaking changes are detected in GitHub release notes.
Now with tests, multi-channel notifications, CI, and multi-arch image support.

---

## 🚀 Features

| Feature                     | File(s)                                      | Summary                                                                 |
|----------------------------|----------------------------------------------|-------------------------------------------------------------------------|
| **Unit tests & CI**        | \`tests/\`, \`.github/workflows/ci.yml\`         | Runs pytest, ruff, and pyright on every push. Fails if coverage < 100%. |
| **Multi-channel notify**   | \`autonope/notify.py\`, \`config/config.yml\`    | Discord, Slack, and SMTP support. Configured under \`notify.channels:\`.  |
| **Release-ID tracking**    | \`autonope/main.py\`, DB schema                | Tracks last \`release_id\` to avoid timezone drift.                       |
| **Per-repo interval**      | \`config/config.yml\`, scheduler logic         | Supports custom \`interval:\` per repo (e.g. \`6h\`, \`3d\`).                 |
| **Multi-arch Docker image**| \`.github/workflows/docker.yml\`               | Pushes \`linux/amd64\` + \`linux/arm64/v8\` images on every tag release.   |

