import base64
import anthropic
from dotenv import load_dotenv

load_dotenv()
client = anthropic.Anthropic()

def extract_text_from_pdf_vision(pdf_path):
    with open(pdf_path, "rb") as f:
        pdf_data = base64.standard_b64encode(f.read()).decode("utf-8")
    
    response = client.messages.create(
        model="claude-sonnet-4-5",  
        max_tokens=8000,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": pdf_data
                    }
                },
                {
                    "type": "text",
                    "text": """Extract all text from this PDF document in reading order.
                                        Transcribe equations as LaTeX and make sure the equation is not altered and make sure to include any relevant explanation to the math or equation.
                                        Transcribe tables as Markdown tables.
                                        Transcribe code exactly how it is stated in the notes and make sure to include any relevant explanation to the code.
                                        do not describe what the image is decoratively, instead interpret what the image is conveying
                                        Return only the extracted content. Do not add preamble, commentary, or explanation."""
                }
            ]
        }]
    )
    
    return response.content[0].text

if __name__ == "__main__":
    pdf_path = r"C:\Users\Nazzoom\Downloads\Y22 notes\rb2302\Part 2\Slides_PDF\Lecture3_Transformer1.pdf"
    text = extract_text_from_pdf_vision(pdf_path)
    print(text)
