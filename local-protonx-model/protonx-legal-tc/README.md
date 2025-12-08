---
license_file: LICENSE.md
library_name: protonx-text-correction
tags:
- text-to-text
language:
- vi
---

<div align="center">

<p align="center">
    <img src="https://storage.googleapis.com/mle-courses-prod/users/61b6fa1ba83a7e37c8309756/private-files/678dadd0-603b-11ef-b0a7-998b84b38d43-ProtonX_logo_horizontally__1_.png" width="260"/>
</p>

<h1 align="center">
High-Accuracy Vietnamese Text Correction v1.3.1
</h1>

[![GitHub](https://img.shields.io/badge/ProtonX-GitHub-black?logo=github)](https://github.com/protonx-engineering/protonx-text-correction)
[![HuggingFace](https://img.shields.io/badge/HuggingFace-Model-black?logo=huggingface)](https://huggingface.co/protonx-models/protonx-tc)
[![Website](https://img.shields.io/badge/protonx.co-Website-blue)](https://protonx.co)
[![Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/drive/17m37QYMG4LO6oyMdkTxNtFzQW8uWDd_-?usp=sharing)


</div>

---

## **Introduction**

<img src="https://storage.googleapis.com/mle-courses-prod/users/61b6fa1ba83a7e37c8309756/private-files/1795a9d0-cb4d-11f0-a59b-27096d42dd86-Screen_Shot_2025-11-27_at_11.53.12.png">

### **ProtonX Text Correction (v1.3-NC)**

A specialized Vietnamese text correction model engineered for high-accuracy normalization of legal and enterprise text. Optimized for OCR post-processing (including PaddleOCR outputs), but also capable of cleaning broader Vietnamese text with diacritic restoration, segmentation repair, and correction of domain-specific terminology.


<img src="https://protonx.co/assets/img/paddle-ocr-protonx.png">

The model is optimized to clean up real-world OCR mistakes such as:

* missing or incorrect diacritics
* broken word segmentation
* misrecognized legal terms
* punctuation artifacts
* formatting inconsistencies

Built on a Seq2Seq Transformer architecture, the model is trained on 800,000 correction pairs, including 30,000 pairs manually annotated by expert Vietnamese annotators, covering:

* official legal documents
* OCR outputs from scanned PDFs
* colloquial → standardized legal text

Strict constraints ensure:

* **Correction ≠ rewriting**
* meaning of legal text must never change
* no hallucination / no added legal terms
* confidence-based correction
* no paraphrasing

---

## **LICENSE**

This model is released under the ProtonX Text Correction Model License (v1.3-NC).

See [LICENSE.md](./LICENSE.md) for full terms, conditions, and usage restrictions.

## **Current Version**: v1.3.1


## **Highlights**

- Supports a maximum context length of 160 tokens

- Introduces enhanced post-correction for Paddle-OCR VL output

- Includes targeted mitigation for hallucination behavior on long input sentences


---

## **Quick Usage with Transformers**

```python
import torch
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM

model_path = "protonx-models/protonx-legal-tc"

tokenizer = AutoTokenizer.from_pretrained(model_path)
model = AutoModelForSeq2SeqLM.from_pretrained(model_path)

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
model.to(device)
model.eval()

examples = [
       "Điều 10. Điều kiện bảo đảm an ninh mạng đối với thiết bị, phân cứng, phân m遮挡 thành phận hệ thống 1. Các thiết bị phàn cứng là thành phàn hệ thông phải được kiểm tra an ninh mạng để phát hiện diểm yếu, lỗ hỏng bảo mất, mã độc, thiết bị thu phát, phàn cứng độc hại bảo đảm sự tương thích với các thành phàn khác trong hệ thông thông tin quan trọng về an ninh quốc gia. Các thiết bị quản trị phải được cải đạt hệ điều hành, phàn mêm sạch, có các lóp tương lữa bảo vệ. Hệ thông thông tin xử lý bí mật nhà nước không được kết nối với mạng Internet.",
]

max_tokens = 160

for text in examples:
    inputs = tokenizer(
        text,
        return_tensors="pt",
        truncation=True,
        max_length=max_tokens
    ).to(device)

    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            num_beams=10,
            num_return_sequences=1,     # <- return all beams
            max_new_tokens=max_tokens,
            early_stopping=True,
            return_dict_in_generate=True,  # <- return full dict
            output_scores=True             # <- include beam scores
        )

    sequences = outputs.sequences
    scores = outputs.sequences_scores

    print(f"Inpput: {text}")

    for i, (seq, score) in enumerate(zip(sequences, scores)):
        decoded = tokenizer.decode(seq, skip_special_tokens=True)
        # print(f"Beam {i+1} | Score: {float(score):.4f}")
        print(f"Output: {decoded}")
        print("-" * 40)
```

---

## **Benchmark**

### **ProtonX Legal Text Correction Validation Dataset**

| Metric        | Score     |
| ------------- | --------- |
| **ROUGE-L**   | **Coming soon** |

---


## **Training Details**

* Model: Seq2Seq Transformer
* Legal-domain augmentation
* Beam search decoding
* Max sequence length: 256 tokens total (128 tokens for input and 128 tokens for output).
* High-precision diacritic + punctuation restoration

### Domain Coverage:

* Government decrees
* Resolutions
* Contract clauses
* Administrative procedures
* OCR-normalized scanned documents

---

## **Example Outputs**


**Input:**

```
Điều 10. Điều kiện bảo đảm an ninh mạng đối với thiết bị, phân cứng, phân m遮挡 thành phận hệ thống 1. Các thiết bị phàn cứng là thành phàn hệ thông phải được kiểm tra an ninh mạng để phát hiện diểm yếu, lỗ hỏng bảo mất, mã độc, thiết bị thu phát, phàn cứng độc hại bảo đảm sự tương thích với các thành phàn khác trong hệ thông thông tin quan trọng về an ninh quốc gia. Các thiết bị quản trị phải được cải đạt hệ điều hành, phàn mêm sạch, có các lóp tương lữa bảo vệ. Hệ thông thông tin xử lý bí mật nhà nước không được kết nối với mạng Internet.
```

**Output:**

```
Điều 10. Điều kiện bảo đảm an ninh mạng đối với thiết bị, phần cứng, phần mềm là thành phần hệ thống 1. Các thiết bị phần cứng là thành phần hệ thống phải được kiểm tra an ninh mạng để phát hiện điểm yếu, lỗ hổng bảo mật, mã độc, thiết bị thu phát, phần cứng độc hại bảo đảm sự tương thích với các thành phần khác trong hệ thống thông tin quan trọng về an ninh quốc gia. Các thiết bị quản trị phải được cài đặt hệ điều hành, phần mềm sạch, có các lớp tường lửa bảo vệ. Hệ thống thông tin xử lý bí mật nhà nước không được kết nối với mạng Internet.
```

---

## **Use Cases**

* Legal OCR text normalization
* Standardizing government documents
* Contract proofreading
* Preprocessing for legal RAG systems
* Administrative workflow automation
* Compliance document processing

---

## **Limitations**

* Does not paraphrase or rewrite legal clauses
* Cannot restore missing semantic content
* Primarily optimized for Vietnamese
* Not designed for informal social media slang

---

## **Future Work**

* Achieving even higher ROUGE-L performance on legal-domain datasets
* Extending maximum sequence length from 128 to 1024 tokens for long-clause legal documents
---

## **Acknowledgments**

Thanks to:

* [vit5-base](https://huggingface.co/VietAI/vit5-base)
