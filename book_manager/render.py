import math
import os
import re

from pyppeteer.browser import Browser


EPUB_HORIZONTAL_MARGIN = 62
EPUB_VERTICAL_MARGIN = 56


def pre_render_content(content: str):
    content = re.sub(
        r'<img id="trigger" data-chapterid="[0-9]*?" src="" onerror="LoadChapter\(&apos;[0-9]*?&apos;\)" />\n',
        "",
        content,
    )

    # Reveal hidden images
    hidden_images = re.findall("<img.*?>", content, re.S)
    for img in hidden_images:
        img_new = img.replace("opacity: 0", "opacity: 1")
        img_new = img_new.replace("data-src", "src")
        content = content.replace(img, img_new)

    return content.strip()


async def page_render(browser: Browser, part_no: int, content: str, cache_dir: str, book_format: str):
    page = await browser.newPage()
    await page.setUserAgent(
        r"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        r"(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
    )

    content = pre_render_content(content)
    with open(f"{cache_dir}/{part_no}.html", "w", encoding="utf-8") as f:
        f.write(content)
        os.fsync(f.fileno())

    await page.goto(
        f"file://{cache_dir}/{part_no}.html",
        {"waitUntil": ["load", "domcontentloaded", "networkidle0", "networkidle2"], "timeout": 0},
    )

    # Set PDF options
    options = {}
    width, height = await page.evaluate(
        "() => { return [document.documentElement.scrollWidth, document.documentElement.scrollHeight]}"
    )
    page_height = width * math.sqrt(2)
    scale = min(page_height / height, 1)
    if part_no == 0:
        options["scale"] = scale
        options["width"] = width
        options["height"] = page_height
    else:
        match book_format:
            case "PDF":
                options["width"] = width
                options["height"] = height
            case "EPUB":
                options["margin"] = {
                    "top": str(EPUB_VERTICAL_MARGIN),
                    "bottom": str(EPUB_VERTICAL_MARGIN),
                    "left": str(EPUB_HORIZONTAL_MARGIN),
                    "right": str(EPUB_HORIZONTAL_MARGIN),
                }

    document = await page.pdf(options)
    await page.close()
    return document
