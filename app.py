from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from paddleocr import PaddleOCR
import torch
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
import os
import re
from datetime import datetime
from PIL import Image
import numpy as np
import cv2
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# Cấu hình
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'bmp'}
MODEL_PATH = "protonx-models/protonx-legal-tc"

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB

# Global variables for models
ocr = None
tokenizer = None
model = None
device = None

def initialize_models():
    """Khởi tạo các models (OCR + Transformers)"""
    global ocr, tokenizer, model, device
    
    try:
        logger.info("🔄 Initializing PaddleOCR...")
        ocr = PaddleOCR(
            lang="vi",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
        )
        logger.info("✅ PaddleOCR initialized successfully")
        
        logger.info("🔄 Initializing Transformers model...")
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        logger.info(f"📱 Using device: {device}")
        
        tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH)
        model = AutoModelForSeq2SeqLM.from_pretrained(MODEL_PATH)
        model.to(device)
        model.eval()
        logger.info("✅ Transformers model initialized successfully")
        
    except Exception as e:
        logger.error(f"❌ Error initializing models: {str(e)}")
        raise

def allowed_file(filename):
    """Kiểm tra file extension"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def extract_text_from_image(image_path):
    """
    Trích xuất text từ ảnh sử dụng PaddleOCR
    Returns: list of extracted texts and their scores
    """
    try:
        result = ocr.predict(image_path)
        extracted_texts = []
        scores = []
        for block in result:               
            extracted_texts = block["rec_texts"]
            scores = block["rec_scores"]

        output_text = "\n".join(extracted_texts)
        print("===== OCR OUTPUT =====")
        print(output_text)
        
        return extracted_texts, scores
        
    except Exception as e:
        logger.error(f"Error in OCR extraction: {str(e)}")
        raise

def classify_text(text):
    """
    Phân loại văn bản sử dụng Transformers model
    Returns: classified text and score
    """
    try:
        inputs = tokenizer(
            text,
            return_tensors="pt",
            truncation=True,
            max_length=128
        ).to(device)
        
        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                num_beams=10,
                num_return_sequences=1,
                max_new_tokens=128,
                length_penalty=1.0,
                early_stopping=True,
                repetition_penalty=1.2,
                no_repeat_ngram_size=2,
                return_dict_in_generate=True,
                output_scores=True
            )
        
        sequences = outputs.sequences
        scores = outputs.sequences_scores
        
        decoded = tokenizer.decode(sequences[0], skip_special_tokens=True)
        score = float(scores[0]) if len(scores) > 0 else 0.0
        
        return decoded, score
        
    except Exception as e:
        logger.error(f"Error in text classification: {str(e)}")
        return text, 0.0

def extract_id_card_info(texts, ocr_scores):
    """
    Trích xuất thông tin căn cước từ danh sách text
    """
    full_text = ' '.join(texts)
    
    info = {
        'id_number': None,
        'full_name': None,
        'date_of_birth': None,
        'gender': None,
        'nationality': None,
        'place_of_origin': None,
        'place_of_residence': None,
        'expiry_date': None,
    }
    
    # Tìm số CCCD (12 chữ số)
    id_pattern = r'\b\d{12}\b'
    id_match = re.search(id_pattern, full_text)
    if id_match:
        info['id_number'] = id_match.group()
    
    # Tìm họ tên
    for i, text in enumerate(texts):
        if 'tên' in text.lower() or 'name' in text.lower():
            if i + 1 < len(texts):
                name_candidate = texts[i + 1]
                if re.match(r'^[A-ZÀÁẠẢÃÂẦẤẬẨẪĂẰẮẶẲẴÈÉẸẺẼÊỀẾỆỂỄÌÍỊỈĨÒÓỌỎÕÔỒỐỘỔỖƠỜỚỢỞỠÙÚỤỦŨƯỪỨỰỬỮỲÝỴỶỸĐ\s]+$', name_candidate, re.IGNORECASE):
                    info['full_name'] = name_candidate
                    break
    
    # Tìm ngày sinh và ngày hết hạn
    date_pattern = r'\b(\d{2})[/-](\d{2})[/-](\d{4})\b'
    for text in texts:
        date_match = re.search(date_pattern, text)
        if date_match:
            if not info['date_of_birth']:
                info['date_of_birth'] = date_match.group()
            elif not info['expiry_date']:
                info['expiry_date'] = date_match.group()
    
    # Tìm giới tính
    for text in texts:
        if 'nam' in text.lower() and len(text) < 10:
            info['gender'] = 'Nam'
            break
        elif 'nữ' in text.lower() and len(text) < 10:
            info['gender'] = 'Nữ'
            break
    
    # Tìm quốc tịch
    for text in texts:
        if 'việt nam' in text.lower() or 'viet nam' in text.lower():
            info['nationality'] = 'Việt Nam'
            break
    
    # Tìm quê quán và nơi thường trú
    for i, text in enumerate(texts):
        if 'quê quán' in text.lower() or 'origin' in text.lower():
            if i + 1 < len(texts):
                info['place_of_origin'] = texts[i + 1]
        if 'thường trú' in text.lower() or 'residence' in text.lower():
            if i + 1 < len(texts):
                residence_parts = []
                for j in range(i + 1, min(i + 4, len(texts))):
                    if not any(keyword in texts[j].lower() for keyword in ['có giá trị', 'expiry', 'ngày']):
                        residence_parts.append(texts[j])
                    else:
                        break
                info['place_of_residence'] = ', '.join(residence_parts)
    
    return info

@app.route('/')
def index():
    """Render trang chủ"""
    return render_template('index.html')

@app.route('/api/detect', methods=['POST'])
def detect_and_classify():
    """
    API endpoint chính:
    1. Nhận ảnh
    2. OCR để trích xuất text
    3. Phân loại text với Transformers
    4. Trích xuất thông tin CCCD (nếu có)
    5. Trả về JSON
    """
    try:
        # Validate request
        if 'file' not in request.files:
            return jsonify({
                'success': False,
                'error': 'Không tìm thấy file trong request'
            }), 400
        
        file = request.files['file']
        
        if file.filename == '':
            return jsonify({
                'success': False,
                'error': 'Chưa chọn file'
            }), 400
        
        if not allowed_file(file.filename):
            return jsonify({
                'success': False,
                'error': f'File không hợp lệ. Chỉ chấp nhận: {", ".join(ALLOWED_EXTENSIONS)}'
            }), 400
        
        # Save file
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{timestamp}_{file.filename}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        logger.info(f"📁 File saved: {filename}")
        
        # Step 1: OCR - Extract text from image
        logger.info("🔍 Extracting text with OCR...")
        extracted_texts, ocr_scores = extract_text_from_image(filepath)
        
        if not extracted_texts:
            return jsonify({
                'success': False,
                'error': 'Không thể đọc được text từ ảnh'
            }), 400
        
        logger.info(f"✅ Extracted {len(extracted_texts)} text lines")
        
        # Step 2: Classify each text line
        logger.info("🤖 Classifying texts with Transformers...")
        classified_results = []
        
        for text, ocr_score in zip(extracted_texts, ocr_scores):
            classified_text, class_score = classify_text(text)
            classified_results.append({
                'original_text': text,
                'ocr_confidence': round(ocr_score, 4),
                'classified_text': classified_text,
                'classification_score': round(class_score, 4)
            })
        
        logger.info(f"✅ Classified {len(classified_results)} texts")
        
        # Step 3: Extract ID card info (if applicable)
        id_card_info = extract_id_card_info(extracted_texts, ocr_scores)
        
        # Step 4: Prepare response
        response_data = {
            'success': True,
            'filename': filename,
            'total_texts': len(extracted_texts),
            'ocr_results': classified_results,
            'id_card_info': id_card_info,
            'raw_text': extracted_texts,
            'processing_info': {
                'ocr_engine': 'PaddleOCR',
                'classification_model': MODEL_PATH,
                'device': str(device),
                'timestamp': datetime.now().isoformat()
            }
        }
        
        logger.info("✅ Processing completed successfully")
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"❌ Error processing request: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Lỗi xử lý: {str(e)}'
        }), 500

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'service': 'OCR + Legal Text Classification API',
        'models': {
            'ocr': 'PaddleOCR (Vietnamese)',
            'classifier': MODEL_PATH,
            'device': str(device) if device else 'not initialized'
        },
        'timestamp': datetime.now().isoformat()
    })

@app.route('/api/info', methods=['GET'])
def api_info():
    """API information endpoint"""
    return jsonify({
        'api_version': '2.0.0',
        'endpoints': {
            'POST /api/detect': 'Upload image for OCR + classification',
            'GET /api/health': 'Health check',
            'GET /api/info': 'API information'
        },
        'supported_formats': list(ALLOWED_EXTENSIONS),
        'max_file_size': '16MB',
        'features': [
            'Vietnamese OCR with PaddleOCR',
            'Legal text classification with Transformers',
            'ID card information extraction',
            'Confidence scores for all predictions'
        ]
    })

# Initialize models on startup
logger.info("🚀 Starting OCR + Legal Text Classification API...")
initialize_models()
logger.info("✅ All models initialized successfully")

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    # Bật debug=True để tự động reload khi sửa code
    # Lưu ý: Việc này sẽ khiến model bị load lại mỗi khi save file
    app.run(debug=True, host='0.0.0.0', port=port)
