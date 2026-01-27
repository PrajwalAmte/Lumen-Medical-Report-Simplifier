import pytesseract
from PIL import Image, ImageEnhance, ImageFilter
import pdfplumber
import os
from pdf2image import convert_from_path


def extract_text(file_path: str) -> str:
    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".pdf":
        return _extract_from_pdf(file_path)
    else:
        return _extract_from_image(file_path)


def _preprocess_image(img: Image.Image) -> Image.Image:
    img = img.convert("L")
    img = img.filter(ImageFilter.MedianFilter())
    enhancer = ImageEnhance.Contrast(img)
    img = enhancer.enhance(2)
    img = img.point(lambda x: 0 if x < 140 else 255, '1')
    return img


def _extract_from_image(file_path: str) -> str:
    image = Image.open(file_path)
    image = _preprocess_image(image)
    text = pytesseract.image_to_string(image, config="--psm 6")
    return text.strip()


def _extract_from_pdf(file_path: str) -> str:
    text_chunks = []

    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text and page_text.strip():
                text_chunks.append(page_text)

    if not text_chunks:
        images = convert_from_path(file_path)
        for img in images:
            img = _preprocess_image(img)
            text = pytesseract.image_to_string(img, config="--psm 6")
            if text.strip():
                text_chunks.append(text)

    return "\n".join(text_chunks).strip()

