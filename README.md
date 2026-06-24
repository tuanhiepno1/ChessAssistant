# ChessAssistant

Ứng dụng trợ lý phân tích cờ vua cho Windows. Ứng dụng đọc bàn cờ trong trình duyệt hoặc từ hình ảnh, dựng FEN, phân tích bằng Stockfish và hiển thị nước đi gợi ý.

## Tính năng

- Giao diện PySide6 bằng tiếng Việt.
- Theo dõi bàn cờ trên Chess.com, Lichess, ChessBase và ChessClub qua Chrome DevTools.
- Đọc FEN/SAN/DOM theo adapter riêng cho từng website.
- Phân tích Stockfish nền, không khóa giao diện.
- Thời gian phân tích cố định hoặc tự điều chỉnh theo độ khó.
- Sách khai cuộc Polyglot và Syzygy tablebase tùy chọn.
- Nhận diện bàn cờ bằng ảnh/YOLO khi không dùng được DOM.
- Hiển thị ô đi, ô đến và overlay trên bàn cờ website.

## Yêu cầu hệ thống

- Windows 10 hoặc Windows 11 64-bit.
- Python 3.11 trở lên, bản 64-bit.
- Một trình duyệt Chromium được hỗ trợ: Cốc Cốc, Google Chrome, Microsoft Edge hoặc Brave. Windows 10/11 thường đã có sẵn Microsoft Edge.
- Stockfish bản Windows 64-bit.
- Khuyến nghị tối thiểu 8 GB RAM; chế độ Mạnh nhất phù hợp hơn với máy 16–32 GB RAM.

Không sao chép thư mục `.venv` từ máy khác. Mỗi máy phải tạo lại môi trường Python để các thư viện native đúng với hệ điều hành và phiên bản Python.

## Cài đặt nhanh trên máy Windows mới

### 1. Cài công cụ nền

Cài các phần mềm sau:

1. Git for Windows.
2. Python 3.11 hoặc mới hơn. Khi cài, chọn **Add Python to PATH**.
3. Một trình duyệt được hỗ trợ. Có thể dùng Microsoft Edge có sẵn trên Windows; không bắt buộc cài Cốc Cốc hoặc Chrome.
4. Stockfish cho Windows 64-bit từ trang chính thức của Stockfish và giải nén vào một thư mục cố định, ví dụ:

```text
C:\Tools\Stockfish\stockfish.exe
```

Nếu máy cũ hoặc không hỗ trợ AVX2, chọn đúng build Stockfish tương thích CPU.

### 2. Clone repository

```powershell
cd C:\Projects
git clone https://github.com/tuanhiepno1/ChessAssistant.git
cd ChessAssistant
```

### 3. Cài thư viện tự động

Mở PowerShell trong thư mục project:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\setup_windows.ps1
```

Script sẽ:

- Tạo `.venv`.
- Nâng cấp `pip`.
- Cài toàn bộ dependency trong `requirements.txt`.
- Kiểm tra model nhận diện.

Hoặc cài thủ công:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 4. Khởi động lần đầu

Nhấp đúp:

```text
MoTroLyCoVua.bat
```

Ứng dụng sẽ tự tìm Cốc Cốc, Google Chrome, Microsoft Edge rồi Brave, và mở trình duyệt đầu tiên tìm thấy với cổng DevTools `9222`.

Trình duyệt này dùng profile riêng trong thư mục tạm của Windows để không ảnh hưởng profile cá nhân và để DevTools hoạt động ổn định. Vì vậy, lần đầu chạy trên máy mới có thể cần đăng nhập lại tài khoản Chess.com, Lichess, ChessBase hoặc ChessClub trong cửa sổ trình duyệt do ứng dụng mở. Không tự mở website bằng một cửa sổ trình duyệt thông thường khác vì cửa sổ đó không có cổng DevTools `9222`.

Trong cửa sổ **Cài đặt → Stockfish**:

1. Chọn đường dẫn tới `stockfish.exe` vừa giải nén.
2. Chọn chế độ phù hợp cấu hình máy.
3. Bấm **Lưu**.

File `config/settings.json` sẽ tự được tạo trên máy mới. File này chứa đường dẫn và cấu hình riêng của máy nên không được commit lên Git.

### 5. Kiểm tra nhanh trước khi chơi

1. Chọn **Tôi cầm Trắng** hoặc **Tôi cầm Đen** đúng với ván hiện tại.
2. Bấm nút website cần chơi và đăng nhập trong trình duyệt do ứng dụng mở.
3. Vào một ván, chờ dòng trạng thái báo đã đọc được bàn cờ và lượt đi.
4. Nếu Stockfish chưa chạy, mở **Cài đặt → Stockfish**, chọn đúng file `.exe`, lưu rồi bấm **Tính lại nước tốt nhất**.

## Chế độ hiển thị và live stream

Nút **Overlay trên web** chuyển giữa hai cách hiển thị:

- **BẬT**: với chess.com và Lichess, vẽ tối đa 3 mũi tên màu nối rõ ô nguồn–đích, đánh số `#1`–`#3` trên đường đi và hiện điểm tại ô đích. Để không che bàn cờ, overlay dùng `E` cho **ENGINE** và `T` cho **THỰC DỤNG**; UI app vẫn ghi đầy đủ. Ô nguồn dùng viền trắng nét đứt để không gây nhầm khi một quân có nhiều phương án; bàn cờ trong ứng dụng được ẩn để giao diện gọn hơn.
- Các nước có nhãn `E` hoặc `T` được vẽ trên cùng, đậm và rõ hơn; các phương án còn lại mảnh, mờ hơn để không che lựa chọn ưu tiên.
- **TẮT**: xóa dấu gợi ý khỏi website và hiển thị bàn cờ, mũi tên cùng chỉ dẫn trong ứng dụng. Dùng chế độ này khi live stream website để overlay không xuất hiện trên luồng phát.

