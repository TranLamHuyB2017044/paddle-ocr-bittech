import os
import shutil
import urllib.request
import zipfile
import io

def main():
    url = "https://github.com/hoaivannguyen/deepdoc_vietocr/archive/refs/heads/main.zip"
    temp_dir = "temp_deepdoc_extract"
    dest_deepdoc = os.path.join(os.path.dirname(os.path.abspath(__file__)), "deepdoc")

    print(f"📥 Đang tải mã nguồn từ {url}...")
    r = urllib.request.urlopen(url)
    print("✅ Tải xong!")

    print("📦 Đang giải nén file ZIP...")
    with zipfile.ZipFile(io.BytesIO(r.read())) as z:
        z.extractall(temp_dir)

    print(f"🔄 Đang copy thư mục deepdoc tới {dest_deepdoc}...")
    
    source_deepdoc = os.path.join(temp_dir, "deepdoc_vietocr-main")

    try:
        shutil.copytree(source_deepdoc, dest_deepdoc, dirs_exist_ok=True)
        print("✅ Copy thành công!")
    except Exception as e:
        print(f"❌ Lỗi khi copy: {e}")
    finally:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
            print("🧹 Đã dọn dẹp thư mục tạm.")

if __name__ == "__main__":
    main()
