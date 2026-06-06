#!/bin/sh
#  curl -X POST -F "file=@./test_docs/inputs/pdfs/CBP-9112.pdf" http://0.0.0.0:8060/
#  curl -X POST -F "file=@./dev_temp/temp_26-04-11_13-26-58/input_text/CBP-9112_0.txt" http://0.0.0.0:8060/argmine-ibis
curl -X POST -F "file=@./dev_temp/temp_26-04-11_15-00_deepseek-ai/input_text/CBP-9112_1.txt" http://0.0.0.0:8060/argmine-ibis
