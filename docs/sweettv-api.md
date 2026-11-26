# SWEET.TV API Specification

Sanitized contract for `https://api.sweet.tv/` as consumed by `device/files/usr/local/lib/media-stick/mediastick_sweetapi.py` and `device/skin-overlay/plugin.video.sweettv/resources/lib/sweettv.py`.

Machine-readable type schemas live in [`docs/sweettv-api-shapes.json`](sweettv-api-shapes.json) (stamped with `captured_at`, checked by `python3 tools/sweettv-api-spec.py --check`, and refreshed only on demand via `--refresh` when `captured_at` is older than 30 days or an upstream field contract fails).

## Transport & Headers

- Base URL: `https://api.sweet.tv/`
- Method: `POST` with JSON body (`8 s` timeout, `60 s` response cache in `Client`, `600 s` in-memory cache for `GetConfiguration`).
- Required headers (`mediastick_sweetapi.HEADERS`):
  - `user-agent`, `origin` (`https://sweet.tv`), `referer` (`https://sweet.tv/`)
  - `content-type` (`application/json`), `accept` (`application/json`)
  - `x-device` (`1;22;0;2;<ADDON_VERSION>`)
  - `accept-language` (device language code: `ru`, `uk`, `en`, ...)
  - HTTP `authorization` header read from the add-on's `settings.xml` at call time (never logged, cached, or persisted to SQLite/docs).
- A `401` re-reads `settings.xml` once and retries if the value changed; `401`/`403` returns `error: "auth"`.
- Non-`"OK"` `status` strings map to `error: "service"`.

## Semantic Pitfalls (Verified)

1. **Hero vs. card artwork (`banner_url` vs. `horizontal_poster_url`)**:
   - `banner_url` (`1280x720`) is a clean wide hero backdrop without overlaid text.
   - `horizontal_poster_url` (`478x267`) is a smaller card image often stamped with promotional/title text.
   - URLs containing `/cdn-cgi/image/<params>/<target>` are Cloudflare resize proxies; `_hq_url()` strips that prefix to recover full-resolution art.
2. **Bulk `channelList.json` / `GetChannels` vs. `TvService/GetEpgRecords.json`**:
   - Bulk `channelList.json` / `TvService/GetChannels.json` responses carry **0 EPG previews** (`preview_url` / `preview_url_ext` are absent on bulk guide syncs).
   - `TvService/GetEpgRecords.json` returns `image_url` (`epg_horizontal`), `preview_url_ext`, `preview_url`, and the full `text` programme title (single-channel `GetChannels` day queries can also return `preview_url` / `preview_url_ext`).
3. **Unreleased episodes in `MovieService/GetMovieInfo.json`**:
   - Unreleased episodes arrive with `duration == 0`, `file_size == "0"`, a `playable_episode_ids` list on the movie/series object, no release date, and resolve to a ~65 s promotional HLS stub if played.
4. **Config labels in `MovieService/GetConfiguration.json`**:
   - `GetConfiguration` uses `title` on live responses (and `name` as fallback in older/fixture payloads) for `genres`, `sort_modes`, and `countries`; items with blank or missing labels must be filtered out.
   - `GetMovieInfo` returns numeric country IDs when `need_extended_info: true`, which map via `GetConfiguration.countries` (while legacy/fixture payloads may already hold string country names).
5. **64-bit IDs & timestamps as int or string**:
   - Programme/channel `id`, `sub_id`, `channel_id`, `tv_show_id`, `time_start`, and `time_stop` may arrive as either JSON integers or decimal strings (`_num()` / `_id()` / `_time()` normalize both).
6. **TVOD & 4K UHD filtering**:
   - `availability_info.available == false` (or `available == false`) marks paid TVOD / unavailable items to filter out.
   - Genre `57` (`UHD_GENRE`) on movies and category `24` (`UHD_CATEGORY`) or `"ultra hd"` in `genres` on channels mark 4K UHD content, which is hidden unless `quality == "unlimited"` (Pi 3B+ H.264 1080p cap).
