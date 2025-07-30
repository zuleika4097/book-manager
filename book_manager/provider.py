import binascii
import json
import logging
import os
import re
import time
import urllib.parse
from operator import itemgetter
from pathlib import Path
from typing import Any, Literal

import aiohttp
from pydantic import (
    BaseModel,
    Field,
    model_validator,
    computed_field,
    TypeAdapter,
    field_serializer,
    ConfigDict,
    field_validator,
)
from websockets.client import WebSocketClientProtocol, connect

from book_manager.auth import encrypt
from book_manager.config import DEFAULT_CACHE_DIR

METADATA_ENDPOINT = (
    b"68747470733a2f2f6170692e7065726c65676f2e636f6d2f6d657461646174612f76322f6d657461646174612f626f6f6b732f"
)

BOOK_PROVIDER_ENDPOINT = b"7773733a2f2f6170692d77732e7065726c65676f2e636f6d2f626f6f6b2d64656c69766572792d6e65772f"


logger = logging.getLogger("rich")


class DataProviderError(Exception):
    pass


class BookMetadata(BaseModel):
    title: str
    author: str
    subtitle: str | None = None
    num_pages: int | None = None
    isbn13: str | None = None
    format: str | None = None

    @field_validator("num_pages", mode="before")
    @classmethod
    def corce_empty(cls, value: Any) -> Any:
        if value == "":
            return None

        return value


class BookChapterMetadata(BaseModel):
    book_type: str = Field(validation_alias="bookType")
    num_chapters: int = Field(validation_alias="numberOfChapters")
    book_map: dict[int, list[int]] | None = Field(None, validation_alias="bookMap")

    @model_validator(mode="before")
    @classmethod
    def remove_double_encoding(cls, data: Any) -> Any:
        if not isinstance(data, str):
            return data

        return json.loads(data)

    @computed_field
    def chapter_lengths(self) -> dict[int, int]:
        if self.book_map is None:
            return {i + 1: 1 for i in range(self.num_chapters)}

        book_map = {key: len(value) + 1 for key, value in self.book_map.items()}
        return book_map


class ErrorDetails(BaseModel):
    code: int
    message: str


class ErrorResponse(BaseModel):
    event: Literal["error"]
    data: ErrorDetails


class InitCommandData(BaseModel):
    auth_token: str = Field(serialization_alias="authToken")
    recaptcha_token: str = Field(serialization_alias="reCaptchaToken")
    book_id: int = Field(serialization_alias="bookId")

    model_config = ConfigDict(serialize_by_alias=True)


class InitCommand(BaseModel):
    action: Literal["initialise"]
    data: InitCommandData


class InitCommandResponseChunk(BaseModel):
    total_chunk_num: int = Field(validation_alias="numberOfChunks")
    chunk_num: int = Field(validation_alias="chunkNumber")
    content: str


class InitCommandResponse(BaseModel):
    event: Literal["initialisationDataChunk"]
    data: InitCommandResponseChunk


class LoadPageCommandData(BaseModel):
    auth_token: str = Field(serialization_alias="authToken")
    page_id: int = Field(serialization_alias="pageId")
    book_format: str = Field(serialization_alias="bookType")
    width: int = Field(serialization_alias="windowWidth")
    part_index: int = Field(serialization_alias="mergedChapterPartIndex")
    timestamp: int = Field(serialization_alias="clientTimestamp", default_factory=lambda: int(time.time() * 1000))

    model_config = ConfigDict(serialize_by_alias=True)


class LoadPageCommand(BaseModel):
    action: Literal["loadPage"]
    data: LoadPageCommandData

    @field_serializer("data")
    def encode_data(self, data: LoadPageCommandData, _info):
        return encrypt(data.auth_token, data.model_dump_json()).decode("utf-8")


class PageLoadCommandChunk(BaseModel):
    total_chunk_num: int = Field(validation_alias="numberOfChunks")
    chunk_num: int = Field(validation_alias="chunkNumber")
    total_merged_chapter_num: int | None = Field(None, validation_alias="mergedChapterNumber")
    merged_chapter_num: int | None = Field(None, validation_alias="numberOfMergedChapters")
    content: str


