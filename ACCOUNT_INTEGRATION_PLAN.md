# YTSage Multi-Account and Bilibili Library Integration Plan

## 1. Purpose

Add first-class platform accounts to YTSage, starting with multiple Bilibili accounts. A user should be able to:

- Add, rename, verify, replace credentials for, set as default, and remove multiple Bilibili accounts.
- Browse each account's created favorites, collected favorites, and watch-later library.
- Open a resource and fetch its entries page by page.
- Select entries and send them through the existing analysis and download workflow.
- Download a resource now, monitor it for additions, or do both.
- Preserve the selected account across analysis, task execution, retry, restart, and monitor checks.

This plan treats accounts as local credential identities. YTSage does not create a Bilibili account and does not store a username or password.

## 2. Product Scope

### 2.1 Phase-one scope

- Bilibili accounts imported using Netscape or supported JSON cookie exports.
- Multiple accounts with a user-defined label.
- Identity verification through Bilibili's authenticated navigation endpoint.
- Created favorites, including private favorites owned by the account.
- Collected favorites where available to the logged-in account.
- Favorite entries with server-side pagination.
- Watch-later entries with server-side pagination over the returned data.
- Existing public Bilibili collection and series URL support.
- Account-aware analysis, downloads, retries, restarts, and playlist monitors.
- Existing generic, Bilibili, and YouTube cookie profiles remain compatible during migration.

### 2.2 Deferred scope

- QR-code login.
- Password login or storage.
- Automatic cookie refresh through platform login flows.
- Account actions such as adding/removing favorites, likes, follows, comments, or messages.
- Subscription feeds, viewing history, bangumi favorites, and dynamic feeds.
- YouTube multi-account library discovery. The account model must support it later, but the first provider is Bilibili.
- Circumvention of geographic, membership, account, anti-bot, or content-access restrictions.

### 2.3 Non-goals

- YTSage is not an account vault or password manager.
- YTSage will not return imported cookie content through an API.
- YTSage will not expose arbitrary filesystem cookie paths to clients.
- YTSage will not silently switch a task or monitor to another account when its bound account is unavailable.

## 3. Architectural Principles

1. **Stable account identity**: persist `account_id`, not a cookie path, in tasks and monitors.
2. **Late credential resolution**: resolve the current cookie file when analysis or execution starts so replacing cookies repairs existing monitors.
3. **Provider boundary**: platform resource APIs live behind a Bilibili provider service, separate from generic yt-dlp orchestration.
4. **Least credential exposure**: cookie contents remain in account-specific files and are never logged or returned.
5. **On-demand pagination**: list resources first; fetch entries only when a user opens a resource and only for the requested page.
6. **Explicit failure**: missing, invalid, or deleted accounts produce a clear account error instead of anonymous fallback.
7. **Backward compatibility**: existing installations and tasks using legacy cookie profiles keep working.
8. **Reuse download logic**: provider APIs discover entries; yt-dlp remains responsible for format analysis and media downloads.

## 4. Domain Model

### 4.1 Account

Add these backend models:

```python
Platform = Literal["bilibili"]
AccountState = Literal["valid", "invalid", "unknown", "expired"]

class AccountCreateRequest(BaseModel):
    platform: Platform
    label: str = Field(min_length=1, max_length=80)
    cookie_content: str = Field(max_length=2_000_000)
    make_default: bool = False

class AccountUpdateRequest(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=80)
    cookie_content: str | None = Field(default=None, max_length=2_000_000)
    make_default: bool | None = None

class AccountResponse(BaseModel):
    id: str
    platform: Platform
    label: str
    external_id: str | None
    display_name: str | None
    avatar_url: str | None
    vip_type: int | None
    state: AccountState
    cookie_status: CookieProfileStatus
    is_default: bool
    last_verified_at: str | None
    last_error: str | None
    created_at: str
    updated_at: str
```

`external_id` is the platform UID. It may be absent until successful verification.

### 4.2 Account resource

Normalize platform libraries into a generic resource shape:

```python
AccountResourceType = Literal[
    "created_favorite",
    "collected_favorite",
    "watch_later",
    "collection",
    "series",
]

class AccountResource(BaseModel):
    id: str
    account_id: str
    platform: Platform
    resource_type: AccountResourceType
    external_id: str
    title: str
    description: str | None
    cover_url: str | None
    owner_name: str | None
    owner_id: str | None
    item_count: int | None
    is_private: bool
    source_url: str
    updated_at: int | None
```

Use an opaque YTSage `id`, for example `created_favorite:1103407912`. API consumers must not parse it; provider code maps it back to platform parameters.

### 4.3 Paginated response

```python
class PageInfo(BaseModel):
    offset: int
    limit: int
    total: int
    has_more: bool

class AccountResourceListResponse(BaseModel):
    items: list[AccountResource]
    page: PageInfo

class AccountResourceEntriesResponse(BaseModel):
    resource: AccountResource
    entries: list[PlaylistEntry]
    page: PageInfo
```

The first version can support `offset` and `limit` externally while translating to Bilibili `pn` and `ps` internally. Enforce `1 <= limit <= 100`, with a default of 20.

## 5. Persistence and Credential Storage

### 5.1 SQLite schema

Add `platform_accounts`:

```sql
CREATE TABLE IF NOT EXISTS platform_accounts (
    id TEXT PRIMARY KEY,
    platform TEXT NOT NULL,
    label TEXT NOT NULL,
    external_id TEXT,
    display_name TEXT,
    avatar_url TEXT,
    vip_type INTEGER,
    state TEXT NOT NULL,
    cookie_filename TEXT NOT NULL,
    is_default INTEGER NOT NULL DEFAULT 0,
    last_verified_at TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(platform, label)
);

CREATE INDEX IF NOT EXISTS idx_platform_accounts_platform
ON platform_accounts(platform, created_at);

CREATE UNIQUE INDEX IF NOT EXISTS idx_platform_accounts_default
ON platform_accounts(platform)
WHERE is_default = 1;
```

Do not enforce `(platform, external_id)` uniqueness initially. Two credential exports may resolve to the same UID; the service should instead reject a duplicate after verification with an actionable conflict response, while still allowing invalid/unverified credentials to be repaired.

### 5.2 Cookie layout

```text
/config/accounts/{account_id}/cookies.txt
```

Rules:

- Generate `account_id` server-side as a random UUID hex value.
- Resolve the final path under `/config/accounts`; reject any path escaping that root.
- Create files with the most restrictive permissions supported by the host.
- Write replacement cookies atomically through a temporary sibling file and `replace()`.
- Store only `accounts/{account_id}/cookies.txt` in SQLite.
- Never include cookie values, full cookie lines, or auth query values in logs.
- Delete the account directory only after the database deletion transaction succeeds, or use a recoverable two-step tombstone operation.

### 5.3 Schema evolution

The current project initializes schema with `CREATE TABLE IF NOT EXISTS` and has no migration framework. For this feature:

- Add a small internal schema migration mechanism using `PRAGMA user_version`.
- Migration 1 creates `platform_accounts`.
- Migration 2 adds `account_id` to `playlist_monitors` if absent.
- Existing task options are JSON and require no table column migration.
- Always back up the database before a destructive future migration; this feature's migrations are additive.

### 5.4 Legacy cookie migration

Do not automatically move or delete existing files in the first release.

Compatibility behavior:

- Existing `cookies-bilibili.txt`, `cookies-youtube.txt`, and `cookies.txt` remain legacy profiles.
- If no explicit `account_id` is supplied, URL analysis/download uses the existing profile resolution.
- The Accounts page offers "Import existing Bilibili credentials" when `cookies-bilibili.txt` exists and no Bilibili account has been created.
- Import copies and normalizes the legacy content into a new account; it does not delete the legacy file.
- A later release may deprecate fixed platform profiles after adoption data and migration stability are known.

## 6. Backend Components

### 6.1 `AccountService`

Create `ytsage/server/services/accounts.py` responsible for:

