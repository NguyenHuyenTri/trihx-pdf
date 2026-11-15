# TRIHX PDF

Ứng dụng Windows 10/11 x64 để đọc, in và chuyển PDF sang Word.

## Cài đặt

Trong GitHub Actions, mở lần chạy thành công của **Build Windows EXE** và tải artifact **TRIHX-Office-Setup-Windows-x64**. Giải nén artifact để lấy `TRIHX Office Setup.exe`. Bộ cài tạo lối tắt Start và Desktop, có mục gỡ cài đặt và đăng ký **Open with** cho PDF. Windows tự quản lý lựa chọn ứng dụng mặc định.

Nếu đang dùng bản mã nguồn, đóng ứng dụng và chạy lại `capnhat.bat` để tạo `dist\HX PDF.exe`. Máy người dùng cài từ Setup không cần Python hoặc Git.

## Đọc và in

- PDF cuộn liên tục, tìm và sao chép chữ, `Ctrl` + lăn chuột để thu phóng. Menu **Vừa trang** cũng có **Vừa chiều rộng** và **100%**.
- **Chữ ký số** báo kết quả kiểm tra ngoại tuyến độc lập với hình chữ ký hoặc con dấu trên trang.
- **Print** mở bản xem trước, có phạm vi trang, lọc chẵn/lẻ, số bản, khổ giấy, hướng giấy, tỷ lệ và hai mặt theo driver. Có thể in hai mặt thủ công sau khi thử hướng nạp giấy.
- **Hỗ trợ in** mở hàng đợi, gửi trang kiểm tra, sao chép chẩn đoán và thử lại dạng ảnh sau khi xác nhận.
## Chuyển PDF sang Word

Mở PDF và chọn **PDF sang Word** để lưu tệp DOCX có thể chỉnh sửa. Ứng dụng phục dựng chữ, hình và bảng có đường kẻ. Tài liệu nhiều cột, bảng phức tạp, con dấu và bố cục đặc biệt cần rà lại trong Word. Tệp PDF gốc được giữ nguyên và chữ ký số không chuyển sang DOCX.

Với trang scan không có lớp chữ, cài **Tesseract OCR 5** và chọn dữ liệu tiếng Việt (`vie.traineddata`). Để TRIHX tìm thấy Tesseract, cài vào thư mục Tesseract-OCR mặc định hoặc thêm thư mục chứa `tesseract.exe` vào PATH. Quá trình nhận dạng thực hiện trên máy. Bảng scan xuất thành văn bản để rà lại.