Lựa chọn được lưu trong `config/settings.json` và được giữ lại ở lần mở ứng dụng tiếp theo. Phần log luôn tự cuộn tới sự kiện mới nhất.

Preset **Rapid** dùng chung cấu hình tối ưu cho Chess.com và Lichess: 8 luồng, Hash 2048 MB, 3 phương án, thời gian thông minh 0,7–3 giây và Ponder bật. Website được chọn bằng các nút mở trang riêng, nên không cần hai preset Rapid trùng lặp.

Trên Windows, tiến trình Stockfish chạy ở mức ưu tiên **Below Normal**: engine vẫn dùng đủ 8 luồng khi CPU rảnh, nhưng tự nhường CPU cho trình duyệt và UI khi có tranh chấp tài nguyên để overlay và thao tác bàn cờ giữ độ mượt.

Ponder chạy khi DOM cung cấp FEN chính xác. App ưu tiên lấy nước trả lời dự đoán từ PV đã lưu; nếu nước người chơi không nằm trong các PV đó, Stockfish dùng tối đa khoảng 200 ms để dự đoán nhanh nước đối thủ rồi tiếp tục tính 3 PV trong toàn bộ lượt đối thủ. Badge cập nhật tiến độ thật `0/3`–`3/3` và độ sâu `D`; trạng thái **Sẵn sàng** yêu cầu đủ 3 PV từ độ sâu 8, sau đó Stockfish vẫn tiếp tục đào sâu. Khi đối thủ đi, app gửi `ponderhit` nếu FEN khớp hoặc `stop` nếu dự đoán sai. Nếu Ponder hit nhưng Stockfish mới trả một phần MultiPV, app hiện ngay dữ liệu có sẵn và dùng tối đa khoảng 650 ms để bổ sung các phương án còn thiếu. Ponder miss cũng hiển thị gợi ý nhanh sau khoảng 650 ms rồi tiếp tục tinh chỉnh nền. Search nền có trần an toàn 10 giây và luôn được dừng khi đổi preset, website, bên chơi hoặc bắt đầu ván mới. Chu kỳ đọc bàn cờ là 150 ms.

Badge cạnh **Độ khó thế cờ** hiển thị trực tiếp trạng thái Ponder: xám khi chờ/tắt, tím khi đang tính, xanh ngọc khi đã chuẩn bị, xanh lá khi ponder hit, vàng khi đang dùng gợi ý nhanh sau ponder miss và xanh dương khi đã có kết quả cuối. Badge kèm thời gian tính để phân biệt rõ kết quả tức thời với kết quả đã phân tích đầy đủ.

Trong danh sách phương án, nhãn **ENGINE** luôn chỉ nước Stockfish xếp hạng đầu. Nhãn **THỰC DỤNG** chỉ phương án tự nhiên, dễ chơi và có mức mất điểm chấp nhận được; nhãn này có thể trùng với nước engine khi không có lựa chọn thay thế đủ an toàn.

Trên màn hình dọc 1080p, bảng kết quả ưu tiên **Độ khó thế cờ** và **Các lựa chọn**. Khối nước tốt nhất riêng được lược khỏi bố cục vì đã trùng với phương án `#1`; độ sâu, chi tiết engine và trạng thái nằm thấp hơn trong vùng cuộn.

