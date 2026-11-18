# TRIHX PDF

Ứng dụng Windows 10/11 x64 để đọc, in và chuyển PDF sang Word.

## Cài đặt

Tải [bộ cài TRIHX PDF cho Windows x64](https://github.com/NguyenHuyenTri/trihx-pdf/releases/latest/download/TRIHX-PDF-Setup-Windows-x64.exe) và chạy tệp vừa tải. Nếu đã cài phiên bản cũ, đóng ứng dụng rồi chạy bộ cài này để nâng cấp tại chỗ. Mở lại TRIHX PDF từ lối tắt trên Desktop hoặc Start.

Từ phiên bản 0.3.0, bấm **Cập nhật** ở góc dưới bên phải cửa sổ, kể cả khi chưa mở PDF. Nếu có phiên bản mới, bấm **Tải bản mới**. Khi ứng dụng kiểm tra xong bộ cài, bấm **Cài đặt**. Các tab sẽ đóng và trình cài đặt Windows sẽ mở. Bạn có thể đóng hộp cập nhật để tiếp tục đọc.

Nếu tự dựng chương trình từ mã nguồn, `capnhat.bat` vẫn tạo `dist\HX PDF.exe`. Để phát hành phiên bản mới, tăng số phiên bản trong `version.ini` theo dạng `X.Y.Z` rồi đưa thay đổi lên nhánh `main`. Workflow **Build Windows EXE** kiểm tra ứng dụng, dựng bộ cài Windows và đăng bộ cài lên GitHub Releases. Nút **Cập nhật** đọc bản phát hành chính thức mới nhất.

## Đọc và in

- Bấm **Giao diện** ở góc trên bên phải để chọn **Sáng**, **Tối** hoặc **Màu tùy chọn…**. Màu đã chọn áp dụng ngay cho cửa sổ, thanh công cụ và hộp in. Ứng dụng ghi nhớ lựa chọn cho lần mở sau. Trang tài liệu và bản in dùng màu gốc của PDF.
- PDF cuộn liên tục, tìm và sao chép chữ, `Ctrl` + lăn chuột để thu phóng. Menu **Vừa trang** cũng có **Vừa chiều rộng** và **100%**.
- **Chữ ký số** báo kết quả kiểm tra ngoại tuyến độc lập với hình chữ ký hoặc con dấu trên trang.
- **Print** mở bản xem trước, có phạm vi trang, lọc chẵn/lẻ, số bản, khổ giấy, hướng giấy, tỷ lệ và hai mặt theo driver. Có thể in hai mặt thủ công sau khi thử hướng nạp giấy.
- **Hỗ trợ in** mở hàng đợi, gửi trang kiểm tra, sao chép chẩn đoán và thử lại dạng ảnh sau khi xác nhận.
## Chuyển PDF sang Word

Mở PDF và chọn **PDF sang Word** để lưu tệp DOCX có thể chỉnh sửa. Ứng dụng phục dựng chữ, hình và bảng có đường kẻ. Tài liệu nhiều cột, bảng phức tạp, con dấu và bố cục đặc biệt cần rà lại trong Word. Tệp PDF gốc được giữ nguyên và chữ ký số không chuyển sang DOCX.

PDF có trang scan chỉ chứa ảnh vẫn có thể mở và in. Khi chuyển sang Word, ứng dụng sẽ báo số trang thiếu lớp văn bản và dừng xuất tệp.
