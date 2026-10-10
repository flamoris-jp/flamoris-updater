# Private GitHub Releases

Updater 1.0.5 accepts the same repository-owned Release URLs for public and private catalogs/payloads. Register `https://github.com/OWNER/REPO/releases/latest/download/catalog.json` in the existing screen. Recipes keep immutable versioned asset URLs. Payloads stay in their own repository; there is no mirror or centralized distribution.

Public URLs are downloaded anonymously first. Only an initial GitHub 404 triggers the private Release API path. That path uses, in order, `GH_TOKEN`, `GITHUB_TOKEN`, or `/usr/bin/gh auth token --hostname github.com` in the downloader's OS context. Credentials must grant the selected private repository **Contents: read**. Updater adds no login page, token input, credential database or persistent copy of GitHub credentials. It never prints the token or includes it in Jobs, catalogs or errors.

## Reuse the operator's existing GitHub CLI login

Run as the normal operator account:

```bash
gh auth status --hostname github.com
```

If that account is not authenticated, run `gh auth login --hostname github.com` as that account. Linux systemd's root manager does not inherit a normal user's GitHub login. Select the existing account in a root-managed drop-in; replace `operator` with the actual local account:

```bash
sudo systemctl edit flamoris-updater-manager.service
```

Add:

```ini
[Service]
Environment=FLAMORIS_GITHUB_USER=operator
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl restart flamoris-updater-manager.service
```

Use an idle maintenance window with no unfinished install/update Job. The manager runs the fixed GitHub CLI token-read command as the selected normal account through `/usr/sbin/runuser`; its home/config/keychain must be usable noninteractively. It does not run GitHub CLI under sudo as that user, clone a repository, or copy credentials into Updater. `/usr/bin/gh` is an optional external requirement only for private downloads without an environment token; public downloads remain independent of it.

For unattended installations, an existing service environment may instead provide `GH_TOKEN` or `GITHUB_TOKEN`. Keep that configuration administrator-controlled, out of public configuration and the unprivileged Web service. This document does not create a token or provision host credentials.

## Download boundary

The token goes only to exact `https://api.github.com` GET endpoints constructed for the requested repository/release/asset. Metadata redirects are rejected. An asset can be streamed by the API or redirected to exact `https://release-assets.githubusercontent.com` on the default HTTPS port; the storage request carries no Authorization or Cookies. API-provided URLs cannot select a different host or repository. Pagination, metadata and payload sizes, redirect counts and response lifetimes are bounded. Existing SHA-256 checks and immutable recipes remain enforced.

Missing access produces `github_access_required`; expired/insufficient permissions fail without exposing credentials. Other registered catalogs continue to refresh. GitHub Enterprise, private raw/source URLs and arbitrary authenticated HTTPS sites are outside this path.

An existing 1.0.3/1.0.4 installation needs the public 1.0.5 self-update catalog before using private app catalogs. Existing pinned supervisors can fetch that public Updater bundle. The new manager handles private app downloads; no supervisor replacement is needed for those apps. A supervisor fetching a private Updater bundle would separately need the new downloader and its own OS credential context. No live service or installation is changed by this source/release preparation.
