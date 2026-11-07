# Playback preferences

`GET /api/v1/users/me` and the existing `PATCH /api/v1/users/me` expose:

| Field | Default | Meaning |
| --- | --- | --- |
| `preferred_audio_language` | `null` | Prefer this language; otherwise use the default/first audio track. |
| `preferred_subtitle_language` | `null` | Prefer this language within the tracks allowed by subtitle mode. |
| `subtitle_mode` | `off` | `off`, `forced` (forced tracks only), or `always` (all subtitle tracks). |

Language preferences accept ISO two/three-letter codes and region tags. Matching treats ISO639 aliases and region variants as the same language, for example `fr`, `fra`, `fre`, and `fr-CA`. Stored codes retain their supplied form after trimming and lowercasing. An unavailable preferred language falls back to a default track, then the lowest stream index. Forced mode never falls back to a non-forced track. No tracks means no selection.

Initial `playback-info` or `start-stream` requests omit `AudioStreamIndex` and `SubtitleStreamIndex` to resolve the saved preferences. Explicit indexes take priority; `SubtitleStreamIndex: -1` explicitly disables subtitles, including when the saved mode is enabled. Invalid explicit indexes return 422.

`StreamInfo` returns the resolved indexes, `SubtitleDeliveryMethod` (`External`, `Encode`, or null), and `SubtitleUrl` for external WebVTT. A preferred non-default audio track is remuxed to avoid silently playing the native file's default audio. Image subtitles require full transcoding and are passed to FFmpeg's overlay filter; if transcoding is disabled, no compatible plan is returned.

Clients apply the resolved indexes once when opening playback, then send those explicit indexes on subsequent negotiations. Use `-1` for a resolved/manual subtitle-off selection. Updating account preferences changes future automatic selections; it does not restart or mutate an active playback session. Media URLs still require that playback session's scoped grant.

`start-stream` additionally returns optional `subtitle_stream_index` (string), `subtitle_delivery_method`, and `subtitle_url` metadata alongside its existing streaming result. Clients using the lower-level HLS endpoints pass the already resolved audio and burned-subtitle indexes explicitly.

WebVTT extraction has a 30-second deadline, including time waiting for the same target's extraction. Concurrent requests share the completed cache through a process-local lock. FFmpeg writes a temporary file, which is atomically published only after a successful exit and a valid WebVTT header; cancellation and timeout kill and reap the child. The cache key includes the source path, actual size and nanosecond modification time so replacements do not reuse old subtitles. The versioned cache ignores legacy partial files.
