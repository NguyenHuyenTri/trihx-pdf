"""Offline validation with separate integrity and certificate results."""
def signature_report(path):
    from pyhanko.pdf_utils.reader import PdfFileReader
    from pyhanko.sign.validation import validate_pdf_signature
    from pyhanko_certvalidator import ValidationContext

    lines = []
    with path.open("rb") as stream:
        reader = PdfFileReader(stream, strict=False)
        for number, signature in enumerate(reader.embedded_signatures, 1):
            try:
                status = validate_pdf_signature(signature, signer_validation_context=ValidationContext(
                    allow_fetching=False, revocation_mode="hard-fail"))
                integrity = "đạt" if status.intact and status.valid else "không đạt"
                trust = "tin cậy" if status.trusted else "chưa xác lập tin cậy"
                coverage = "toàn bộ tệp" if status.coverage.name == "ENTIRE_FILE" else "phiên bản đã ký hoặc một phần tệp"
                lines.append(f"Chữ ký {number} · Toàn vẹn: {integrity} · Chứng thư: {trust}\nPhạm vi: {coverage}.")
            except Exception as exc:
                lines.append(f"Chữ ký {number} · Chưa xác minh được ({type(exc).__name__}).")
    if not lines:
        return "Không tìm thấy chữ ký số nhúng trong PDF."
    lines.append("Kiểm tra ngoại tuyến. Kết quả phụ thuộc vào chuỗi chứng thư và dữ liệu thu hồi có sẵn.")
    return "\n\n".join(lines)
