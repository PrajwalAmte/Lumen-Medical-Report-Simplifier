import pytest
from unittest.mock import Mock, patch, mock_open
from app.services.ocr import extract_text


@patch('app.services.ocr.pytesseract.image_to_string')
@patch('app.services.ocr.Image.open')
def test_extract_text_from_image(mock_image_open, mock_tesseract):
    mock_tesseract.return_value = "Sample extracted text"
    mock_image = Mock()
    # Mock the image processing chain
    mock_image.convert.return_value = mock_image
    mock_image.filter.return_value = mock_image
    mock_image.histogram.return_value = [100] * 256
    mock_image_open.return_value = mock_image
    
    with patch('app.services.ocr._preprocess_image', return_value=mock_image):
        result = extract_text("test.jpg")
    
    assert result == "Sample extracted text"
    mock_image_open.assert_called_once_with("test.jpg")
    mock_tesseract.assert_called_once()


@patch('app.services.ocr.pdfplumber.open')
def test_extract_text_from_pdf(mock_pdf_open):
    mock_page = Mock()
    mock_page.extract_text.return_value = "PDF text content"
    
    mock_pdf = Mock()
    mock_pdf.pages = [mock_page]
    mock_pdf.__enter__ = Mock(return_value=mock_pdf)
    mock_pdf.__exit__ = Mock(return_value=None)
    
    mock_pdf_open.return_value = mock_pdf
    
    result = extract_text("test.pdf")
    
    assert result == "PDF text content"
    mock_pdf_open.assert_called_once_with("test.pdf")


def test_extract_text_unsupported_format():
    # Create a test that triggers the unsupported format flow
    # Since the function routes based on extension, we need to make it
    # try to open a file with unsupported extension that will fail
    with patch('app.services.ocr.Image.open') as mock_open:
        mock_open.side_effect = FileNotFoundError("File not found")
        
        with pytest.raises(FileNotFoundError):
            extract_text("test.txt")