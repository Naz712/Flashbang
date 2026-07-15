
from pypdf import PdfReader

def extract_text_from_pdf(pdf_path):
    reader = PdfReader(pdf_path)
    text = ""
    for page in reader.pages:
        text += page.extract_text() + "\n"
    return text

if __name__ == "__main__":
    pdf_path = r"C:\Users\Nazzoom\Downloads\Y22 notes\rb2302\Part 2\Slides_PDF\Lecture3_Transformer1.pdf" 
    extracted_text = extract_text_from_pdf(pdf_path)
    print(extracted_text)