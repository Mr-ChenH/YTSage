"""Authenticated Bilibili account and library access."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from ..analyzers.bilibili import _json_response, _load_cookie_jar, as_dict_list, as_float, as_int, as_str
from ..models import AccountResource, AccountResourceEntriesResponse, AccountResourceListResponse, PageInfo, PlatformAccount, PlaylistEntry

_API = "https://api.bilibili.com"
_AVATAR_HOST_SUFFIXES = (".hdslb.com", ".biliimg.com")
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
    "Referer": "https://www.bilibili.com/",
}


class BilibiliProviderError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class BilibiliIdentity:
    external_id: str
    display_name: str
    avatar_url: str | None
    vip_type: int | None


def normalize_image_url(value: Any) -> str | None:
    url = as_str(value)
    if not url:
        return None
    if url.startswith("//"):
        return f"https:{url}"
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme == "http" and any(host.endswith(suffix) for suffix in _AVATAR_HOST_SUFFIXES):
        return f"https://{parsed.netloc}{parsed.path}" + (f"?{parsed.query}" if parsed.query else "")
    return url


class BilibiliProvider:
    platform = "bilibili"

    def __init__(self, timeout: int = 15, http: Any = requests) -> None:
        self.timeout = timeout
        self.http = http

    def _get(self, cookie_file: Path, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            response = self.http.get(
                f"{_API}{path}", params=params, headers=_HEADERS,
                cookies=_load_cookie_jar(cookie_file), timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise BilibiliProviderError("provider_unavailable", "Bilibili is currently unavailable.", 503) from exc
        if response.status_code == 403:
            raise BilibiliProviderError("resource_private", "This Bilibili resource is unavailable to the selected account.", 403)
        if response.status_code == 429:
            raise BilibiliProviderError("provider_rate_limited", "Bilibili temporarily rate-limited this account.", 429)
        if response.status_code >= 500:
            raise BilibiliProviderError("provider_unavailable", "Bilibili is currently unavailable.", 503)
        payload = _json_response(response)
        if not isinstance(payload, dict):
            raise BilibiliProviderError("provider_response_invalid", "Bilibili returned an invalid response.")
        code = as_int(payload.get("code")) or 0
        if code == -101:
            raise BilibiliProviderError("account_login_invalid", "The Bilibili login is no longer valid.", 424)
        if code in {-403, 11010}:
            raise BilibiliProviderError("resource_private", "This Bilibili resource is unavailable to the selected account.", 403)
        if code != 0:
            raise BilibiliProviderError("provider_response_invalid", as_str(payload.get("message")) or f"Bilibili error {code}.", 400 if code == -400 else 502)
        return payload

    def verify(self, cookie_file: Path) -> BilibiliIdentity:
        payload = self._get(cookie_file, "/x/web-interface/nav")
        data = payload.get("data")
        if not isinstance(data, dict) or data.get("isLogin") is not True:
            raise BilibiliProviderError("account_login_invalid", "The Bilibili login is no longer valid.", 424)
        mid = as_str(data.get("mid"))
        name = as_str(data.get("uname"))
        if not mid or not name:
            raise BilibiliProviderError("provider_response_invalid", "Bilibili returned incomplete account identity data.")
        vip = data.get("vipType")
        if vip is None:
            vip = (data.get("vip") or {}).get("type") if isinstance(data.get("vip"), dict) else None
        return BilibiliIdentity(mid, name, normalize_image_url(data.get("face")), as_int(vip))

    def list_resources(self, account: PlatformAccount, cookie_file: Path, kind: str, offset: int, limit: int) -> AccountResourceListResponse:
        if not account.external_id:
            raise BilibiliProviderError("account_login_invalid", "Verify this account before browsing its library.", 424)
        if kind == "created_favorite":
            payload = self._get(cookie_file, "/x/v3/fav/folder/created/list-all", params={"up_mid": account.external_id, "type": 2})
            if not isinstance(payload.get("data"), dict):
                raise BilibiliProviderError("account_login_invalid", "The Bilibili login is no longer valid.", 424)
            data = payload["data"]
            raw_items = as_dict_list(data.get("list"))
            total = as_int(data.get("count")) or len(raw_items)
            items = [self._favorite_resource(account, item, "created_favorite") for item in raw_items[offset : offset + limit]]
        elif kind == "collected_favorite":
            page_number = offset // limit + 1
            payload = self._get(cookie_file, "/x/v3/fav/folder/collected/list", params={"up_mid": account.external_id, "pn": page_number, "ps": limit, "platform": "web"})
            data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
            raw_items = as_dict_list(data.get("list"))
            total = as_int(data.get("count")) or as_int(data.get("total")) or offset + len(raw_items)
            items = [self._favorite_resource(account, item, "collected_favorite") for item in raw_items]
        elif kind == "collection":
            page_number = offset // limit + 1
            payload = self._get(cookie_file, "/x/polymer/web-space/seasons_series_list", params={"mid": account.external_id, "page_num": page_number, "page_size": limit})
            data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
            lists = data.get("items_lists") if isinstance(data.get("items_lists"), dict) else {}
            page = lists.get("page") if isinstance(lists.get("page"), dict) else {}
            items = [
                *(self._collection_resource(account, item, "collection") for item in as_dict_list(lists.get("seasons_list"))),
                *(self._collection_resource(account, item, "series") for item in as_dict_list(lists.get("series_list"))),
            ]
            total = as_int(page.get("total")) or offset + len(items)
        elif kind == "watch_later":
            payload = self._get(cookie_file, "/x/v2/history/toview/web", params={"jsonp": "jsonp"})
            data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
            raw_items = as_dict_list(data.get("list"))
            total = len(raw_items)
            items = [self._watch_later_resource(account, total)] if offset == 0 and total else []
            total = 1 if total else 0
        else:
            raise BilibiliProviderError("resource_not_found", "Unsupported Bilibili library type.", 404)
        return AccountResourceListResponse(items=items, page=PageInfo(offset=offset, limit=limit, total=total, has_more=offset + len(items) < total))

    def list_entries(self, account: PlatformAccount, cookie_file: Path, resource_id: str, offset: int, limit: int) -> AccountResourceEntriesResponse:
        try:
            kind, external_id = resource_id.split(":", 1)
        except ValueError as exc:
            raise BilibiliProviderError("resource_not_found", "Invalid Bilibili resource identifier.", 404) from exc
        if kind in {"created_favorite", "collected_favorite"}:
            page_number = offset // limit + 1
            payload = self._get(cookie_file, "/x/v3/fav/resource/list", params={"media_id": external_id, "pn": page_number, "ps": limit, "platform": "web"})
            data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
            info = data.get("info") if isinstance(data.get("info"), dict) else {}
            medias = as_dict_list(data.get("medias"))
            total = as_int(info.get("media_count")) or offset + len(medias)
            resource = self._favorite_resource(account, {**info, "id": external_id}, kind)
            entries = [self._favorite_entry(item, offset + index + 1) for index, item in enumerate(medias)]
        elif kind in {"collection", "series"}:
            if kind == "collection":
                path = "/x/polymer/web-space/seasons_archives_list"
                params = {"mid": account.external_id, "season_id": external_id, "page_num": offset // limit + 1, "page_size": limit}
            else:
                path = "/x/series/archives"
                params = {"mid": account.external_id, "series_id": external_id, "pn": offset // limit + 1, "ps": limit}
            payload = self._get(cookie_file, path, params=params)
            data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
            medias = as_dict_list(data.get("archives"))
            page = data.get("page") if isinstance(data.get("page"), dict) else {}
            total = as_int(page.get("total")) or offset + len(medias)
            meta = data.get("meta") if isinstance(data.get("meta"), dict) else {"season_id" if kind == "collection" else "series_id": external_id, "total": total}
            resource = self._collection_resource(account, {"meta": meta}, kind)
            entries = [self._entry(item, offset + index + 1) for index, item in enumerate(medias)]
        elif kind == "watch_later":
            payload = self._get(cookie_file, "/x/v2/history/toview/web", params={"jsonp": "jsonp"})
            data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
            medias = as_dict_list(data.get("list"))
            total = len(medias)
            resource = self._watch_later_resource(account, total)
            entries = [self._entry(item, offset + index + 1) for index, item in enumerate(medias[offset : offset + limit])]
        else:
            raise BilibiliProviderError("resource_not_found", "Unsupported Bilibili resource identifier.", 404)
        return AccountResourceEntriesResponse(resource=resource, entries=entries, page=PageInfo(offset=offset, limit=limit, total=total, has_more=offset + len(entries) < total))

    def list_all_entries(
        self,
        account: PlatformAccount,
        cookie_file: Path,
        resource_id: str,
        *,
        page_size: int = 20,
    ) -> tuple[AccountResource, list[PlaylistEntry]]:
        offset = 0
        resource: AccountResource | None = None
        entries: list[PlaylistEntry] = []
        while True:
            page = self.list_entries(account, cookie_file, resource_id, offset, page_size)
            resource = page.resource
            entries.extend(page.entries)
            if not page.page.has_more:
                break
            offset += page.page.limit
            if offset >= 10_000:
                raise BilibiliProviderError("resource_too_large", "This Bilibili collection is too large to expand.", 422)
        if resource is None:
            raise BilibiliProviderError("resource_not_found", "Bilibili collection was not found.", 404)
        return resource, entries

    def expand_entries(
        self,
        account: PlatformAccount,
        cookie_file: Path,
        entries: list[PlaylistEntry],
    ) -> list[PlaylistEntry]:
        expanded: list[PlaylistEntry] = []
        visited_resources: set[str] = set()
        for entry in entries:
            expanded.extend(self._expand_entry(account, cookie_file, entry, visited_resources, depth=0))
        deduplicated: list[PlaylistEntry] = []
        seen: set[str] = set()
        for entry in expanded:
            key = entry.webpage_url or entry.url or entry.id or f"index:{entry.index}"
            if key in seen:
                continue
            seen.add(key)
            deduplicated.append(entry.model_copy(update={"index": len(deduplicated) + 1}))
        return deduplicated

    def _expand_entry(
        self,
        account: PlatformAccount,
        cookie_file: Path,
        entry: PlaylistEntry,
        visited_resources: set[str],
        *,
        depth: int,
    ) -> list[PlaylistEntry]:
        if not entry.is_available:
            return [entry]
        if depth > 4:
            raise BilibiliProviderError("resource_nested_too_deep", "Nested Bilibili collections are too deep to expand.", 422)
        if entry.entry_type == "favorite_collection" and entry.resource_id:
            if entry.resource_id in visited_resources:
                return []
            visited_resources.add(entry.resource_id)
            resource, children = self.list_all_entries(account, cookie_file, entry.resource_id)
            result: list[PlaylistEntry] = []
            for child in children:
                for leaf in self._expand_entry(account, cookie_file, child, visited_resources, depth=depth + 1):
                    result.append(leaf.model_copy(update={
                        "parent_id": entry.id or entry.resource_id,
                        "parent_title": entry.title or resource.title,
                    }))
            return result
        if entry.entry_type != "multipart_video" or not entry.url:
            return [entry.model_copy(update={"resource_id": None, "item_count": None})]

        bvid = as_str(entry.id)
        if not bvid or not bvid.startswith("BV"):
            return [entry.model_copy(update={"entry_type": "video", "item_count": None})]
        payload = self._get(cookie_file, "/x/web-interface/view", params={"bvid": bvid})
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        pages = as_dict_list(data.get("pages"))
        count = len(pages) or entry.item_count or 1
        if not pages:
            pages = [{"page": index, "part": f"P{index}"} for index in range(1, count + 1)]
        owner = data.get("owner") if isinstance(data.get("owner"), dict) else {}
        parent_title = entry.title or as_str(data.get("title")) or bvid
        parts: list[PlaylistEntry] = []
        for position, page in enumerate(pages, start=1):
            part_index = as_int(page.get("page")) or position
            url = f"https://www.bilibili.com/video/{bvid}/?p={part_index}"
            parts.append(PlaylistEntry(
                index=position,
                id=f"{bvid}_p{part_index}",
                title=as_str(page.get("part")) or f"P{part_index}",
                url=url,
                webpage_url=url,
                duration=as_float(page.get("duration")),
                channel=as_str(owner.get("name")) or entry.channel,
                thumbnail_url=as_str(page.get("first_frame")) or as_str(data.get("pic")) or entry.thumbnail_url,
                parent_id=bvid,
                parent_title=parent_title,
                part_index=part_index,
                part_count=len(pages),
            ))
        return parts

    @staticmethod
    def _favorite_resource(account: PlatformAccount, item: dict[str, Any], kind: str) -> AccountResource:
        external_id = as_str(item.get("id")) or ""
        upper = item.get("upper") if isinstance(item.get("upper"), dict) else {}
        owner_id = as_str(upper.get("mid")) or as_str(item.get("mid")) or account.external_id
        return AccountResource(
            id=f"{kind}:{external_id}", account_id=account.id, platform="bilibili", resource_type=kind,
            external_id=external_id, title=as_str(item.get("title")) or "Untitled favorite",
            description=as_str(item.get("intro")), cover_url=normalize_image_url(item.get("cover")),
            owner_name=as_str(upper.get("name")) or account.display_name, owner_id=owner_id,
            item_count=as_int(item.get("media_count")), is_private=bool((as_int(item.get("attr")) or 0) & 1),
            source_url=f"https://space.bilibili.com/{owner_id}/favlist?fid={external_id}", updated_at=as_int(item.get("mtime")),
        )

    @staticmethod
    def _collection_resource(account: PlatformAccount, item: dict[str, Any], kind: str) -> AccountResource:
        meta = item.get("meta") if isinstance(item.get("meta"), dict) else item
        key = "season_id" if kind == "collection" else "series_id"
        external_id = as_str(meta.get(key)) or ""
        source_url = (
            f"https://space.bilibili.com/{account.external_id}/lists/{external_id}"
            if kind == "collection" else f"https://www.bilibili.com/list/{account.external_id}?sid={external_id}"
        )
        return AccountResource(
            id=f"{kind}:{external_id}", account_id=account.id, platform="bilibili", resource_type=kind,
            external_id=external_id, title=as_str(meta.get("name")) or "Untitled collection",
            description=as_str(meta.get("description")), cover_url=normalize_image_url(meta.get("cover")),
            owner_name=account.display_name, owner_id=account.external_id, item_count=as_int(meta.get("total")),
            source_url=source_url, updated_at=as_int(meta.get("mtime")) or as_int(meta.get("last_update_ts")) or as_int(meta.get("ptime")),
        )

    @staticmethod
    def _watch_later_resource(account: PlatformAccount, total: int) -> AccountResource:
        return AccountResource(
            id="watch_later:current", account_id=account.id, platform="bilibili", resource_type="watch_later",
            external_id="current", title="Watch later", owner_name=account.display_name, owner_id=account.external_id,
            item_count=total, is_private=True, source_url="https://www.bilibili.com/watchlater/",
        )

    @staticmethod
    def _favorite_entry(item: dict[str, Any], index: int) -> PlaylistEntry:
        media_type = as_int(item.get("type")) or 2
        external_id = as_str(item.get("id")) or as_str(item.get("aid"))
        bvid = as_str(item.get("bvid")) or as_str(item.get("bv_id"))
        title = as_str(item.get("title"))
        upper = item.get("upper") if isinstance(item.get("upper"), dict) else {}
        attr = as_int(item.get("attr")) or 0
        unavailable = bool(attr & 1) or (title or "").strip(" []【】") == "已失效视频"
        page_count = max(1, as_int(item.get("page")) or 1)
        # Bilibili favorite media types: 2 video, 12 audio, 21 nested video collection.
        if media_type == 21:
            url = f"https://www.bilibili.com/medialist/detail/ml{external_id}" if external_id and not unavailable else None
            entry_type = "favorite_collection"
            resource_id = f"collected_favorite:{external_id}" if external_id else None
            entry_id = f"favorite:{external_id}" if external_id else None
        elif media_type == 12:
            url = f"https://www.bilibili.com/audio/au{external_id}" if external_id and not unavailable else None
            entry_type = "audio"
            resource_id = None
            entry_id = f"audio:{external_id}" if external_id else None
        else:
            url = f"https://www.bilibili.com/video/{bvid}" if bvid and not unavailable else None
            entry_type = "multipart_video" if page_count > 1 else "video"
            resource_id = None
            entry_id = bvid or external_id
        available = not unavailable and bool(url) and media_type != 12
        if unavailable:
            unavailable_reason = "Video is no longer available on Bilibili."
        elif media_type == 12:
            unavailable_reason = "Audio favorites are not supported by mixed video downloads."
        elif not url:
            unavailable_reason = "This favorite item type is not supported."
        else:
            unavailable_reason = None
        return PlaylistEntry(
            index=index, id=entry_id, title=title, url=url, webpage_url=url,
            duration=as_float(item.get("duration")), channel=as_str(upper.get("name")),
            thumbnail_url=as_str(item.get("cover")) or as_str(item.get("pic")),
            is_available=available,
            unavailable_reason=unavailable_reason,
            entry_type=entry_type, item_count=page_count if entry_type == "multipart_video" else None,
            resource_id=resource_id,
        )

    @staticmethod
    def _entry(item: dict[str, Any], index: int) -> PlaylistEntry:
        bvid = as_str(item.get("bvid")) or as_str(item.get("bv_id"))
        aid = as_str(item.get("id")) or as_str(item.get("aid"))
        title = as_str(item.get("title"))
        upper = item.get("upper") if isinstance(item.get("upper"), dict) else {}
        attr = as_int(item.get("attr")) or 0
        unavailable = bool(attr & 1) or (title or "").strip(" []【】") == "已失效视频"
        url = f"https://www.bilibili.com/video/{bvid}" if bvid and not unavailable else None
        return PlaylistEntry(
            index=index, id=bvid or aid, title=title, url=url, webpage_url=url,
            duration=as_float(item.get("duration")), channel=as_str(upper.get("name")),
            thumbnail_url=as_str(item.get("cover")) or as_str(item.get("pic")),
            is_available=not unavailable,
            unavailable_reason="Video is no longer available on Bilibili." if unavailable else None,
        )
