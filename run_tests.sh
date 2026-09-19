#!/bin/bash
# Jalankan semua test RayzorgenDB

echo "================================"
echo "  RayzorgenDB Test Suite"
echo "================================"
echo ""

python -m unittest discover tests -v

echo ""
echo "================================"
echo "  Selesai"
echo "================================"