Khung điều khiển dùng bố cục 8 cột, 5 hàng: các preset cùng hàng, bốn nút website cùng hàng và trạng thái overlay nằm cạnh tóm tắt cấu hình. Chiều cao nút, khoảng cách và phần đệm được giảm để dành thêm không gian cho kết quả.

Số phương án tự đổi theo nhịp độ trên Chess.com/Lichess: Rapid dùng `3`, Blitz dùng `2`, Bullet dùng `1`. Bullet chỉ hiện lựa chọn `E`; Blitz vẫn có thể so sánh `E` và `T`. Các giá trị này có thể chỉnh trong **Cài đặt → Nhịp độ → Số phương án**.

Nút **Bullet** dùng fast path riêng: không dùng sách khai cuộc, 6 luồng Stockfish ở `150 ms/nước`, quét DOM mỗi `50 ms`, và bắt đầu tính trước phản hồi ngay khi đưa nước gợi ý cho người chơi; bấm lại để trở về cấu hình mặc định mạnh.

## Kiểm tra cài đặt

Chạy toàn bộ test:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Khởi động trực tiếp để xem lỗi trên terminal:

```powershell
.\.venv\Scripts\python.exe TroLyCoVua.pyw
```

## Tài nguyên tùy chọn

### Model YOLO

File mặc định:

```text
models\chess_piece_model.pt
```

Nếu thiếu model, chế độ đọc DOM vẫn hoạt động nhưng nhận diện bàn cờ từ ảnh sẽ không dùng được.

### Sách khai cuộc

Repository có thể dùng file nhỏ:

```text
books\lichess_2025_1000_1600.bin
```

File Cerebellum đầy đủ lớn hơn giới hạn file GitHub thông thường nên không được commit. Nếu tự tải, chọn lại đường dẫn trong **Cài đặt → Khai cuộc**.

### Syzygy tablebase

Syzygy là tùy chọn và có dung lượng rất lớn, vì vậy các file `.rtbw/.rtbz` không được lưu trong Git.

Có thể tải bộ 3–4–5 quân bằng script:

```powershell
.\.venv\Scripts\python.exe scripts\download_syzygy_345.py
```

Sau khi tải xong, vào **Cài đặt → Tàn cuộc**, chọn thư mục Syzygy và bật tablebase.

Nếu không cần Syzygy, để tính năng này ở trạng thái tắt; Stockfish vẫn phân tích bình thường.

## Cấu hình mẫu

Tham khảo:

```text
config\settings.example.json
```

Không đổi tên file mẫu thành cấu hình dùng chung trong Git. Ứng dụng tự tạo `config/settings.json` riêng cho từng máy.

## Xử lý lỗi thường gặp

### Không tìm thấy Stockfish

Mở **Cài đặt → Stockfish** và chọn lại đúng file `.exe`. Không dùng đường dẫn từ máy khác.

### Không kết nối được cổng DevTools 9222

1. Đóng toàn bộ tiến trình ứng dụng và trình duyệt do ứng dụng mở.
2. Chạy lại bằng `MoTroLyCoVua.bat`.
3. Kiểm tra Cốc Cốc/Chrome/Edge/Brave không bị phần mềm bảo mật chặn tham số remote debugging.
4. Không mở đồng thời một trình duyệt khác bằng cổng `9222`; mỗi máy chỉ nên để ChessAssistant quản lý một phiên DevTools này.

### PowerShell chặn script

Chỉ mở quyền thực thi cho cửa sổ hiện tại:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
```

### Máy yếu hoặc giao diện chậm

- Chọn chế độ **Yếu** hoặc **Trung bình**.
- Giảm số luồng và Hash trong Cài đặt.
- Bật **Thời gian thông minh**.
- Không đặt Hash gần bằng toàn bộ RAM của máy.

## Cấu trúc chính

```text
app/           Khởi động ứng dụng và trình duyệt
books/         Polyglot opening book
chess_tools/   Dựng và đồng bộ vị trí cờ
config/        Cấu hình
core/          Phần cứng và quản lý cấu hình
engine/        UCI/Stockfish
scripts/       Script cài đặt và tải tài nguyên
tablebase/     Syzygy manager
tests/         Unit tests
ui/            Giao diện PySide6
vision/        DOM, chụp màn hình và nhận diện quân
```

## Lưu ý sử dụng

Ứng dụng chỉ hiển thị phân tích và gợi ý. Người dùng tự chịu trách nhiệm tuân thủ điều khoản của website, giải đấu và nền tảng cờ vua đang sử dụng.
