@echo off
py -m pip install -r requirements.txt pyinstaller
py -m PyInstaller --noconfirm --onefile --name GerberXORComparator gerber_compare_files.py
