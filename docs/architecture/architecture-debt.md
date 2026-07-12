# Architecture finalization debt ledger

> **Historical migration ledger.** Initial counts are evidence from commit `97c9618`;
> the final zero-debt claim is continuously rechecked by the current architecture gate.

The finalization audit at commit `97c9618` replaced the original narrow architecture
checker with whole-production-tree SQL placement checks, alias-aware module graph
resolution, compatibility-facade reporting, and pool/SQL bans for domain,
application, workflow, and inbound layers.

The initial mechanically detected debt is:

| Rule | Initial violations |
|---|---:|
| Owner SQL outside approved adapters | 10 |
| Pool initialization in non-outbound layers | 2 |
| Business-module compatibility-facade imports | 199 |
| Canonical cross-module internal imports | 0 |

The exact live list is produced by:

```bash
uv run python tools/check_architecture.py
```

No count-based exception is accepted by CI: the checker reports every violation and
returns non-zero until the debt reaches zero. This file is updated as each sequential
work package removes a class of debt; it is not an architectural waiver.

## Final state

The temporary debt is now fully burned down:

| Rule | Final violations |
|---|---:|
| Owner SQL outside approved adapters | 0 |
| Pool management in non-outbound layers | 0 |
| Business-module compatibility-facade imports | 0 |
| Canonical cross-module internal imports | 0 |
| Alias-aware executable dependency cycles | 0 |

There is no migration-debt allowlist.