- CRUD orchestration.
- Cookie normalization and atomic storage.
- Default-account invariants.
- Credential status calculation.
- Provider verification.
- Duplicate UID detection.
- Resolving an account to a safe cookie file.
- Guarding deletion when active tasks reference the account.

Recommended methods:

```python
create(request) -> AccountResponse
list(platform=None) -> list[AccountResponse]
get(account_id) -> AccountResponse
update(account_id, request) -> AccountResponse
verify(account_id) -> AccountResponse
set_default(account_id) -> AccountResponse
delete(account_id, force=False) -> None
resolve_cookie_file(account_id, expected_platform=None) -> Path
```

### 6.2 Provider interface

Create `ytsage/server/providers/base.py`:

```python
class AccountProvider(Protocol):
    platform: str
    def verify(self, cookie_file: Path) -> ProviderIdentity: ...
    def list_resources(self, account, kind, offset, limit) -> ProviderPage: ...
    def list_entries(self, account, resource_id, offset, limit) -> ProviderEntryPage: ...
```

Create `ytsage/server/providers/bilibili.py` for authenticated library discovery. Keep existing `analyzers/bilibili.py` focused on converting video, collection, and series metadata into `PlaylistEntry` values. Shared HTTP and parsing helpers can move to `providers/bilibili_common.py` only if real duplication appears.

### 6.3 Bilibili provider behavior

Identity verification:

- Request Bilibili navigation identity using the account cookie jar.
- Require `isLogin == true` for a valid account.
- Capture UID, display name, avatar, and VIP type from returned data.
- Distinguish invalid login from network/platform uncertainty.

Resource discovery:

- Created favorites: list folders for the verified UID.
- Collected favorites: request one page at a time.
- Watch later: fetch the authenticated list, then paginate the normalized result in the service if the upstream response is not paginated.
- Collections/series: expose only when a stable account-owned discovery endpoint is validated; URL-based collection support remains available regardless.

Favorite entries:

- Fetch only the requested page.
- Normalize video records into `PlaylistEntry` with stable `id`, Bilibili video URL, title, owner/channel, duration, and thumbnail.
- Preserve unavailable/deleted entries as disabled metadata if practical; do not silently shift indexes within a page.
- Calculate global indexes as `offset + position + 1`.

HTTP behavior:

- Use a single configured `requests.Session` per operation, not a global authenticated session.
- Set realistic `User-Agent`, `Referer`, and request timeout.
- Use bounded retries only for connection resets, 429, and transient 5xx responses.
- Respect `Retry-After` where present.
- Map provider codes to typed errors: authentication required, forbidden/private, not found, rate limited, and upstream unavailable.
- Do not implement WBI signing until an endpoint demonstrably requires it; keep signing isolated if later added.

### 6.4 API router

Create `ytsage/server/api/accounts.py`:

```text
GET    /api/accounts?platform=bilibili
POST   /api/accounts
GET    /api/accounts/{account_id}
PATCH  /api/accounts/{account_id}
DELETE /api/accounts/{account_id}?force=false
POST   /api/accounts/{account_id}/verify
POST   /api/accounts/{account_id}/default

GET /api/accounts/{account_id}/resources
    ?kind=created_favorite&offset=0&limit=20

GET /api/accounts/{account_id}/resources/{resource_id}/entries
    ?offset=0&limit=20
```

All routes use the existing server auth dependency. Return:

- `400` for malformed cookies or invalid pagination.
- `401` only for YTSage server authentication; do not overload it for platform login.
- `404` for unknown account/resource.
- `409` for duplicate account identity, protected deletion, or duplicate default transition conflicts.
- `422` for unsupported provider operations.
- `424 Failed Dependency` for invalid/expired platform credentials.
- `429` when the platform rate-limits the request.
- `502/503` for malformed or unavailable upstream responses.

Provider error responses should contain stable machine-readable codes, for example:

```json
{
  "detail": {
    "code": "account_login_invalid",
    "message": "The Bilibili login is no longer valid."
  }
}
```

