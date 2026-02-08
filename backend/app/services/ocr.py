import pytesseract
from PIL import Image, ImageEnhance, ImageFilter
import pdfplumber
import os
from pdf2image import convert_from_path


def extract_text(file_path: str) -> str:
    """Extract text from PDF or image file using appropriate method.
    
    Args:
        file_path: Path to the file to process
        
    Returns:
        str: Extracted text content
    """
    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".pdf":
        return _extract_from_pdf(file_path)
    else:
        # Handle image formats: .jpg, .jpeg, .png
        return _extract_from_image(file_path)


def _preprocess_image(img: Image.Image) -> Image.Image:
    """Enhance image quality for better OCR accuracy.
    
    Steps:
    1. Convert to grayscale
    2. Apply median filter to reduce noise
    3. Enhance contrast
    4. Apply threshold for binary conversion
    """
    img = img.convert("L")  # Convert to grayscale
    img = img.filter(ImageFilter.MedianFilter())  # Noise reduction
    enhancer = ImageEnhance.Contrast(img)
    img = enhancer.enhance(2)  # Increase contrast
    # Binary threshold: pixels below 140 become black, above become white
    img = img.point(lambda x: 0 if x < 140 else 255, '1')
    return img


def _extract_from_image(file_path: str) -> str:
    """Extract text from image using Tesseract OCR."""
    image = Image.open(file_path)
    image = _preprocess_image(image)
    # PSM 6: Uniform block of text
    text = pytesseract.image_to_string(image, config="--psm 6")
    return text.strip()


def _extract_from_pdf(file_path: str) -> str:
    """Extract text from PDF using text extraction first, fallback to OCR.
    
    Strategy:
    1. Try native text extraction with pdfplumber (faster, preserves formatting)
    2. If no text found, convert to images and use OCR (slower but works on scanned PDFs)
    """
    text_chunks = []

    # First attempt: native text extraction
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text and page_text.strip():
                text_chunks.append(page_text)

    # Fallback: OCR on PDF images if no text was extracted
    if not text_chunks:
        images = convert_from_path(file_path)
        for img in images:
            img = _preprocess_image(img)
            text = pytesseract.image_to_string(img, config="--psm 6")
            if text.strip():
                text_chunks.append(text)

    return "\n".join(text_chunks).strip()

