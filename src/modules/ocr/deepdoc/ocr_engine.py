import os
import sys

# Thêm src vào sys.path để các absolute import (from deepdoc.module...) hoạt động
current_dir = os.path.dirname(os.path.abspath(__file__))
deepdoc_root = os.path.dirname(current_dir) # Đây là /app/src trong container
if deepdoc_root not in sys.path:
    sys.path.insert(0, deepdoc_root)

from deepdoc.module.ocr_onnx import OCR

class DeepDocOCR:
    def __init__(self):
        self.engine = OCR()

    def __call__(self, img):
        return self.engine(img)