Update the frontend API error parser to accept both existing string detail and typed detail.

## 7. Account Propagation Through Existing Workflows

### 7.1 Analysis

Add optional `account_id` to `AnalyzeRequest`.

Resolution order:

1. Explicit request `account_id`.
2. Default account matching the URL platform, if the user has enabled default-account use.
3. Existing legacy profile resolution.
4. Anonymous analysis.

For an explicit account:

- Verify that its platform matches the URL.
- Resolve its cookie path.
- Do not fallback to a legacy or different account when invalid.
- Return account metadata in analysis `raw` only as non-secret fields: `account_id`, label, login state.

To keep behavior predictable, the first release should use an explicit account selected by the frontend and avoid implicit default-account use in background operations except where the user deliberately chose a default.

### 7.2 Download task

Add optional `account_id` to `CreateTaskRequest` and deprecate client-controlled `cookie_file`.

Execution behavior:

- Resolve account credentials immediately before each yt-dlp process.
- A playlist item uses the parent task's account.
- Retry and resume retain the same `account_id`.
- Restart copies the same `account_id` into the new task.
- If the account is missing or invalid, fail with an account-specific status message and do not anonymously retry protected content.
- The existing YouTube no-cookie fallback must never run for Bilibili account-bound tasks.

Security hardening:

- Ignore or reject `cookie_file` from normal API clients after compatibility migration.
- If legacy persisted tasks contain `cookie_file`, accept only paths produced by the existing server profile resolver.
- Redact `cookie_file` and `account_id`-adjacent secrets from task logs; `account_id` itself is safe to display.

### 7.3 Playlist monitor

Add `account_id` to `PlaylistMonitorCreate` and `PlaylistMonitorResponse`, preferably as a dedicated database column.

Behavior:

- Monitor uniqueness becomes `(url, COALESCE(account_id, ''))`.
- Every scheduled analysis uses the bound account.
- New download tasks inherit the monitor account.
- Replacing account cookies repairs the monitor without editing it.
- Deleting an account with monitors requires either:
  - default behavior: `409` and list dependent monitor IDs; or
  - `force=true`: disable those monitors, store `last_error=account_removed`, then delete.
- Never silently bind dependent monitors to another account.

## 8. Frontend Information Architecture

### 8.1 Navigation

Add a first-class **Accounts** operational page rather than expanding the existing three fixed cookie tabs indefinitely.

Desktop layout:

- Left master list: account avatar/platform, label, display name or UID, login state, default marker.
- Right detail: identity summary, resource tabs, resource list, and account actions.

Mobile layout:

- Account list first.
- Selecting an account opens its detail as the next view with a back control.
- Resource entries use normal page scrolling; avoid nested scroll containers.

### 8.2 Account creation

Use a modal or focused detail form with:

- Platform selector, initially fixed to Bilibili.
- Account label.
- Cookie file chooser and paste area.
- "Verify and add" primary action.
- "Set as default" checkbox.

The UI must explain only necessary credential status. Do not expose raw cookie names or values after import.

Creation transaction:

1. Validate cookie syntax locally only for obvious empty/oversized input.
2. POST credentials to the server.
3. Server writes a temporary cookie file and verifies it.
4. On success, commit account metadata and cookie file.
5. On invalid login, either reject creation or create an invalid account only with an explicit user choice. Phase one should reject and preserve entered content in the form for correction.

### 8.3 Account detail

Header:

- Avatar, user display name, label, UID, VIP state.
- Login state and last verified time.
- Verify, edit label, replace credentials, set default, delete.

Resource tabs:

- Created favorites.
- Collected favorites.
- Watch later.
- Collections, once provider discovery is validated.

Resource rows:

- Cover thumbnail.
- Title and owner.
- Resource type/private marker.
- Item count and updated time.
- Open entries command.
- More menu with Download, Download and Monitor, Monitor only, and Open source.

### 8.4 Resource entry browser

Use the same selection conventions as the current workspace playlist table but with server pagination:

