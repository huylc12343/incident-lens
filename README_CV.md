# Hướng dẫn cấu hình bài toán che mờ biển số và khuôn mặt

File chạy chính:

```text
src/agents/nodes/detect_and_blur.py
```

Hai model mặc định:

```text
src/models/best_cv.pt
src/models/face_yolov8n.pt
```

## 1. Đường dẫn model

Trong `src/agents/nodes/detect_and_blur.py`, đường dẫn mặc định của hai model được khai báo trong hàm `main()`:

```python
src_dir = Path(__file__).resolve().parents[2]
default_plate_weights = src_dir / "models" / "best_cv.pt"
default_face_weights = src_dir / "models" / "face_yolov8n.pt"
```

- `default_plate_weights`: model nhận diện biển số.
- `default_face_weights`: model nhận diện khuôn mặt.
- Đường dẫn được tính từ vị trí của file Python, không phụ thuộc vào ổ đĩa hoặc thư mục đang mở trong terminal.

Nếu chuyển model sang thư mục khác hoặc đổi tên file, hãy sửa phần nằm sau `src_dir`. Ví dụ model được chuyển sang `src/weights/`:

```python
default_plate_weights = src_dir / "weights" / "best_cv.pt"
default_face_weights = src_dir / "weights" / "face_yolov8n.pt"
```

Cũng có thể chọn model khác khi chạy mà không cần sửa mã nguồn:

```powershell
python src/agents/nodes/detect_and_blur.py `
  --source "duong/dan/video.mp4" `
  --plate-weights "duong/dan/model-bien-so.pt" `
  --face-weights "duong/dan/model-khuon-mat.pt"
```

## 2. Chọn đầu vào (input)

Đầu vào được truyền qua tham số bắt buộc `--source`.

Chạy với một file video:

```powershell
python src/agents/nodes/detect_and_blur.py --source "D:\Videos\input.mp4"
```

Nếu đường dẫn có khoảng trắng, phải đặt đường dẫn trong dấu ngoặc kép.

Chạy với webcam mặc định (webcam số `0`):

```powershell
python src/agents/nodes/detect_and_blur.py --source 0
```

Phần xử lý đường dẫn input nằm trong hàm `main()`, ngay dưới chú thích:

```python
# --- Resolve and validate source ---
source_str = args.source.strip()
```

## 3. Đường dẫn đầu ra (output)

Mặc định, chương trình tự tạo thư mục kết quả mới để không ghi đè lần chạy trước:

```text
runs/detect/run_1/output.mp4
runs/detect/run_2/output.mp4
runs/detect/run_3/output.mp4
...
```

Phần cấu hình output nằm trong hàm `main()`:

```python
run_dir = get_next_run_dir(base_dir="runs/detect")
run_dir.mkdir(parents=True, exist_ok=True)
output_path = run_dir / "output.mp4"
```

Muốn đổi thư mục chứa kết quả, sửa giá trị `base_dir`. Ví dụ:

```python
run_dir = get_next_run_dir(base_dir="D:/Videos/results")
```

Muốn đổi tên file kết quả, sửa `output.mp4`. Ví dụ:

```python
output_path = run_dir / "video_da_che_mo.mp4"
```

Lưu ý: đường dẫn output tương đối như `runs/detect` được tính từ thư mục hiện tại của terminal khi chạy lệnh. Nên chạy lệnh tại thư mục gốc của dự án để kết quả luôn nằm trong dự án.

## 4. Ví dụ chạy đầy đủ

Mở PowerShell tại thư mục gốc `P-207`, sau đó chạy:

```powershell
python src/agents/nodes/detect_and_blur.py --source "D:\Videos\input.mp4"
```

Chương trình sẽ dùng hai model trong `src/models/` và in đường dẫn tuyệt đối của file kết quả khi hoàn tất.
