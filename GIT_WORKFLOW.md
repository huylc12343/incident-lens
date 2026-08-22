# Git workflow P-207

## Vai trò nhánh

```text
feature/*  →  develop  →  docker  →  main
```

- `feature/*`: một tính năng hoặc phần việc độc lập. Ví dụ: `feature/frontend`, `feature/ai-brain`, `feature/backend`.
- `develop`: tích hợp cho phiên bản phát triển kế tiếp. Chỉ nhận PR đã review và CI pass.
- `docker`: staging/deploy trên EC2. Nội dung phải luôn deploy được bằng `git pull origin docker` và `docker compose up -d --build`.
- `main`: release ổn định; chỉ nhận PR đã kiểm thử thành công trên `docker`/EC2.

## Quy tắc commit và pull request

- Mỗi PR có phạm vi nhỏ, mô tả rõ thay đổi, cách test và ảnh hưởng deploy.
- Không commit `.env`, API key, `.ssh/`, `.next*`, `node_modules`, cache, ZIP, video mẫu hay build artifact. Video cần versioning phải dùng Git LFS đã được team chấp thuận.
- Không dùng `git add .` khi workspace có file local/artifact. Chỉ stage các file đã xem lại bằng đường dẫn cụ thể.
- Không force push, rewrite history hay merge vào `docker`/`main` khi CI chưa pass.
- PR sang `develop`, `docker`, `main` cần review; dùng merge commit hoặc squash theo quy ước team.

## Quy trình làm việc hằng ngày

```powershell
git switch develop
git pull --ff-only origin develop
git switch -c feature/<ten-cong-viec>

# Sau khi review diff cục bộ:
git add src/... frontend/...
git commit -m "feat(scope): mo ta ngan gon"
git push -u origin feature/<ten-cong-viec>
```

Tạo PR `feature/<ten-cong-viec> → develop`. Chỉ merge sau khi CI pass và review được chấp thuận.

## Quy trình deploy EC2

1. Sau CI của `develop`, tạo PR `develop → docker`.
2. Merge chỉ khi compose, healthcheck và biến môi trường deploy đã được kiểm tra.
3. Trên EC2, dùng đúng quy trình hiện hành:

```powershell
git switch docker
git pull --ff-only origin docker
docker compose up -d --build
docker compose ps
docker compose logs --tail 100
```

4. Backend không được public trực tiếp. Docker Compose nên chỉ expose frontend/reverse proxy ra internet; backend dùng network nội bộ và proxy chuyển tiếp các route API cần thiết.
5. Xác nhận healthcheck, luồng upload/AI, log lỗi và rollback plan trước khi chuyển sang `main`.

## Quy trình release main và tag

1. Khi EC2 staging ổn định, tạo PR `docker → main`.
2. Sau CI/review, merge PR và checkout commit release.
3. Tạo annotated tag và push tag (thay `<version>`):

```powershell
git switch main
git pull --ff-only origin main
git tag -a v<version> -m "Release v<version>"
git push origin v<version>
```

Không tạo tag trước khi release commit đã được xác nhận trên EC2.

## Khôi phục an toàn khi merge conflict

Trước một thao tác có thể tạo conflict, lưu thay đổi local có chủ đích:

```powershell
git status
git add <file-da-kiem-tra-1> <file-da-kiem-tra-2>
git stash push -u -m "wip: truoc khi merge <nhanh>"
```

Khi đang merge và muốn hủy merge chưa commit:

```powershell
git merge --abort
git status
```

Khi đang rebase và muốn hủy rebase:

```powershell
git rebase --abort
git status
```

Sau khi xử lý conflict thủ công, kiểm tra diff, stage đúng file rồi tiếp tục:

```powershell
git diff --check
git add <file-da-xu-ly>
git merge --continue
```

Khôi phục thay đổi đã stash chỉ sau khi nhánh sạch:

```powershell
git stash list
git stash apply stash@{0}
```

Không dùng `git reset --hard`, `git clean -fd`, force push hoặc xóa nhánh để giải quyết conflict.
