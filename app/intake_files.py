import os

import pymupdf4llm
from langchain_text_splitters import RecursiveCharacterTextSplitter

text_splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
    encoding_name="cl100k_base", chunk_size=45000, chunk_overlap=0
)

# Return a dict so chunks are asssociated with the name of their file
def pdf_2_txt(input_path):
    doc_md_text = pymupdf4llm.to_markdown(input_path)
    chunks = text_splitter.split_text(doc_md_text)
    
    return chunks

def url_2_txt(input_path):
    # Do some stuff with Beautiful Soup
    # return a string
    pass

def input_2_txt(input_path):
    # Check if it's a URL
    # if yes, call a URL function

    # Check if it's a pdf
    # if yes, call a pdf function

    # Otherwise, complain and quit.
    
    # Return the result of the text-producing function
    pass

# Given paths to PDFs, return as a list of texts.
# Texts are returned as a list of dicts, with the origin and the text:
# - 'origin': the original filename of the pdf
# - 'text_chunks': a list of strings with the extracted text
# ('text_chunks' will only be len>1 in case where original file is too long)
def create_texts(list_of_paths, save_to_dir=''):
    text_list = []
    for f in list_of_paths:
        orig_name = os.path.basename(f)
        text_chunks = pdf_2_txt(f)

        text_list.append({
            'origin': orig_name,
            'text' : text_chunks
        })
        
        if save_to_dir:
            file_name = orig_name.rsplit('.',1)[0]
            if len(text_chunks) == 1:
                with open(os.path.join(save_to_dir, f"{file_name}.txt"), 'w') as f:
                    f.write(text_chunks[0])
            elif len(text_chunks) > 1:
                counter = 0
                for c in text_chunks:
                    with open(os.path.join(save_to_dir, f"{file_name}_{counter}.txt"), 'w') as f:
                        f.write(c)
                    counter +=1

    return text_list