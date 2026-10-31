# Security

Social Post Tracker stores drafts and results locally. Its server checks Host and Origin, uses a request token, limits requests, and suppresses access logs. The interface escapes user text. The runtime folder rejects symlinks and folders owned by another account. Results are capped at 1,000 rows; the app reports a clear error at the limit and keeps existing rows. A “User marked verified” label records your selection, not an independent source check.

Local data is plaintext protected by account permissions. Use your Mac’s disk encryption to protect saved files. The native app has an ad-hoc code signature. This lets the installer check whether its files changed. It does not prove who made the app. The build is not notarized.

Report security issues through [GitHub private vulnerability reporting](https://github.com/gmperkinsmba/social-post-tracker/security/advisories/new).
