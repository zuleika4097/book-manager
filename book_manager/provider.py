import binascii
import json
import logging
import os
import time
import urllib.parse
from operator import itemgetter
from rich.progress import track

import aiohttp
from pydantic import BaseModel
from websockets.client import WebSocketClientProtocol, connect

from book_manager.auth import encrypt
from book_manager.config import DEFAULT_CACHE_DIR

METADATA_ENDPOINT = (
    b"68747470733a2f2f6170692e7065726c65676f2e636f6" b"d2f6d657461646174612f76322f6d657461646174612f626f6f6b732f"
)

BOOK_PROVIDER_ENDPOINT = b"7773733a2f2f6170692d77732e7065726c65676f2e636f6d2f626f6f6b2d64656c69766572792d6e65772f"


logger = logging.getLogger("rich")


class BookMetadata(BaseModel):
    title: str
    subtitle: str | None
    author: str
    isbn13: str | None
    format: str | None
    cover_url: str | None


class BookChapterMetadata(BaseModel):
    book_type: str
    num_chapters: int
    book_map: dict[int, int | None]


class DataProviderError(Exception):
    pass


class DataProvider:
    def __init__(
        self,
        auth_token: str,
        recaptcha_token: str,
        width: int,
        cache_dir: str = DEFAULT_CACHE_DIR,
    ):
        self.auth_token = auth_token
        self.recaptcha_token = recaptcha_token
        self.width = width
        self.cache_dir = cache_dir

        if not os.path.exists(cache_dir):
            os.makedirs(cache_dir)

    @staticmethod
    async def get_metadata(book_id: int):
        endpoint = binascii.unhexlify(METADATA_ENDPOINT).decode("utf-8")
        url = urllib.parse.urljoin(endpoint, f"{book_id}")
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status != 200:
                    raise DataProviderError(f"Unexpected response from server ({response.status}).")

                content = await response.json()

        if not content.get("success"):
            raise DataProviderError(f"Received error response from server: {content}.")

        meta_info = content.get("data", {}).get("results", [])
        if len(meta_info) == 0:
            raise DataProviderError(f"No results found for book id {book_id}.")

        book_metadata = meta_info[0]
        title = book_metadata.get("title")
        if title is None:
            raise DataProviderError(f"No title found on book id {book_id}.")

        author = book_metadata.get("author")
        if author is None:
            raise DataProviderError(f"No author found on book id {book_id}.")

        return BookMetadata(
            title=title,
            subtitle=book_metadata.get("subtitle"),
            author=author,
            isbn13=book_metadata.get("isbn13"),
            format=book_metadata.get("format"),
            cover_url=book_metadata.get("cover"),
        )

    async def initialize(self, socket: WebSocketClientProtocol, book_id: int):
        message = json.dumps(
            {
                "action": "initialise",
                "data": {
                    "authToken": self.auth_token,
                    "reCaptchaToken": self.recaptcha_token,
                    "bookId": book_id,
                },
            }
        )
        await socket.send(message)

        chunk_info: dict[int, str] = {}

        while True:
            response = await socket.recv()

            try:
                load_page_response = json.loads(response)
            except json.JSONDecodeError as e:
                raise DataProviderError("Invalid response format") from e

            event = load_page_response.get("event")
            if event == "error":
                code = load_page_response.get("code", "Unknown")
                raise DataProviderError(f"Server error: {code}")

            if event != "initialisationDataChunk":
                raise DataProviderError(f"Unexpected event: {event}")

            data = load_page_response.get("data")
            if data is None:
                raise DataProviderError("No data returned")

            total_chunk_num = data.get("numberOfChunks")
            if total_chunk_num is None:
                raise DataProviderError("Missing total chunk number")

            chunk_num = data.get("chunkNumber")
            if chunk_num is None:
                raise DataProviderError("Missing chunk number")

            content = data.get("content")
            if content is None:
                raise DataProviderError("Missing content")

            chunk_info[chunk_num] = content
            if len(chunk_info) < total_chunk_num:
                continue

            break

        # Meta is double encoded
        full_content = "".join(map(itemgetter(1), sorted(chunk_info.items())))
        book_chapter_meta = json.loads(full_content)
        book_chapter_meta = json.loads(book_chapter_meta)
        book_type = book_chapter_meta.get("bookType")
        if book_type is None:
            raise DataProviderError("Missing book type")

        num_chapters = book_chapter_meta.get("numberOfChapters")
        if num_chapters is None:
            raise DataProviderError("Missing number of chapters")

        book_map = book_chapter_meta.get("bookMap", {i + 1: None for i in range(num_chapters)})
        book_map = {key: int(len(value)) if value is not None else 0 for key, value in book_map.items()}
        return BookChapterMetadata(book_type=book_type, num_chapters=num_chapters, book_map=book_map)

    async def load_page(self, socket: WebSocketClientProtocol, book_format: str, page_id: int, part_index: int):
        timestamp = int(time.time() * 1000)
        data = json.dumps(
            {
                "authToken": self.auth_token,
                "pageId": page_id,
                "bookType": book_format,
                "windowWidth": self.width,
                "mergedChapterPartIndex": part_index,
                "clientTimestamp": timestamp,
            }
        )
        message = json.dumps({"action": "loadPage", "data": encrypt(data).decode("utf-8")})
        await socket.send(message)

        page_content = {}
        merged_chapter_chunk_sizes = {}
        while True:
            response = await socket.recv()

            try:
                load_page_response = json.loads(response)
            except json.JSONDecodeError as e:
                raise DataProviderError("Invalid response format") from e

            event: str = load_page_response.get("event")
            data = load_page_response.get("data", {})
            if event == "error":
                code = data.get("code", "Unknown")
                message = data.get("message", "Unknown")
                raise DataProviderError(f"Server error ({code}): {message}")

            if not event.startswith("pageChunk"):
                raise DataProviderError(f"Unexpected event: {event}")

            data = load_page_response.get("data")
            if data is None:
                raise DataProviderError("No data returned")

            total_chunk_num = data.get("numberOfChunks")
            if total_chunk_num is None:
                raise DataProviderError("Missing total chunk number")

            chunk_num = data.get("chunkNumber")
            if chunk_num is None:
                raise DataProviderError("Missing chunk number")

            total_merged_chapter_num = data.get("numberOfMergedChapters", 1)
            merged_chapter_num = data.get("mergedChapterNumber", 1)

            content = data.get("content")
            if content is None:
                raise DataProviderError("No content returned")

            merged_chapter_content = page_content.setdefault(merged_chapter_num, {})
            merged_chapter_content[chunk_num] = content
            merged_chapter_chunk_sizes[merged_chapter_num] = total_chunk_num

            if len(page_content) < total_merged_chapter_num:
                continue

            if any(
                len(merged_chapter_content) < merged_chapter_chunk_sizes[chapter_no]
                for chapter_no, merged_chapter_content in page_content.items()
            ):
                continue

            break

        full_content = ""
        for chapter_no, merged_chapter_content in sorted(page_content.items()):
            full_content += "".join(map(itemgetter(1), sorted(merged_chapter_content.items())))

        return full_content

    async def fetch_contents(self, book_id: int):
        book_provider_endpoint = binascii.unhexlify(BOOK_PROVIDER_ENDPOINT).decode("utf-8")

        book_cache = os.path.join(self.cache_dir, str(book_id), "chunks.dat")

        contents = {}

        if os.path.exists(book_cache):
            logger.info(f"[bold green]Found cached content[/bold green]: {book_cache}.", extra={"markup": True})
            with open(book_cache, "r", encoding="utf-8") as f:
                cached_content = json.load(f)
                contents = {int(key): part for key, part in cached_content.items()}

        try:
            async with connect(book_provider_endpoint) as socket:
                book_chapter_meta = await self.initialize(socket, book_id)

                for chapter, part_count in track(
                    book_chapter_meta.book_map.items(),
                    description="Downloading chapters...",
                ):
                    for part_no in range(part_count + 1):
                        if chapter + part_no in contents:
                            continue

                        part_content = await self.load_page(socket, book_chapter_meta.book_type, chapter, part_no)
                        contents[chapter + part_no] = part_content

            return contents
        finally:
            with open(book_cache, "w", encoding="utf-8") as f:
                json.dump(contents, f)