- Fetch the first page only when opened.
- Search only if the provider has a reliable server-side search; otherwise label it as current-page filtering or omit it.
- Support select current page and clear selection.
- Cross-page selection stores stable entry keys, not row indexes alone.
- A "Select all" action for a large favorite must not fetch all pages in the browser. It should create a server-side selection descriptor or be deferred. Phase one should support explicit page selections and a separate "Download entire resource" action.
- Downloading the entire resource should create a task from a server-resolved resource descriptor, not upload thousands of entries from the client.

This requires extending task creation with an optional source reference:

```python
class AccountResourceRef(BaseModel):
    account_id: str
    resource_id: str
    selection: Literal["all", "entries"]
    entry_ids: list[str] = []
```

For small explicit selections, the server resolves the selected stable IDs into current entry URLs. For `all`, a background preparation phase pages through the provider and progressively queues entries. Do not block an HTTP request while loading a large favorite.

### 8.5 Download workspace integration

Add an account selector near the URL input when the URL belongs to a supported platform:

- Anonymous/legacy credentials.
- Each matching account.
- Default account preselected when configured.

Changing account invalidates the current analysis result and requires re-analysis. Store only `account_id` in SPA workspace state.

When opening a resource from Accounts:

- Navigate to the download workspace with an account resource reference.
- Show the resource summary and selected count.
- Reuse format and advanced download options.
- Submit `account_id` and the resource selection descriptor.

### 8.6 Existing settings page

During transition:

- Keep Default and YouTube legacy cookie tabs.
- Replace the Bilibili fixed-profile editor with a link/action to Accounts once at least one account exists.
- Offer "Import existing credentials as an account" for current installations.
- Keep status terminology separated: cookie expiry and platform login validity.

## 9. Large Resource Processing

The current analyzer materializes all playlist entries. Account favorites can be much larger, so introduce a resource preparation path:

1. API validates account and resource reference.
2. Create task immediately with status `queued` and preparation status text.
3. Worker fetches provider pages sequentially.
4. Each page is normalized and appended to the persisted task options or a new `task_entries` table.
5. Worker downloads actual entry URLs one by one using existing per-entry logic.
6. Progress reports discovered count separately from completed count when upstream total is unknown.

Recommended scalable table:

```sql
CREATE TABLE task_entries (
    task_id TEXT NOT NULL,
    entry_key TEXT NOT NULL,
    position INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    error TEXT,
    PRIMARY KEY(task_id, entry_key),
    FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
);
CREATE INDEX idx_task_entries_position ON task_entries(task_id, position);
```

This table is preferable to placing thousands of entries into `options_json`, but it can be a second implementation increment. Phase one may impose a documented maximum (for example 500 entries) if task-entry persistence is not implemented yet.

## 10. Security and Privacy Requirements

- Require YTSage bearer authentication before exposing account APIs when the server has an auth token.
- Warn prominently in documentation that account management should not be exposed publicly without `YTSAGE_AUTH_TOKEN` and TLS at the reverse proxy.
- Never accept Bilibili passwords.
- Never render cookie content after submission.
- Never place credentials in URLs, query strings, task JSON returned to the frontend, exception traces, or WebSocket events.
- Sanitize upstream error payloads before returning them.
- Apply CSRF assumptions carefully: bearer token APIs are protected from ambient-cookie CSRF, but deployments without auth remain trusted-network only.
- Add request size limits to cookie imports.
- Rate-limit verify and resource-fetch actions per account in process; return a busy state for duplicate in-flight requests.
- Prevent SSRF by using provider-owned endpoint constants; clients submit opaque resource IDs, not arbitrary provider API URLs.
- Validate platform source URLs before handing them to yt-dlp.
- Treat account IDs as identifiers, not authorization boundaries. Server bearer auth protects all accounts.
- Treat a Douyin download proof as an ephemeral server capability: issue it only after a live target probe confirms formats with usable media URLs; bind it to the canonical single-video URL and selected account; expire and consume it once.
- Never persist a Douyin proof in browser `localStorage`, task options, database records, logs, WebSocket events, screenshots, or user-visible diagnostics. URL or account changes must discard the current analysis and proof.
- A proof authorizes only creation of the analyzed task. It is not a platform credential and must not be used to bypass signatures, CAPTCHA, device checks, or risk-control challenges.
- Document that Cookie exports grant the same content access as the browser session and should be revoked by logging out or rotating sessions if exposed.

