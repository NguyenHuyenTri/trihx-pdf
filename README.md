# TRIHX Office

Ứng dụng Windows 10/11 x64 quản lý PDF, Word, Excel và PowerPoint theo tab. PDF được đọc và in trực tiếp. Tệp Office dùng Microsoft Office desktop đã cài để sửa và lưu bản gốc. Đóng tab TRIHX Office không đóng tài liệu trong Microsoft Office.

## Cài đặt

Trong GitHub Actions, mở lần chạy thành công của **Build Windows EXE** và tải artifact **TRIHX-Office-Setup-Windows-x64**. Giải nén artifact để lấy `TRIHX Office Setup.exe`. Bộ cài tạo lối tắt Start và Desktop, có mục gỡ cài đặt và đăng ký **Open with** cho PDF. Windows tự quản lý lựa chọn ứng dụng mặc định.

Nếu đang dùng bản mã nguồn, đóng ứng dụng và chạy lại `capnhat.bat` để tạo `dist\HX PDF.exe`. Máy người dùng cài từ Setup không cần Python hoặc Git.

## Đọc và in

- PDF cuộn liên tục, tìm và sao chép chữ, `Ctrl` + lăn chuột để thu phóng. Menu **Vừa trang** cũng có **Vừa chiều rộng** và **100%**.
- **Chữ ký số** báo kết quả kiểm tra ngoại tuyến độc lập với hình chữ ký hoặc con dấu trên trang.
- **Print** mở bản xem trước, có phạm vi trang, lọc chẵn/lẻ, số bản, khổ giấy, hướng giấy, tỷ lệ và hai mặt theo driver. Có thể in hai mặt thủ công sau khi thử hướng nạp giấy.
- **Hỗ trợ in** mở hàng đợi, gửi trang kiểm tra, sao chép chẩn đoán và thử lại dạng ảnh sau khi xác nhận.
- Tab Office chuyển tới cửa sổ Microsoft Office thật. Mục **Cửa sổ Office** cho thử ẩn tiêu đề và khôi phục cửa sổ. Khả năng căn cửa sổ và ẩn tiêu đề phụ thuộc phiên bản Office và cấu hình Windows.
