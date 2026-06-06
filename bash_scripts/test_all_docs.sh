#!/bin/sh
 curl -X POST -F "file=@./test_docs/inputs/pdfs/CBP-9112.pdf" -F "file=@./test_docs/inputs/pdfs/s12941-025-00793-9.pdf" -F "file=@./test_docs/inputs/pdfs/Shaping-COVID-decade-addressing-long-term-societal-impacts-COVID-19.pdf" -F "file=@./test_docs/inputs/pdfs/TA-9-2023-0282_EN.pdf" http://0.0.0.0:8060/
  