class LoadPageCommandResponse(BaseModel):
    event: str
    data: PageLoadCommandChunk

    @field_validator("event", mode="after")
    @classmethod
    def validate_event(cls, event: str) -> str:
        if not re.match(r"^pageChunk-\d+$", event):
            raise ValueError(f"Unexpected event: {event}")

        return event


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
        return BookMetadata.model_validate(book_metadata)

    async def initialize(self, socket: WebSocketClientProtocol, book_id: int):
        command = InitCommand(
            action="initialise",
            data=InitCommandData(auth_token=self.auth_token, recaptcha_token=self.recaptcha_token, book_id=book_id),
        )
        await socket.send(command.model_dump_json())

        chunk_info: dict[int, str] = {}
        while True:
            response = await socket.recv()
            adapter: TypeAdapter[ErrorResponse | InitCommandResponse] = TypeAdapter(ErrorResponse | InitCommandResponse)
            parsed_response = adapter.validate_json(response)
            if isinstance(parsed_response, ErrorResponse):
                code = parsed_response.data.code
                message = parsed_response.data.message
                raise DataProviderError(f"Server error({code}): {message}")

            chunk_data = parsed_response.data
            chunk_info[chunk_data.chunk_num] = chunk_data.content
            if len(chunk_info) < chunk_data.total_chunk_num:
                continue

            break

        full_content = "".join(map(itemgetter(1), sorted(chunk_info.items())))
        book_chapter_meta = BookChapterMetadata.model_validate_json(full_content)
        return book_chapter_meta

    async def load_page(self, socket: WebSocketClientProtocol, book_format: str, page_id: int, part_index: int):
        command = LoadPageCommand(
            action="loadPage",
            data=LoadPageCommandData(
                auth_token=self.auth_token,
                page_id=page_id,
                book_format=book_format,
                width=self.width,
                part_index=part_index,
            ),
        )
        await socket.send(command.model_dump_json())

        page_content: dict[int, dict[int, str]] = {}
        merged_chapter_chunk_sizes: dict[int, int] = {}
        while True:
            response = await socket.recv()
            adapter: TypeAdapter[ErrorResponse | LoadPageCommandResponse] = TypeAdapter(
                ErrorResponse | LoadPageCommandResponse
            )
            parsed_response = adapter.validate_json(response)
            if isinstance(parsed_response, ErrorResponse):
                code = parsed_response.data.code
                message = parsed_response.data.message
                raise DataProviderError(f"Server error({code}): {message}")

            chunk_data = parsed_response.data
            total_merged_chapter_num = (
                chunk_data.total_merged_chapter_num if chunk_data.total_merged_chapter_num is not None else 1
            )
            merged_chapter_content = page_content.setdefault(chunk_data.merged_chapter_num, {})
            merged_chapter_content[chunk_data.chunk_num] = chunk_data.content
            merged_chapter_chunk_sizes[chunk_data.merged_chapter_num] = chunk_data.total_chunk_num
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

        book_cache_dir = Path(self.cache_dir) / str(book_id)
        book_cache = book_cache_dir / "chunks.dat"

        content_cache: dict[int, str] = {}

        if not os.path.exists(book_cache_dir):
            os.makedirs(book_cache_dir)

        if os.path.exists(book_cache):
            logger.info(f"[bold green]Found cached content[/bold green]: {book_cache}.", extra={"markup": True})
            with open(book_cache, "r", encoding="utf-8") as f:
                adapter = TypeAdapter(dict[int, str])
                raw_content_cache = f.read()
                content_cache = adapter.validate_json(raw_content_cache)

        try:
            async with connect(book_provider_endpoint) as socket:
                book_chapter_meta = await self.initialize(socket, book_id)
                sorted_chapter_meta = sorted(book_chapter_meta.chapter_lengths.items())
                num_parts = sum(map(itemgetter(1), sorted_chapter_meta))
                for chapter, part_count in sorted_chapter_meta:
                    for part_no in range(part_count):
                        part_ind = chapter + part_no
                        if part_ind in content_cache:
                            part_content = content_cache[part_ind]
                        else:
                            part_content = await self.load_page(socket, book_chapter_meta.book_type, chapter, part_no)
                            content_cache[part_ind] = part_content

                        yield part_ind, part_content, num_parts

        finally:
            with open(book_cache, "w", encoding="utf-8") as f:
                json.dump(content_cache, f)