## 11. Error and State Model

Stable account error codes:

```text
account_not_found
account_platform_mismatch
account_cookie_invalid
account_cookie_expired
account_login_invalid
account_login_unknown
account_duplicate_identity
account_in_use
resource_not_found
resource_private
provider_rate_limited
provider_unavailable
provider_response_invalid
```

Frontend states:

- `valid`: identity verified and login active.
- `expired`: static cookie inspection shows no usable cookie.
- `invalid`: provider explicitly reports not logged in.
- `unknown`: credential file is usable but provider verification failed due to network/upstream state.

Do not mark an account invalid on timeouts or 5xx responses. Preserve the previous valid identity and set state to unknown with `last_error`.

## 12. Testing Strategy

### 12.1 Unit tests

Account service:

- Create account and atomically persist normalized cookies.
- Reject malformed or oversized credentials.
- Set and transfer the platform default account.
- Reject duplicate labels and verified duplicate UIDs.
- Replace credentials while preserving account ID.
- Delete unused account and remove its cookie directory.
- Reject or force deletion with dependent monitors.
- Resolve only safe account cookie paths.

Bilibili provider:

- Parse valid navigation identity.
- Distinguish invalid login from network uncertainty.
- Parse created and collected favorite resources.
- Translate offset/limit to upstream pages correctly.
- Parse favorite entries and global indexes.
- Handle empty, private, deleted, rate-limited, and malformed responses.
- Ensure each request carries the selected cookie jar and no other account's credentials.

Analysis/download:

- Explicit account overrides legacy profile.
- Platform mismatch is rejected.
- Account-bound playlist items retain account credentials.
- Resume/retry/restart retain `account_id`.
- Missing/deleted account fails explicitly.
- Legacy tasks continue to execute.

Monitors:

- Same URL can be monitored by two accounts.
- Same URL and account remains unique.
- Checks and generated tasks use the bound account.
- Replaced credentials are picked up on next check.
- Forced account deletion disables dependent monitors.

### 12.2 API tests

- CRUD, verification, default transitions, and pagination.
- Typed error response compatibility.
- Bearer authentication on all account endpoints.
- Cookie content absent from every response.
- Resource IDs cannot trigger arbitrary outbound URLs.
- Pagination bounds and invalid account/resource handling.

### 12.3 Frontend tests

- Account list loading only on the Accounts route.
- Selecting an account loads resources; selecting a resource loads only its requested page.
- Account creation, replacement, verification, default, and deletion states.
- Long account/resource lists on desktop and mobile without nested scrolling regressions.
- Cross-page entry selection behavior.
- Account selector invalidates stale URL analysis.
- Resource download submits the right account and stable entry IDs.
- Invalid login guides users to replace credentials without losing navigation context.

### 12.4 Integration fixtures

Do not commit real cookies. Use mocked HTTP responses with redacted representative fixtures. Add an opt-in manual test script that reads a cookie path from an environment variable and never prints it.

Manual acceptance matrix:

- Windows mise development.
- Docker with `/config` volume and UID 10001.
- One Bilibili account.
- Two distinct Bilibili accounts.
- Private favorite owned by one account.
- Public favorite accessed anonymously and with an account.
- Account cookie replacement while a monitor exists.
- Server restart with queued account-bound task.
- Mobile 390px and desktop 1440px layouts.

## 13. Delivery Phases

### Phase 0: Provider contract spike

Deliverables:

- Mocked and opt-in live probes for identity, favorites, favorite entries, and watch later.
- Confirm current endpoint fields, pagination, private-resource behavior, and rate-limit responses.
- Record only normalized fixtures with all identity and cookie data redacted.

