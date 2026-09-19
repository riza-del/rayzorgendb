# Contributing to RayzorgenDB

Terima kasih atas minat kontribusi!

## Cara Kontribusi

1. Fork repository
2. Buat branch: git checkout -b fitur-baru
3. Commit: git commit -am "Tambah fitur X"
4. Push: git push origin fitur-baru
5. Buat Pull Request

## Standar Kode

- Python 3.8+
- Tanpa dependensi eksternal (wajib)
- Style: snake_case untuk fungsi, PascalCase untuk class
- Baris maks 72 karakter
- Komentar dalam Bahasa Inggris

## Test

Semua perubahan harus lolos test:

    python -m unittest discover tests

## Laporkan Bug

Buka issue dengan:
- Langkah reproduksi
- Output yang diharapkan
- Output aktual
- Python version + OS

## Fitur Baru

Diskusikan dulu di issue sebelum implementasi besar.

## Lisensi

Dengan berkontribusi, kamu setuju lisensi MIT.
