# Installation-support file transfers

The managed MCP, JSON HTTP and CLI interfaces can stage and read installation
packages, support scripts and notes without using another application's code
execution endpoint. Uploaded bytes are never executed, extracted, installed,
registered as a release or copied to an application/configuration destination.
Normal installation/update still requires its reviewed repository catalog and
digest-checked recipe. Production media belongs to its owning application or a
separate production file service.

## Storage and access

There is exactly one root, `installation-transfers`, below the configured
manager state: `<helper_state_directory>/transfers/`. Default bootstrap storage
is `/var/lib/flamoris-updater/helper/transfers/`. Each caller-selected canonical
UUID has one fixed `payload` file. `file_name` is display/download metadata, not
a destination or an executable path. The list result reports the actual storage
directory for the operator. No tool accepts an absolute/relative server path,
URL, command, target directory, file mode or arbitrary existing file reference.

The root and UUID directories are private to the manager (0700); payloads are
0600 while receiving and 0400 after verification. Links, hardlinks, special
files, permissive modes and symbolic path ancestors are rejected. Release
removes only that transfer's known payload and empty directory, never an
unexpected extra member or a recursive external tree.

This uses Updater's existing access contract: anyone reaching the configured
endpoint has the same operations and can list/read its staged transfers. UUIDs
are references, not authentication. No new login/token/grant requirement is
introduced. The existing loopback/Host/Origin, byte limits and OS-peer manager
boundary remain. Do not upload passwords, signing keys, credential-bearing
configuration or production secrets. Transfers provide no per-user isolation.

## Limits

| Limit | Value |
| --- | --- |
| One file | 1 GiB, including zero-byte files |
| One decoded read/write chunk | 128 KiB |
| Outstanding reservations, including incomplete/failed transfers | 4 GiB and 128 files |
| Free-space reserve | 256 MiB; admission also reserves declared outstanding bytes |
| List page | 1–100 records, default 25 |

Limits are returned by `updater_transfers_list`. Admission reserves the declared
size before creating the payload. Releasing a staged copy frees its reservation;
its receipt remains as a tombstone so the same ID cannot be rebound. Existing
installer packages, app state and retained releases are outside this root and
quota. No expiry, automatic deletion or archive expansion is performed.

## Shared tool contract

| Tool | Input | Result / effect |
| --- | --- | --- |
| `updater_transfers_list` | Optional `cursor`, `limit` | Root, limits, usage, non-released receipts and next cursor |
| `updater_transfer_begin` | `transfer_id`, `application_id`, `file_name`, `size_bytes`, `sha256` | Reserve one immutable upload binding |
| `updater_transfer_write` | `transfer_id`, `offset`, `data_base64`, `chunk_sha256` | Append the next checked chunk |
| `updater_transfer_finish` | `transfer_id` | Check complete length/SHA-256 and seal the payload |
| `updater_transfer_get` | `transfer_id` | Recorded phase, confirmed received bytes and pending chunk binding |
| `updater_transfer_read` | `transfer_id`, optional `offset`, `length` | Base64 bytes, chunk/file digests and EOF; verified payloads only |
| `updater_transfer_release` | `transfer_id`, `sha256` | Explicitly release only the staged copy; exact retries are safe |

All digests use `sha256:` followed by 64 lowercase hexadecimal characters.
Offsets/sizes are strict JSON integers. `application_id` labels the intended
installation work; it does not grant installation authority or permit access to
the application's real files. Identical filenames may be staged under different
UUIDs; there is no overwrite-by-name operation.

The phases are `allocating`, `receiving`, `ready`, `mismatch`, `releasing` and
`released`. Metadata and effect intents persist in the existing v1 journal; no
journal schema migration is required. `get` reports recorded state; `read` and
repeated `finish` additionally reject a changed sealed-file fingerprint.

## Transfer and reconnect

1. Calculate full size/SHA-256 locally and choose a new UUID. Begin with the
   intended application and filename. Reusing that ID with different metadata
   fails; retrying identical metadata returns its recorded state.
2. Send sequential chunks with their hashes. Inspect `received_bytes` after a
   lost response. Retrying the identical last or pending chunk does not append
   it twice. A pending intent binds its offset, length and digest before writing;
   an interrupted partial write can continue only with that exact chunk after
   checking its existing prefix. Changed/out-of-order retries are rejected.
3. Finish only after every chunk is confirmed. Digest mismatch retains evidence
   and quota until explicit release. Finish grants no execution/install action.
4. Read verified chunks, check their digests and assemble/verify the final size
   and whole-file digest. Never infer complete download from one chunk.
5. Release with the original whole-file digest when the staged copy is no longer
   needed. Retain the transfer ID for inspecting a lost release response.

Known active or unresolved Updater self-update jobs block transfer mutations;
metadata inspection and reads remain available. An interrupted request is not
an instruction to re-execute a script or installation. Follow its transfer
receipt and exact retry contract.

CLI uses the existing generic `flamoris-updater call --tool <name> --arguments
<JSON file>` operation; HTTP uses `/api/v1/tools/<name>` and MCP advertises the
same strict schemas. Configured public path prefixes work unchanged. There is
no separate upload Web page in this implementation. Publication, deployment,
external-client tool discovery and physical-host acceptance remain separate.

**日本語:** インストール補助ファイルの受け渡し専用です。MCPから保存先パスを
指定せず、転送IDで分割送受信します。保存後の実行・展開・アプリ配置は行いません。
既定の保存先は管理サービス領域内の `helper/transfers/` で、制作ファイルや既存の
設定・秘密情報を一般ファイル操作で公開する機能ではありません。