Exit criteria:

- Two separate accounts can return different identity and private resource results.
- Favorite entry URLs are stable enough for existing per-item downloader.
- No WBI signing is required for phase-one operations, or signing work is explicitly scoped.

### Phase 1: Account foundation

Deliverables:

- Schema migration mechanism.
- Account models, storage, service, provider registry, CRUD router.
- Account-scoped credential files and atomic writes.
- Bilibili identity verification.
- API and unit tests.

Exit criteria:

- Multiple accounts can coexist, verify, be made default, update cookies, and be removed safely.
- No API or logs expose cookie content.
- Legacy cookie profiles remain unchanged.

### Phase 2: Account-aware analysis and downloads

Deliverables:

- `account_id` in analysis and task contracts.
- Safe account resolution in analyzer and executor.
- Douyin Cookie import plus account-aware single-video analysis and download.
- A short-lived, single-use `douyin_download_proof`, returned only when the live analysis found real formats with usable media URLs and bound to the canonical URL plus selected account.
- Frontend-only in-memory proof forwarding; URL/account changes invalidate analysis, and proof errors require re-analysis without creating a task.
- Distinct actionable errors for fresh cookies, provider risk control, timeout, and provider unavailability; only an explicit invalid-login result may be described as invalid login.
- Retry, resume, restart, and WebSocket response compatibility.
- Legacy task compatibility tests.

Live-probe conclusion:

- Douyin's identity endpoint can be risk-controlled independently of media extraction, so `unknown` identity is not evidence that login is invalid and is not a downloadability verdict.
- Target downloadability is established separately by a bounded yt-dlp probe of the requested single video. Metadata-only responses and formats without usable URLs do not produce a proof.
- The single-video download proof does not depend on browser automation and does not attempt signature, CAPTCHA, device-check, or risk-control bypasses; account library browsing separately uses Playwright Chromium to observe first-party page responses.
- Douyin works, saved videos, collection folders, and folder entries are available through isolated account browser contexts; bulk/playlist tasks, monitoring, browser/QR login, and automatic renewal remain deferred.

Exit criteria:

- The chosen account is used for every item of a playlist task.
- A new Douyin task is accepted only with an unexpired proof matching its canonical URL and account, and that proof cannot be replayed. Resume continues the already-authorized task; restart and history redownload require a new analysis.
- URL or account changes prevent stale proof submission; no proof appears in durable client or server state.
- Replacing credentials repairs subsequent attempts.
- Explicit account failures never silently fall back.

### Phase 3: Bilibili library APIs

Deliverables:

- Resource list and entry list endpoints.
- Created favorites, collected favorites, and watch later.
- Server-side pagination and provider error mapping.
- Bounded retry and duplicate in-flight request handling.

Exit criteria:

- No account route fetches all favorite entries unless explicitly processing an entire resource in a worker.
- Private favorites are visible only with their owner account.
- Deleted/unavailable videos do not corrupt pagination or selection keys.

### Phase 4: Accounts UI

Deliverables:

- Accounts navigation and master-detail page.
- Add, verify, replace, default, and delete workflows.
- Resource tabs and paginated entry browser.
- Download workspace account selector.
- Mobile layout and i18n.

Exit criteria:

- Common flow is: add account, open favorite, select entries, choose format, download.
- Page transitions retain selected account and resource state during the SPA session.
- No large resource or ephemeral download proof is stored in `localStorage`.

### Phase 5: Account-aware monitoring

Deliverables:

- Monitor schema migration and account binding.
- `(url, account_id)` uniqueness.
- Resource "Download and monitor" action.
- Account deletion dependency handling.
- Existing monitor migration and tests.

Exit criteria:

- Two accounts can independently monitor the same source.
- New entries download with the correct account.
- Deleted/invalid accounts produce visible paused monitor states.

### Phase 6: Scale hardening

Deliverables:

- `task_entries` persistence or a documented bounded alternative.
- Background resource preparation.
- Large favorite progress states.
- Query and index review.

Exit criteria:

