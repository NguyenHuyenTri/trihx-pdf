# HX PDF

Ứng dụng đọc PDF trên Windows. Tài liệu được xử lý trực tiếp trên máy tính.

## Tính năng

- Mở PDF bằng hộp thoại hoặc kéo thả tệp vào cửa sổ.
- Cuộn dọc liên tục qua các trang; có điều hướng trang, thu phóng và vừa trang.
- Tìm văn bản trong tài liệu.
- In với cấu hình máy in, khổ giấy, hướng giấy, màu và số bản.
- Hiển thị chú thích và trường biểu mẫu PDF khi có thể.

## Lần đầu thiết lập trên máy Windows

Cài Git và Python, sau đó mở Command Prompt tại nơi muốn lưu dự án và chạy:

```bat
git clone https://github.com/NguyenHuyenTri/trihx-pdf.git
cd trihx-pdf
capnhat.bat
```

Lệnh đầu chỉ cần chạy một lần. Tệp chạy được tạo tại `dist\HX PDF.exe`.

## Cập nhật sau này

Mở thư mục dự án đã clone và nhấp đúp `capnhat.bat`. Tệp này lấy mã mới nhất từ GitHub, cài các thư viện cần thiết và tạo lại `dist\HX PDF.exe`.

## Tự build bằng tay

```bat
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt pyinstaller
python -m PyInstaller --clean --noconfirm PDFReader.spec
```
