import binascii
import json
import time
import urllib.parse
from operator import itemgetter

import aiohttp
from pydantic import BaseModel
from websockets.asyncio.client import ClientConnection, connect

from book_manager.auth import encrypt


METADATA_ENDPOINT = (
    b"68747470733a2f2f6170692e7065726c65676f2e636f6"
    b"d2f6d657461646174612f76322f6d657461646174612f626f6f6b732f"
)

BOOK_PROVIDER_ENDPOINT = b"7773733a2f2f6170692d77732e7065726c65676f2e636f6d2f626f6f6b2d64656c69766572792d6e65772f"


class BookMetadata(BaseModel):
    title: str
    subtitle: str | None
    author: str
    isbn13: str | None
    format: str | None
    cover_url: str | None


class DataProviderError(Exception):
    pass


class DataProvider:
    def __init__(
        self,
        auth_token: str,
        recaptcha_token: str,
        width: int,
    ):
        self.auth_token = auth_token
        self.recaptcha_token = recaptcha_token
        self.width = width

    @staticmethod
    async def get_metadata(book_id: int):
        endpoint = binascii.unhexlify(METADATA_ENDPOINT).decode("utf-8")
        url = urllib.parse.urljoin(endpoint, f"{book_id}")
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status != 200:
                    raise DataProviderError(
                        f"Unexpected response from server ({response.status})."
                    )

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

    async def initialize(self, socket: ClientConnection, book_id: int):
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
        chunk_meta = json.loads(full_content)
        chunk_meta = json.loads(chunk_meta)
        return chunk_meta

    async def load_page(
        self, socket: ClientConnection, book_format: str, page_id: int, part_index: int
    ):
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
        message = json.dumps(
            {"action": "loadPage", "data": encrypt(data).decode("utf-8")}
        )
        await socket.send(message)
        response = await socket.recv()

        try:
            load_page_response = json.loads(response)
        except json.JSONDecodeError as e:
            raise DataProviderError("Invalid response format") from e

        event = load_page_response.get("event")
        if event == "error":
            code = load_page_response.get("code", "Unknown")
            raise DataProviderError(f"Server error: {code}")

        if event != "pageChunk":
            raise DataProviderError(f"Unexpected event: {event}")

        data = load_page_response.get("data")
        if data is None:
            raise DataProviderError("No data returned")

        content = load_page_response.get("content")
        if content is None:
            raise DataProviderError("No content returned")

    async def fetch_contents(self, book_id: int):
        book_provider_endpoint = binascii.unhexlify(BOOK_PROVIDER_ENDPOINT).decode(
            "utf-8"
        )
        async with connect(book_provider_endpoint) as socket:
            chunk_meta = await self.initialize(socket, book_id)


        return chunk_meta