7. **Never persist `watch_info` or stream URLs**:
   - `GetMovieInfo` `watch_info` is ignored; local resume and favourites come strictly from `StateStore` / `mediastick_resume`.
   - `GetLink` responses (`http_stream.url`, `license_url`) are strictly uncached and never written to SQLite or logs.

---

## Endpoints

### `TvService/GetChannels.json`

Used in two forms:
- **Full channel list sync** (add-on `refreshChannelList()`): omits `channels`, sets `epg_limit_prev: 10`, `epg_limit_next: 100`, `need_categories: true`.
- **Single-channel day guide** (`mediastick_sweetapi.day_body()`): sets `channels: [cid]`, `epg_current_time: <unix>`, `epg_limit_prev: 30`, `epg_limit_next: 30`, `need_categories: false` (retried up to `DAY_EXTEND = 2` times each way for busy days).

Request fields:
- `channels`: `list[int]` (optional; single channel ID for day queries)
- `epg_current_time`: `int` (unix seconds)
- `epg_limit_prev`, `epg_limit_next`: `int`
- `need_epg`, `need_list`, `need_categories`, `need_offsets`, `need_hash`, `need_icons`, `need_big_icons`: `bool`

Response tree:
- `status`: `str` (`"OK"`)
- `categories[]`: `{id: int, caption: str, name: str, order: int}` (`id == 1000` is synthetic "All")
- `list[]`: `{id: int, name: str, slug: str, number: int, icon_url: str, icon_v2_url: str, banner_url: str, category: list[int], catchup: bool, catchup_duration: int, epg_days_past: int, epg_days_future: int, available: bool, available_without_auth: bool, live_blackout: bool, is_fast_channel: bool, epg: list[object]}`
- `list[].epg[]`: `{id: int|str, text: str, time_start: int|str, time_stop: int|str, available: bool, tv_show_id: int|str, season_number: int, episode_number: int, description: str, text_description: str, image_url: str, preview_url: str, preview_url_ext: str, external_id: str, is_downloadable: bool}`

### `TvService/GetEpgRecords.json`

Fetches rich EPG records (artwork + full metadata) for IDs referenced by `GetCollectionInfo.secondary_id_list`.

Request fields:
- `id_list`: `list[int]`
- `image_type`: `int` (`0`)
- `need_extended_info`: `bool` (`true`)

Response tree:
- `status`: `str`
- `epg_records[]` (or `list[]`): `{id: int|str, channel_id: int|str, text: str, time_start: int|str, time_stop: int|str, available: bool, tv_show_id: int|str, season_number: int, episode_number: int, description: str, image_url: str, epg_horizontal: str, preview_url: str, preview_url_ext: str}`

### `MovieService/GetConfiguration.json`

Returns catalog taxonomy (`genres`, `sort_modes`, `countries`), cached in memory for `CONFIG_TTL = 600` s.

Request fields: `{}`

Response tree:
- `status`: `str`
- `genres[]`: `{id: int, title: str, name: str}` (`1` = Series, `3` = Shows, `57` = Ultra HD, `61` = All Movies)
- `sort_modes[]`: `{id: int, title: str, name: str}` (supported IDs: `1, 2, 3, 5, 6`)
- `countries[]`: `{id: int|str, title: str, name: str}`

### `MovieService/GetCollections.json`

Returns curated collections for Series (`type: 3`) or Shows/mixed (`type: 7`).

Request fields:
- `type`: `int` (`3` or `7`)

Response tree:
- `status`: `str`
- `collection[]` (or `collections[]`): `{id: int, type: str, title: str, id_list: list[int]}`
  - `type == "Movie"`: `id_list` contains `movie_id`s for `GetMovieInfo`.
  - `type == "Epg"`: `id` is a `collection_id` for `GetCollectionInfo` (ignore `id_list` and `title` promo slogans).

### `MovieService/GetCollectionInfo.json`

