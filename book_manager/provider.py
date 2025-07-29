import binascii
import urllib.parse

import aiohttp
from pydantic import BaseModel

METADATA_ENDPOINT = (
    b"68747470733a2f2f6170692e7065726c65676f2e636f6"
    b"d2f6d657461646174612f76322f6d657461646174612f626f6f6b732f"
)


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
    def __init__(self, auth_token: str, recaptcha_token: str):
        self.auth_token = auth_token
        self.recaptcha_token = recaptcha_token

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
                    raise DataProviderError(
                        f"Received error response from server: {content}."
                    )

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