- A resource with thousands of entries does not create an oversized HTTP response, browser state object, or task JSON record.
- Server restart resumes discovery/download without duplicating completed entries.

## 14. Commit Strategy

Keep changes reviewable:

1. `feat: add platform account persistence`
2. `feat: add bilibili account provider`
3. `feat: bind analysis and downloads to accounts`
4. `feat: expose account library resources`
5. `feat: add account management workspace`
6. `feat: bind playlist monitors to accounts`
7. `feat: persist large playlist task entries`
8. `docs: document account credential security`

Each commit should pass backend tests, frontend type checking where applicable, and `git diff --check`.

## 15. Rollout and Compatibility

- Keep account functionality additive and disabled until an account is created.
- Existing API clients can omit `account_id`.
- Existing fixed cookie APIs remain available for at least one release.
- Existing tasks need no rewrite because options JSON accepts absent fields.
- Existing monitors migrate with `account_id = NULL` and retain legacy analysis behavior.
- Surface database migration failures at startup and do not run against a partially migrated schema.
- Before release, update README and Chinese translation with backup, token, TLS, and Cookie security guidance.
- Docker image must create or write `/config/accounts` as UID 10001 through the existing permissions setup.

## 16. Rollback Plan

Code rollback:

- New account and monitor columns are additive; older code ignores the account table and nullable monitor column.
- Do not delete legacy cookie files during rollout, allowing immediate return to fixed profiles.
- Account cookie directories can remain inert during rollback.

Data rollback:

- Stop the service.
- Back up `ytsage_server.db` and `/config/accounts`.
- Revert application image/version.
- Existing legacy-profile tasks and monitors continue as before.
- Account-bound tasks created by the new version may fail under old code if they rely only on `account_id`; document that these should be paused before rollback or recreated after restoring the new version.

## 17. Acceptance Criteria

The feature is complete when all statements below are true:

- At least two Bilibili accounts can be stored and independently verified.
- Account A cannot see Account B's private favorite through accidental credential reuse.
- Created favorites, collected favorites, and watch later load on demand with bounded pages.
- A user can download selected favorite entries and an entire favorite.
- Account choice survives analysis, creation, execution, retry, resume, restart, and server restart.
- A user can download a favorite now and monitor it for future additions.
- Updating an account's cookies repairs its monitors without recreating them.
- Removing an in-use account is blocked or explicitly disables dependents.
- Existing installations using fixed cookie profiles continue to analyze and download.
- API responses, WebSocket events, task options shown to clients, logs, and error messages contain no cookie secrets.
- Backend tests, frontend build, responsive browser checks, and Docker volume-permission checks pass.

## 18. Open Decisions Before Implementation

Resolve these at the end of Phase 0:

1. Whether invalid cookies should prevent account creation or allow an unverified account record. Recommended: prevent creation, allow later valid accounts to become invalid.
2. Whether default accounts are selected automatically for pasted URLs. Recommended: yes in the UI, but submit the selected `account_id` explicitly.
3. Whether phase one supports "download entire favorite" above a bounded item count. Recommended: implement background preparation or cap at 500 until `task_entries` exists.
4. Whether account deletion should support force in the first release. Recommended: block deletion and present dependent monitors/tasks; add force after dependency UI exists.
5. Whether collections discovery ships with favorites. Recommended: ship favorites and watch later first; add collection discovery only after live endpoint validation.
6. Whether legacy Bilibili credentials are imported automatically. Recommended: explicit one-click import, never automatic movement or deletion.

## 19. Recommended First Milestone

Implement Phases 0 through 3 as the backend milestone before building the final UI. This establishes the security and workflow contracts early and avoids coupling the interface to unstable platform response shapes.

The first demonstrable vertical slice should be:

1. Import two Bilibili Cookie exports as separate accounts.
2. Verify and display both identities.
3. List the selected account's created favorites.
4. Open one favorite and request one page of entries.
5. Create a download task for selected entries with `account_id`.
6. Confirm every yt-dlp child process uses that account's current Cookie file.
