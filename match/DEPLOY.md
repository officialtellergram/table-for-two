# Deploy runbook — Table for Two — Tonight

**Discovered 2026-09-30: the pipeline already exists.** Workers Builds has been
connected to this repo since July, bound to the worker **`table-for-two`**
(account officialtellergram), running `npx wrangler versions upload` on every
push. **Triggers rewired 2026-09-30 (via API):** `reframe` is now the PRODUCTION
build branch — a push runs `npx wrangler deploy` (assets + routes, production
traffic, custom domain). `main` matches **no trigger at all**: its cron and
freshness commits build nothing and can never hijack the domain (which is
exactly what happened the first night, when a freshness-auditor commit on
main — no skip token — redeployed main's repo-root clone over production).

## The URLs

| URL | What it is |
| --- | --- |
| `https://reframe-table-for-two.officialtellergram.workers.dev` | **Stable branch alias** — updates on every push to `reframe`. This is the live app. |
| `https://<version-id>-table-for-two.officialtellergram.workers.dev` | Immutable per-version URL (printed in each build's log). |
| `https://table-for-two.officialtellergram.workers.dev` | The worker's **production traffic** — serves whatever version was last *promoted* (see below). |
| `https://tonight.tablefortwo.city` | Future custom domain — routes block in `wrangler.jsonc`, currently commented. |

## Daily workflow

**`git push origin reframe` = live on tonight.tablefortwo.city.** That's the
whole pipeline — production deploy, ~40s. Watch via dashboard (worker →
Deployments) or the cloudflare-builds MCP tools.

## Why `wrangler.jsonc` matters (do not rename the worker)

Before this config existed, builds fell back to autoconfig defaults and
uploaded the **entire repo root as public assets — including `.git/`**. The
root `wrangler.jsonc` scopes assets to `./match` (plus `match/.assetsignore`
for the .md files) and its `"name"` MUST stay `table-for-two` to match the
Builds binding — a different name makes builds create a stray second worker.

## Rolling back / pinning a version

Reframe builds now deploy production directly — promotion is only needed to
ROLL BACK to an earlier version:

```powershell
cd C:\Users\Karen Plankton\Desktop\t42-reframe
npx wrangler versions deploy    # interactive: pick the latest version, 100%
```

(wrangler is OAuth-authed on this machine as officialtellergram@gmail.com;
if auth expires: `npx wrangler login`, approve in browser.)

## Custom domain — tonight.tablefortwo.city (apex untouched)

1. Zone DNS → confirm no existing `tonight` record (delete only that if found).
   **Never touch the apex records** — `tablefortwo.city` stays on GitHub Pages.
2. Uncomment the `"routes"` block in `wrangler.jsonc`, push, then promote
   (`wrangler versions deploy`) — custom domains serve production traffic, not
   branch previews. Cloudflare auto-creates the DNS record + cert.
3. Verify all three: `tonight.` serves the app; apex still GitHub Pages;
   workers.dev still up (`workers_dev: true` is explicit in config — required,
   or adding routes would silently disable it).

## Housekeeping (optional)

- GitHub branch `cloudflare/workers-autoconfig` (July's autoconfig PR) is
  inert now that the repo ships real config — safe to delete.
- The pre-fix production version still serves the old repo-root clone
  (with `.git/`) at the worker's production URL until a newer version is
  promoted. Promoting once fixes that.
