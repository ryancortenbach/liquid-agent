# Collaboration workflow

The shared integration branch is `codex/liquid-core`. Ryan and SpectrrT should each create a
feature branch from its latest commit. This keeps either person free to choose a feature without
blocking the other.

## Start independent work

```bash
git fetch origin
git switch -c <your-name>/<feature> origin/codex/liquid-core
git push -u origin <your-name>/<feature>
```

Commit one coherent feature per branch, open a pull request into `codex/liquid-core`, and state
which files or subsystem the branch owns in the pull request description. Before merging, update
from the integration branch and rerun the checks:

```bash
git fetch origin
git rebase origin/codex/liquid-core
uv run ruff check app tests scripts sim
uv run pytest
```

## Suggested work boundaries

- Photo and iMessage intake: `app/photos`, `app/channels`, and related API wiring
- eBay publication: a new adapter under `app/market` and its tests
- Facebook Marketplace assistance: a separate browser adapter and its tests
- Demo experience: dashboard, scenario fixtures, and recording assets

These are suggestions, not assignments. Claim the area you choose in the pull request before
making broad edits. Avoid changing the shared database models from two branches at once. If a
feature needs a model change, describe it in the pull request so the other branch can account for
it early.