Resolves EPG show collections into titles, artwork, and `secondary_id_list` (`epg_id`s).

Request fields:
- `id_list`: `list[int]`
- `need_translations`: `bool` (`true`)

Response tree:
- `status`: `str`
- `collections[]` (or `collection[]`): `{id: int, title: str, description: str, age_limit: str, age_rating: str, poster_url: str, banner_url: str, horizontal_poster_url: str, posters: [{orientation: str, poster_url: str, original_poster_url: str}], secondary_id_list: list[int]}`

### `MovieService/GetGenreMovies.json`

Returns ordered `movie_id` integers for a genre (genre `61` includes `1` and `3`, so movies view excludes those).

Request fields:
- `genre_id`: `int`

Response tree:
- `status`: `str`
- `movies`: `list[int]`

### `MovieService/GetMovieInfo.json`

Fetches catalog cards (`need_extended_info: false`, paginated with `limit`/`offset`/`sort_mode_id`) or full movie/series detail with seasons & episodes (`need_extended_info: true`).

Request fields:
- `movies`: `list[int]`
- `limit`, `offset`, `sort_mode_id`: `int` (optional, catalog slice)
- `need_extended_info`: `bool`

Response tree:
- `status`: `str`
- `movies[]`: `{id: int, title: str, description: str, year: int, duration: int, file_size: str, rating_imdb: float, age_limit: str, age_rating: str, genres: list[int], countries: list[int|str], poster_url: str, original_poster_url: str, banner_url: str, original_banner_url: str, horizontal_poster_url: str, external_id_pairs: [{owner_id: int, preferred: bool}], owners: list[int], available: bool, availability_info: {available: bool}, watch_info: {position: int}, playable_episode_ids: list[int], seasons: [{id: int, number: int, title: str, owner_id: int, episodes: [{id: int, number: int, title: str, duration: int, file_size: str, preview_url: str, image_url: str, available: bool}]}]}`

### `MovieService/GetLink.json`

Resolves a playable VOD stream URL (HLS or Widevine MPEG-DASH). Strictly uncached.

Request fields:
- `movie_id`: `int`
- `owner_id`: `int` (from `external_id_pairs` preferred/first, else `owners[0]`)
- `video_quality_id`: `int` (`1` = 720p, `2` = 1080p, `3` = unlimited/4K)
- `audio_track`: `int` (`-1`)
- `preferred_link_type`: `int` (`0`)
- `subtitle`: `str` (`"all"`)
- `episode_id`: `int` (optional, for series episodes)

Response tree:
- `status`: `str`
- `scheme`: `str` (`"HTTP_HLS"` or `"HTTP_DASH"`)
- `license_url`: `str`
- `http_stream`: `{host: {address: str}, url: str}` (either absolute `https://` URL or path joined to `https://{host.address}{url}`)

### `SearchService/Search.json`

Searches programmes, channels, movies/series, and people (`MIN_NEEDLE = 2`, `MAX_NEEDLE = 100`).

Request fields:
- `needle`: `str`

Response tree:
- `status`: `str`
- `result[]`: `{type: str, id: int|str, sub_id: int|str, tv_show_id: int|str, text: str, subtext: str, slug: str, time_start: int|str, time_stop: int|str, image_url: str, genres: list[int], category: list[int], categories: list[int], is_serial: bool, seasons_count: int, available: bool, availability_info: {available: bool}}`
  - `type` values: `"EpgRecord"` (`sub_id` is channel ID), `"Channel"`, `"Movie"`, `"Person"`.

### `SearchService/GetTop.json`

Returns trending search items (movies and channels).

Request fields: `{}`

Response tree:
- `status`: `str`
- `result[]`: `{type: str, id: int|str, text: str, year: int, genres: str|list, category: list[int], image_url: str, availability_info: {available: bool}}`
  - Note: `genres` may be either a display `str` (e.g. `"Ultra HD"`) or `list[int]` (e.g. `[57]`).
