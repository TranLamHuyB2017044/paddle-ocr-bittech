"""
Test Script - Kiểm tra import các module
"""

print("="*70)
print("🧪 KIỂM TRA CẤU TRÚC MODULE MỚI")
print("="*70)
print()

# Test 1: Import config
print("1️⃣  Test import config...")
try:
    from cccd.config import (
        UPLOAD_FOLDER, 
        ALLOWED_EXTENSIONS, 
        MODEL_PATH,
        USELESS_KEYWORDS,
        DATE_KEYWORDS,
        FRONT_KEYWORDS
    )
    print(f"   ✅ Config OK")
    print(f"   📁 Upload folder: {UPLOAD_FOLDER}")
    print(f"   📦 Model path: {MODEL_PATH}")
    print(f"   🗑️  Useless keywords: {len(USELESS_KEYWORDS)} items")
except Exception as e:
    print(f"   ❌ Error: {e}")

print()

# Test 2: Import file utils
print("2️⃣  Test import file_utils...")
try:
    from cccd.utils.file_utils import allowed_file, save_uploaded_files
    print(f"   ✅ file_utils OK")
    print(f"   📝 Functions: allowed_file, save_uploaded_files")
except Exception as e:
    print(f"   ❌ Error: {e}")

print()

# Test 3: Import OCR utils
print("3️⃣  Test import ocr_utils...")
try:
    from cccd.utils.ocr_utils import ocr_extract, filter_useless_lines
    print(f"   ✅ ocr_utils OK")
    print(f"   📝 Functions: ocr_extract, filter_useless_lines")
except Exception as e:
    print(f"   ❌ Error: {e}")

print()

# Test 4: Import text cleaner
print("4️⃣  Test import text_cleaner...")
try:
    from cccd.utils.text_cleaner import selective_clean_text_front, selective_clean_text_back
    print(f"   ✅ text_cleaner OK")
    print(f"   📝 Functions: selective_clean_text_front, selective_clean_text_back")
except Exception as e:
    print(f"   ❌ Error: {e}")

print()

# Test 5: Import extractors
print("5️⃣  Test import extractors...")
try:
    from cccd.extractors.front_extractor import extract_front
    from cccd.extractors.back_extractor import extract_back
    print(f"   ✅ extractors OK")
    print(f"   📝 Functions: extract_front, extract_back")
except Exception as e:
    print(f"   ❌ Error: {e}")

print()

# Test 6: Import API routes
print("6️⃣  Test import api routes...")
try:
    from cccd.api.routes import register_routes
    print(f"   ✅ api.routes OK")
    print(f"   📝 Functions: register_routes")
except Exception as e:
    print(f"   ❌ Error: {e}")

print()

# Test 7: Import model loader (sẽ load models - có thể mất thời gian)
print("7️⃣  Test import model_loader...")
print("   ⚠️  Lưu ý: Bước này sẽ load models, có thể mất vài phút...")
try:
    from cccd.models.model_loader import model_loader
    print(f"   ✅ model_loader OK")
    print(f"   🖥️  Device: {model_loader.device}")
    print(f"   📦 OCR: {type(model_loader.ocr).__name__}")
    print(f"   🤖 Model: {type(model_loader.model).__name__}")
except Exception as e:
    print(f"   ❌ Error: {e}")

print()
print("="*70)
print("✅ HOÀN THÀNH KIỂM TRA")
print("="*70)
