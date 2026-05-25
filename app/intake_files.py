import os

import pymupdf4llm
from langchain_text_splitters import RecursiveCharacterTextSplitter



def chunk_text(input_txt, text_splitter):
    chunks = text_splitter.split_text(input_txt)
    return chunks

# Return a dict so chunks are asssociated with the name of their file
def pdf_to_chunks(input_path, text_splitter):
    doc_md_text = pymupdf4llm.to_markdown(input_path)
    chunks = chunk_text(doc_md_text, text_splitter)
    return chunks

def txt_to_chunks(input_path, text_splitter):
    with open(input_path) as f:
        orig_text = f.read()
    chunks = chunk_text(orig_text, text_splitter)
    return chunks


# Given paths to files, return as a list of texts.
# Texts are returned as a list of dicts, with the origin and the text:
# - 'origin': the original filename
# - 'text_chunks': a list of strings with the extracted text of max the required size
def create_texts(list_of_paths, chunk_size=1500, save_to_dir=''):

    text_splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        encoding_name="cl100k_base", chunk_size=chunk_size, chunk_overlap=0
    )

    text_list = []
    for fpath in list_of_paths:
        orig_name = os.path.basename(fpath)
        type = orig_name.rsplit('.',1)[-1]
        
        if type == 'pdf':
            text_chunks = pdf_to_chunks(fpath, text_splitter)
        elif type == 'txt':
            text_chunks = txt_to_chunks(fpath, text_splitter)
        else:
            continue

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